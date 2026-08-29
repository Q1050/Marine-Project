import shutil,sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base
from early_warning_service import EarlyWarningService
from milestone13c_migrate_early_warning import run_migration
from models import Jurisdiction,JurisdictionBoundary,Observation,Region,RegionalTaxonRegistry,Species

def db():
 e=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(e);return sessionmaker(bind=e)()
def seed():
 s=db();r=Region(name="Caribbean",slug="caribbean");s.add(r);s.flush();j=Jurisdiction(region_id=r.id,name="Fixture",slug="fixture",country_code="FX",center_latitude=1,center_longitude=1,default_zoom=7);s.add(j);s.flush();s.add(JurisdictionBoundary(jurisdiction_id=j.id,boundary_type="MARINE_MONITORING",geometry_json='{"type":"Polygon","coordinates":[]}',source="fixture",status="ACTIVE"));t=Species(scientific_name="Perna viridis",taxonomic_rank="SPECIES",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="140480",accepted_name_status="ACCEPTED");s.add(t);s.flush();s.add(RegionalTaxonRegistry(region_id=r.id,taxon_id=t.id,registry_version="v1",inclusion_basis="fixture",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="registry"));s.commit();return s,j,t
def observation(s,j,t,verified=True,duplicate=False):
 o=Observation(jurisdiction_id=j.id,image_filename="fixture.jpg",latitude=1,longitude=1,species=t.scientific_name,identification_status="accepted",verification_status="CONFIRMED" if verified else "PENDING",verified_species=t.scientific_name if verified else None,is_possible_duplicate=duplicate,decision="REVIEW",priority="NORMAL",reason="fixture");s.add(o);s.commit();return o
def test_verified_nonfish_without_local_baseline_is_conservatively_assessed():
 s,j,t=seed();o=observation(s,j,t);a=EarlyWarningService(s).evaluate(o.id);assert a.overall_status=="INSUFFICIENT_BASELINE";assert "does not mean first occurrence" in EarlyWarningService(s).payload(a)["explanation"].lower();assert len(a.signals)==5
def test_ai_only_and_duplicate_are_ineligible():
 s,j,t=seed();assert not EarlyWarningService(s).readiness(observation(s,j,t,False).id)["eligible"];assert not EarlyWarningService(s).readiness(observation(s,j,t,True,True).id)["eligible"]
def test_evaluation_is_idempotent_and_firewalled():
 s,j,t=seed();o=observation(s,j,t);service=EarlyWarningService(s);a=service.evaluate(o.id);b=service.evaluate(o.id);assert a.id==b.id;assert s.query(RegionalTaxonRegistry).count()==1
def test_migration_is_idempotent(tmp_path):
 path=tmp_path/"copy.db";shutil.copy2("marine_observations.db",path)
 with sqlite3.connect(path) as c:first=run_migration(c);second=run_migration(c);assert set(first)==set(second);assert not any(second.values());assert c.execute("select count(*) from anomaly_assessments").fetchone()[0]==0
