import json,sqlite3
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from jurisdiction_governance import create_artifact_reference,create_onboarding_record,set_sovereign_parent
from marine_regions_acquisition import acquire_marine_regions_boundary
from models import ArtifactReference,Jurisdiction,JurisdictionBoundary,JurisdictionOnboardingRecord,Region
from onboarding_batch import apply_manifest_batch,plan_manifests
from phase12a5_migrate_onboarding_governance import run_migration

ANTIGUA="artifacts/onboarding/antigua-and-barbuda-onboarding-manifest-v1.json"
SAINT_LUCIA="artifacts/onboarding/saint-lucia-onboarding-manifest-v1.json"

@pytest.fixture()
def db():
 e=create_engine("sqlite:///:memory:"); Base.metadata.create_all(e); s=sessionmaker(bind=e)(); r=Region(name="Caribbean",slug="caribbean"); s.add(r); s.flush(); yield s; s.close(); e.dispose()

def test_artifact_reference_supports_external_hash_only(db):
 row=create_artifact_reference(db,external_uri="s3://future/boundary.geojson",local_path=None,sha256="a"*64,media_type="application/geo+json",artifact_type="JURISDICTION_BOUNDARY_SOURCE",size_bytes=123,provider="Provider",source_reference="reference",availability_status="EXTERNAL_ONLY")
 db.commit(); assert row.external_uri and row.local_path is None
 row.provider="changed"
 with pytest.raises(ValueError): db.commit()

def test_onboarding_record_is_immutable_and_fingerprint_persists(db):
 region=db.query(Region).one(); j=Jurisdiction(region_id=region.id,name="Test",slug="test",country_code="TT",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="TT",jurisdiction_type="SOVEREIGN_STATE",center_latitude=0,center_longitude=0,default_zoom=5); db.add(j); db.flush()
 b=JurisdictionBoundary(jurisdiction_id=j.id,boundary_type="MARINE_MONITORING",geometry_json="{}",source="p",geometry_hash="b"*64,source_artifact_sha256="a"*64,status="ACTIVE"); db.add(b); db.flush()
 a=create_artifact_reference(db,local_path="x",external_uri=None,sha256="a"*64,media_type="x",artifact_type="BOUNDARY",size_bytes=1,provider="p",source_reference="r",availability_status="AVAILABLE")
 manifest={"manifest_version":"v1","manifest_fingerprint":"f"*64,"jurisdiction":{"canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":"TT"},"approval_state":"APPROVED"}
 row=create_onboarding_record(db,jurisdiction=j,boundary=b,artifact_reference=a,manifest=manifest,action_performed="CREATE",execution_mode="APPLY",before_state={},after_state={}); db.commit(); assert row.manifest_fingerprint=="f"*64
 row.action_performed="UPDATE"
 with pytest.raises(ValueError): db.commit()

def test_sovereign_parent_rules_and_cycle_refusal(db):
 region=db.query(Region).one(); sovereign=Jurisdiction(region_id=region.id,name="S",slug="s",country_code="SS",jurisdiction_type="SOVEREIGN_STATE",center_latitude=0,center_longitude=0,default_zoom=1); territory=Jurisdiction(region_id=region.id,name="T",slug="t",country_code="TT",jurisdiction_type="OVERSEAS_TERRITORY",center_latitude=0,center_longitude=0,default_zoom=1); db.add_all([sovereign,territory]); db.flush()
 set_sovereign_parent(db,territory,sovereign); assert territory.sovereign_parent_id==sovereign.id
 with pytest.raises(ValueError): set_sovereign_parent(db,sovereign,territory)
 with pytest.raises(ValueError): set_sovereign_parent(db,territory,None)

class Response:
 def __init__(self,data): self.data=data
 def __enter__(self): return self
 def __exit__(self,*args): pass
 def read(self): return self.data

def _payload(iso="ATG"):
 return json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"mrgid":8414,"iso_ter1":iso,"pol_type":"200NM","territory2":None},"geometry":{"type":"Polygon","coordinates":[[[-62,17],[-58,17],[-58,20],[-62,20],[-62,17]]]}}]}).encode()

def test_generic_acquisition_and_identity_mismatch(monkeypatch,tmp_path):
 monkeypatch.setattr("urllib.request.urlopen",lambda *_args,**_kwargs:Response(_payload()))
 artifact,raw,value=acquire_marine_regions_boundary(canonical_name="Antigua and Barbuda",canonical_identifier="AG",expected_provider_iso="ATG",mrgid=8414,output_directory=tmp_path/"a",raw_directory=tmp_path/"r")
 assert artifact.exists() and raw.exists() and value["source_artifact_sha256"]!=value["geometry_sha256"]
 monkeypatch.setattr("urllib.request.urlopen",lambda *_args,**_kwargs:Response(_payload("WRONG")))
 with pytest.raises(ValueError): acquire_marine_regions_boundary(canonical_name="Antigua and Barbuda",canonical_identifier="AG",expected_provider_iso="ATG",mrgid=8414,output_directory=tmp_path/"b",raw_directory=tmp_path/"s")

def test_two_candidate_manifests_and_batch_planning(db):
 plans=plan_manifests(db,[ANTIGUA,SAINT_LUCIA]); assert [(p.canonical_identifier,p.jurisdiction_action,p.boundary_action,p.status) for p in plans]==[("AG","CREATE","CREATE","READY"),("LC","CREATE","CREATE","READY")]
 duplicate=plan_manifests(db,[ANTIGUA,ANTIGUA]); assert any(p.status=="CONFLICT" for p in duplicate)
 with pytest.raises(RuntimeError): apply_manifest_batch(db,[ANTIGUA,SAINT_LUCIA])

def test_migration_idempotency_and_barbados_backfill():
 c=sqlite3.connect(":memory:"); c.executescript("""CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY,canonical_identifier TEXT); CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY,jurisdiction_id INTEGER,status TEXT,activated_at DATETIME); INSERT INTO jurisdictions VALUES(3,'BB'); INSERT INTO jurisdiction_boundaries VALUES(3,3,'ACTIVE','2026-01-01');""")
 first=run_migration(c); second=run_migration(c); assert first["barbados_record_backfilled"]==1 and second["barbados_record_backfilled"]==0
 assert c.execute("select manifest_fingerprint from jurisdiction_onboarding_records").fetchone()[0]=="f536e77d272204bf9e7175817c9207ecd96f4813b0ee56cc8fa30e64f36ba14a"
