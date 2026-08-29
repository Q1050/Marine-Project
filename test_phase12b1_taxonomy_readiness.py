import json, sqlite3
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from database import Base
from jurisdiction_taxon_readiness import JurisdictionTaxonReadinessService
from models import (AnomalyAssessment, Jurisdiction, Region, RegionalTaxonRegistry,
                    ScientificDatasetApplicability, Species, SpeciesJurisdictionStatus,
                    SpeciesProgram, SuitabilityDeployment)
from phase12b1_migrate_taxonomy_registry import run_migration
from taxonomy_governance import provenance_fingerprint, regional_registry_payload, taxonomy_identity_payload

@pytest.fixture()
def db():
    engine=create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine); session=sessionmaker(bind=engine)()
    region=Region(name="Caribbean",slug="caribbean",status="ACTIVE"); session.add(region); session.flush()
    for name,code in (("Jamaica","JM"),("Bahamas","BS"),("Barbados","BB")):
        session.add(Jurisdiction(region_id=region.id,name=name,slug=name.lower(),country_code=code,canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier=code,jurisdiction_type="SOVEREIGN_STATE",status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=7))
    session.commit(); yield session; session.close()

def identity(name="Pterois volitans", identifier="126401"):
    return taxonomy_identity_payload(scientific_name=name,taxonomic_rank="SPECIES",identifier_scheme="WORMS_APHIA_ID",identifier=identifier,accepted_name_status="ACCEPTED",provenance={"provider":"WoRMS","reference":"reviewed fixture"},provenance_version="fixture-v1")

def add_taxon(db):
    payload=identity(); row=Species(scientific_name=payload["scientific_name"],common_name="Lionfish",aphia_id=126401,taxonomic_rank="SPECIES",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="126401",accepted_name_status="ACCEPTED",taxonomic_provenance_json=json.dumps(payload["provenance"],sort_keys=True,separators=(",",":")),provenance_version="fixture-v1",provenance_fingerprint=provenance_fingerprint(payload)); db.add(row); db.flush(); return row

def approve_region(db,taxon):
    region=db.query(Region).one(); payload=regional_registry_payload(region_id=region.id,taxon_id=taxon.id,registry_version="caribbean-v1",inclusion_basis="REVIEWED_EXISTING_PROGRAM",source_references=["fixture"],taxon_fingerprint=taxon.provenance_fingerprint)
    row=RegionalTaxonRegistry(region_id=region.id,taxon_id=taxon.id,registry_version="caribbean-v1",inclusion_basis="REVIEWED_EXISTING_PROGRAM",source_references_json='["fixture"]',review_status="APPROVED",approved_by="scientific-review",approved_at=datetime.now(timezone.utc),provenance_json=json.dumps(payload,sort_keys=True,separators=(",",":")),provenance_fingerprint=provenance_fingerprint(payload)); db.add(row); db.flush(); return row

def test_taxonomic_identity_and_registry_fingerprints_are_deterministic():
    first=identity(); second=identity()
    assert provenance_fingerprint(first)==provenance_fingerprint(second)
    a=regional_registry_payload(region_id=1,taxon_id=2,registry_version="v1",inclusion_basis="review",source_references=["b","a"],taxon_fingerprint="x")
    b=regional_registry_payload(region_id=1,taxon_id=2,registry_version="v1",inclusion_basis="review",source_references=["a","b"],taxon_fingerprint="x")
    assert provenance_fingerprint(a)==provenance_fingerprint(b)
    assert provenance_fingerprint({**a,"created_at":"yesterday"})==provenance_fingerprint({**a,"created_at":"today"})

def test_authoritative_identifier_is_unique(db):
    add_taxon(db); db.commit()
    db.add(Species(scientific_name="Different name",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="126401"))
    with pytest.raises(IntegrityError): db.commit()

