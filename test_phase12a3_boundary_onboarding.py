import hashlib, json, sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from caribbean_jurisdiction_inventory import CaribbeanJurisdictionInventory, validate_inventory
from database import Base
from jurisdiction_boundary_ingestion import activate_bahamas_boundary, activate_jamaica_boundary
from jurisdiction_boundary_registry import BoundaryRegistration, JurisdictionBoundaryRegistry
from jurisdiction_onboarding import plan_onboarding
from models import (AnomalyAssessment, HistoricalOccurrence, Jurisdiction, JurisdictionBoundary,
                    Region, ScientificDatasetApplicability, SpeciesJurisdictionStatus,
                    SpeciesProgram, SuitabilityDeployment, TrainingRun)
from phase12a3_migrate_boundary_onboarding import run_migration
from scientific_applicability_domain import EvidenceRole
from scientific_dataset_applicability import dataset_is_jurisdiction_compatible


@pytest.fixture()
def db():
    engine=create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    session=sessionmaker(bind=engine)()
    region=Region(name="Caribbean",slug="caribbean"); session.add(region); session.flush()
    session.add_all([
      Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="JM",jurisdiction_type="SOVEREIGN_STATE",center_latitude=18,center_longitude=-77,default_zoom=8),
      Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="BS",jurisdiction_type="SOVEREIGN_STATE",center_latitude=24,center_longitude=-76,default_zoom=6),
    ]); session.commit(); yield session; session.close(); engine.dispose()


def _request(jurisdiction_id, x=0, artifact=None):
    geometry={"type":"Polygon","coordinates":[[[x,0],[x+1,0],[x+1,1],[x,1],[x,0]]]}
    return BoundaryRegistration(jurisdiction_id,"MARINE_MONITORING","Provider","v1",f"id-{x}","reference","EPSG:4326",geometry,
      None if artifact is None else str(artifact), None if artifact is None else hashlib.sha256(artifact.read_bytes()).hexdigest(), {"retrieved":"controlled"}, ("Operational boundary only",))


def test_inventory_contract_and_duplicate_validation(tmp_path, db):
    payload={"inventory_version":"v1","parent_region_identifier":"caribbean","entries":[
      {"canonical_name":"Third","canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":"TT","jurisdiction_type":"SOVEREIGN_STATE","parent_region_identifier":"caribbean","operational_status":"PROPOSED","source_reference":"ISO","review_classification":"READY_FOR_ONBOARDING"},
      {"canonical_name":"Duplicate","canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":"TT","jurisdiction_type":"OVERSEAS_TERRITORY","sovereign_parent_identifier":"GB","parent_region_identifier":"caribbean","operational_status":"PROPOSED","source_reference":"ISO","review_classification":"READY_FOR_ONBOARDING"}]}
    path=tmp_path/"inventory.json"; path.write_text(json.dumps(payload),encoding="utf-8")
    errors=validate_inventory(CaribbeanJurisdictionInventory.load(path),region_identifier="caribbean",existing_jurisdictions=db.query(Jurisdiction).all())
    assert any("duplicate canonical identifier" in error for error in errors)


def test_generic_registration_provenance_and_lifecycle(db, tmp_path):
    artifact=tmp_path/"source.geojson"; artifact.write_text("source bytes",encoding="utf-8")
    jamaica=db.query(Jurisdiction).filter_by(slug="jamaica").one(); registry=JurisdictionBoundaryRegistry(db)
    first=registry.register_draft(_request(jamaica.id,0,artifact)); db.flush()
    assert first.status=="DRAFT" and first.source_artifact_sha256 != first.geometry_hash
    registry.activate(first); db.commit(); assert first.status=="ACTIVE" and first.activated_at
    second=registry.register_draft(_request(jamaica.id,2)); registry.activate(second); db.commit()
    assert first.status=="SUPERSEDED" and first.superseded_at
    assert second.predecessor_boundary_id==first.id
    assert db.query(JurisdictionBoundary).filter_by(jurisdiction_id=jamaica.id,status="ACTIVE").count()==1


def test_dry_run_reports_create_and_never_mutates(db, tmp_path):
    payload={"inventory_version":"v1","parent_region_identifier":"caribbean","entries":[{"canonical_name":"Third","canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":"TT","jurisdiction_type":"SOVEREIGN_STATE","parent_region_identifier":"caribbean","operational_status":"PROPOSED","source_reference":"ISO","review_classification":"READY_FOR_ONBOARDING"}]}
    path=tmp_path/"inventory.json"; path.write_text(json.dumps(payload),encoding="utf-8")
    before=db.query(Jurisdiction).count(); plan=plan_onboarding(db,path)
    assert plan[0].jurisdiction_action=="CREATE" and db.query(Jurisdiction).count()==before


