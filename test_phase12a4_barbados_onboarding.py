import shutil, sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import barbados_onboarding
from barbados_onboarding import apply_barbados, load_boundary_artifact, load_reviewed_manifest, plan_barbados
from models import (HistoricalOccurrence, Jurisdiction, JurisdictionBoundary, ScientificDataset,
                    ScientificDatasetApplicability, SpeciesJurisdictionStatus, SpeciesProgram,
                    SuitabilityDeployment, TrainingRun)
from phase12a2_migrate_jurisdiction_applicability import run_migration as migrate_12a2
from phase12a3_migrate_boundary_onboarding import run_migration as migrate_12a3
from phase12a5_migrate_onboarding_governance import run_migration as migrate_12a5
from phase12e3_migrate_display_governance import run_migration as migrate_12e3
from phase12d1_migrate_ecological_status import run_migration as migrate_12d1
from scientific_applicability_domain import EvidenceRole
from scientific_dataset_applicability import dataset_is_jurisdiction_compatible

MANIFEST="artifacts/onboarding/barbados-onboarding-manifest-v1.json"


def _copy_session(tmp_path):
    backups=sorted(Path("backups").glob("marine_observations_pre_phase12a4_*.db"))
    source=backups[-1] if backups else Path("marine_observations.db")
    path=tmp_path/"copy.db"; shutil.copy2(source,path)
    connection=sqlite3.connect(path); first=(migrate_12a2(connection),migrate_12a3(connection),migrate_12a5(connection),migrate_12d1(connection),migrate_12e3(connection)); second=(migrate_12a2(connection),migrate_12a3(connection),migrate_12a5(connection),migrate_12d1(connection),migrate_12e3(connection)); connection.close()
    engine=create_engine(f"sqlite:///{path}"); return sessionmaker(bind=engine)(),engine,first,second


def test_barbados_identity_boundary_and_manifest_are_exact():
    manifest=load_reviewed_manifest(MANIFEST); artifact,feature=load_boundary_artifact(manifest["boundary_artifact_reference"])
    assert manifest["jurisdiction"]=={"canonical_name":"Barbados","canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":"BB","jurisdiction_type":"SOVEREIGN_STATE"}
    assert feature["properties"]["mrgid"]==8418 and artifact["geometry_valid"] is True
    assert artifact["source_artifact_sha256"] != artifact["geometry_sha256"]


def test_migration_chain_apply_firewalls_and_repeat_noop(tmp_path):
    db,engine,first,second=_copy_session(tmp_path)
    before={"jamaica":db.query(Jurisdiction).filter_by(slug="jamaica").one().id,"bahamas":db.query(Jurisdiction).filter_by(slug="bahamas").one().id,
            "hashes":[x.geometry_hash for x in db.query(JurisdictionBoundary).order_by(JurisdictionBoundary.id)],
            "historical":db.query(HistoricalOccurrence).count(),"deployments":db.query(SuitabilityDeployment).count(),"runs":db.query(TrainingRun).count()}
    assert plan_barbados(db,MANIFEST)["jurisdiction_action"]=="CREATE"
    result=apply_barbados(db,MANIFEST); db.commit(); barbados=db.get(Jurisdiction,result["jurisdiction_id"])
    assert (barbados.name,barbados.canonical_identifier,barbados.jurisdiction_type)==("Barbados","BB","SOVEREIGN_STATE")
    assert db.query(JurisdictionBoundary).filter_by(jurisdiction_id=barbados.id,status="ACTIVE",boundary_type="MARINE_MONITORING").count()==1
    for model in (SpeciesProgram,SpeciesJurisdictionStatus,ScientificDatasetApplicability): assert db.query(model).filter_by(jurisdiction_id=barbados.id).count()==0
    regional=db.query(ScientificDataset).filter_by(geographic_scope_type="REGION").one()
    assert not dataset_is_jurisdiction_compatible(db,regional,barbados,EvidenceRole.ENVIRONMENTAL_COVARIATE)
    assert not dataset_is_jurisdiction_compatible(db,regional,barbados,EvidenceRole.GEOGRAPHIC_EVIDENCE)
    assert apply_barbados(db,MANIFEST)["boundary_action"]=="NO-OP"; db.commit()
    assert db.query(Jurisdiction).count()==3 and db.query(JurisdictionBoundary).count()==3
    assert db.query(Jurisdiction).filter_by(slug="jamaica").one().id==before["jamaica"] and db.query(Jurisdiction).filter_by(slug="bahamas").one().id==before["bahamas"]
    assert [x.geometry_hash for x in db.query(JurisdictionBoundary).filter(JurisdictionBoundary.id.in_([1,2])).order_by(JurisdictionBoundary.id)]==before["hashes"]
    assert (db.query(HistoricalOccurrence).count(),db.query(SuitabilityDeployment).count(),db.query(TrainingRun).count())==(before["historical"],before["deployments"],before["runs"])
    assert second[0]["identity_columns_added"]==0 and second[1]["columns_added"]==0
    db.close(); engine.dispose()


def test_apply_failure_rolls_back_entire_jurisdiction(tmp_path,monkeypatch):
    db,engine,_,_=_copy_session(tmp_path)
    def fail(*args,**kwargs): raise RuntimeError("controlled failure")
    monkeypatch.setattr(barbados_onboarding.JurisdictionBoundaryRegistry,"register_and_activate",fail)
    with pytest.raises(RuntimeError): apply_barbados(db,MANIFEST)
    db.rollback()
    assert db.query(Jurisdiction).filter_by(canonical_identifier="BB").count()==0
    db.close(); engine.dispose()


def test_future_boundary_replacement_preserves_lifecycle(tmp_path):
    db,engine,_,_=_copy_session(tmp_path); result=apply_barbados(db,MANIFEST); db.commit()
    old=db.query(JurisdictionBoundary).filter_by(jurisdiction_id=result["jurisdiction_id"],status="ACTIVE").one()
    from jurisdiction_boundary_registry import BoundaryRegistration,JurisdictionBoundaryRegistry
    geometry={"type":"Polygon","coordinates":[[[-60,11],[-56,11],[-56,16],[-60,16],[-60,11]]]}
    new=JurisdictionBoundaryRegistry(db).register_draft(BoundaryRegistration(result["jurisdiction_id"],"MARINE_MONITORING","Test replacement","v2","replacement","test","EPSG:4326",geometry))
    JurisdictionBoundaryRegistry(db).activate(new); db.commit()
    assert old.status=="SUPERSEDED" and old.superseded_at and new.status=="ACTIVE" and new.predecessor_boundary_id==old.id
    assert db.query(JurisdictionBoundary).filter_by(jurisdiction_id=result["jurisdiction_id"],status="ACTIVE").count()==1
    db.close(); engine.dispose()