def test_synonym_and_conflict_are_explicit_and_species_complex_is_refused(db):
    accepted=add_taxon(db); db.flush()
    synonym=Species(scientific_name="Reviewed synonym",taxonomic_rank="SPECIES",authoritative_identifier_scheme="GBIF_TAXON_KEY",authoritative_identifier="42",accepted_name_status="SYNONYM",accepted_taxon_id=accepted.id)
    conflict=Species(scientific_name="Pterois complex",taxonomic_rank="GENUS",authoritative_identifier_scheme="LOCAL_REVIEW",authoritative_identifier="complex-1",accepted_name_status="CONFLICT")
    db.add_all([synonym,conflict]); db.commit(); assert synonym.accepted_taxon_id==accepted.id and conflict.accepted_name_status=="CONFLICT"
    with pytest.raises(ValueError,match="Ambiguous species complexes"):
        identity("Pterois volitans/miles","complex")

def test_regional_approval_is_not_jurisdiction_science(db):
    taxon=add_taxon(db); approve_region(db,taxon); db.commit()
    assert db.query(SpeciesProgram).count()==0
    assert db.query(SpeciesJurisdictionStatus).count()==0
    assert db.query(ScientificDatasetApplicability).count()==0
    assert db.query(SuitabilityDeployment).count()==0
    assert db.query(AnomalyAssessment).count()==0

def test_bahamas_and_barbados_firewall_and_dimensional_readiness(db):
    taxon=add_taxon(db); approve_region(db,taxon); db.commit(); service=JurisdictionTaxonReadinessService(db)
    for name in ("Bahamas","Barbados"):
        result=service.evaluate(db.query(Jurisdiction).filter_by(name=name).one(),taxon).as_dict()
        assert result["dimensions"]["taxonomy"]["state"]=="READY"
        assert result["dimensions"]["regional_governance"]["state"]=="READY"
        assert result["dimensions"]["occurrence_evidence"]["state"]=="BLOCKED"
        assert result["dimensions"]["ecological_status"]["state"]=="BLOCKED"
        assert result["dimensions"]["species_program"]["state"]=="BLOCKED"
        assert result["dimensions"]["anomaly_prerequisites"]["state"]=="BLOCKED"
        assert "score" not in json.dumps(result).lower() and "percent" not in json.dumps(result).lower()

def test_existing_jamaica_species_id_and_program_are_unchanged(db):
    legacy=Species(scientific_name="Pterois volitans",common_name="Lionfish",aphia_id=126401); db.add(legacy); db.flush()
    jamaica=db.query(Jurisdiction).filter_by(name="Jamaica").one(); program=SpeciesProgram(jurisdiction_id=jamaica.id,species_id=legacy.id,scientific_name=legacy.scientific_name,status="ACTIVE"); db.add(program); db.commit()
    before=(legacy.id,program.id,db.query(SpeciesProgram).count()); result=JurisdictionTaxonReadinessService(db).evaluate(jamaica,legacy)
    assert result.as_dict()["dimensions"]["taxonomy"]["state"]=="READY"
    assert before==(legacy.id,program.id,db.query(SpeciesProgram).count())

def test_migration_is_idempotent(tmp_path):
    connection=sqlite3.connect(tmp_path/"taxonomy.db"); connection.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY); CREATE TABLE species(id INTEGER PRIMARY KEY,scientific_name TEXT);")
    first=run_migration(connection); second=run_migration(connection)
    assert len(first["species_columns_added"])==10 and second["species_columns_added"]==[]
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='regional_taxon_registry'").fetchone()

def test_admin_taxonomy_endpoint_is_protected_and_read_only():
    import inspect
    from fastapi.testclient import TestClient
    from api import app, admin_region_taxa, admin_taxon_detail, admin_jurisdiction_taxon_readiness, admin_jurisdiction_scientific_readiness
    assert TestClient(app).get("/admin/regions/1/taxa").status_code==401
    source="\n".join(inspect.getsource(function) for function in (admin_region_taxa,admin_taxon_detail,admin_jurisdiction_taxon_readiness,admin_jurisdiction_scientific_readiness))
    assert "@app.post" not in source and "db.commit()" not in source and "db.add(" not in source