@pytest.mark.parametrize("kind,parent",[("SOVEREIGN_STATE",None),("OVERSEAS_TERRITORY","GB"),("CONSTITUENT_COUNTRY","NL")])
def test_multiple_jurisdiction_types_remain_scientifically_unconfigured(db, kind, parent):
    region=db.query(Region).one(); row=Jurisdiction(region_id=region.id,name=f"Test {kind}",slug=f"test-{kind.lower()}",country_code="ZZ",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier=f"Z{len(kind)}",jurisdiction_type=kind,center_latitude=0,center_longitude=0,default_zoom=5)
    db.add(row); db.flush(); JurisdictionBoundaryRegistry(db).register_and_activate(_request(row.id)); db.commit()
    assert db.query(SpeciesProgram).filter_by(jurisdiction_id=row.id).count()==0
    assert db.query(SpeciesJurisdictionStatus).filter_by(jurisdiction_id=row.id).count()==0
    assert db.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=row.id).count()==0
    assert db.query(HistoricalOccurrence).count()==0 and db.query(SuitabilityDeployment).count()==0
    assert db.query(TrainingRun).count()==0 and db.query(AnomalyAssessment).count()==0


def test_region_dataset_firewall_without_applicability(db):
    region=db.query(Region).one(); third=Jurisdiction(region_id=region.id,name="Third",slug="third",country_code="TT",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="TT",jurisdiction_type="SOVEREIGN_STATE",center_latitude=0,center_longitude=0,default_zoom=5)
    db.add(third); db.flush()
    from models import ScientificDataset
    dataset=ScientificDataset(slug="regional",name="regional",dataset_type="ENVIRONMENTAL",geographic_scope_type="REGION",region_id=region.id,source_name="source")
    db.add(dataset); db.commit()
    assert not dataset_is_jurisdiction_compatible(db,dataset,third,EvidenceRole.ENVIRONMENTAL_COVARIATE)


def test_migration_idempotency_and_partial_unique_index():
    c=sqlite3.connect(":memory:"); c.executescript("CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY,jurisdiction_id INTEGER,boundary_type TEXT,source TEXT,source_version TEXT,source_reference TEXT,geometry_json TEXT,geometry_hash TEXT,status TEXT,created_at DATETIME,updated_at DATETIME); INSERT INTO jurisdiction_boundaries VALUES(1,1,'MARINE_MONITORING','Provider','v1','ref','{}','hash','ACTIVE','2020-01-01','2020-01-01');")
    first=run_migration(c); second=run_migration(c)
    assert first["columns_added"]==9 and second["columns_added"]==0
    assert c.execute("select status,geometry_hash,activated_at from jurisdiction_boundaries").fetchone()==("ACTIVE","hash","2020-01-01")
    with pytest.raises(sqlite3.IntegrityError): c.execute("INSERT INTO jurisdiction_boundaries(jurisdiction_id,boundary_type,status) VALUES(1,'MARINE_MONITORING','ACTIVE')")


def test_legacy_jamaica_wrapper_uses_generic_registry(db,tmp_path):
    feature = {
        "type": "Feature",
        "properties": {"mrgid": 8459, "iso_ter1": "JAM", "pol_type": "200NM"},
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[[[-78, 17], [-76, 17], [-76, 19], [-78, 19], [-78, 17]]]],
        },
    }
    path=tmp_path/"source.geojson"; path.write_text(json.dumps({"type":"FeatureCollection","features":[feature]}),encoding="utf-8")
    first,inserted,_=activate_jamaica_boundary(db,path); second,again,_=activate_jamaica_boundary(db,path)
    assert inserted and not again and first.id==second.id and first.provider_boundary_identifier=="8459"


def test_legacy_bahamas_wrapper_uses_generic_registry(db, tmp_path):
    feature = {
        "type": "Feature",
        "properties": {"mrgid": 8404, "iso_ter1": "BHS", "pol_type": "200NM", "territory2": None},
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[-79, 22], [-73, 22], [-73, 27], [-79, 27], [-79, 22]]]]},
    }
    payload = {"type": "FeatureCollection", "crs": {"properties": {"name": "EPSG:4326"}}, "features": [feature]}
    path = tmp_path / "bahamas.geojson"; path.write_text(json.dumps(payload), encoding="utf-8")
    first, inserted, _ = activate_bahamas_boundary(db, path)
    second, again, _ = activate_bahamas_boundary(db, path)
    assert inserted and not again and first.id == second.id
    assert first.provider_boundary_identifier == "8404"
