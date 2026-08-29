import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from ecological_status_read_service import EcologicalStatusReadService
from public_media_service import PublicMediaService
from phase12e3_migrate_display_governance import run_migration

def test_display_governance_and_batched_primary_media():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);s=sessionmaker(bind=engine)();region=Region(name="R",slug="r",status="ACTIVE");user=User(email="a@b.c",display_name="A",password_hash="x",is_platform_admin=True);s.add_all([region,user]);s.flush();j=Jurisdiction(region_id=region.id,name="J",slug="j",country_code="JJ",status="ACTIVE",center_latitude=0,center_longitude=0,default_zoom=5);taxon=Species(scientific_name="Alga example",common_name="Alga",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="f"*64);s.add_all([j,taxon]);s.flush();program=SpeciesProgram(jurisdiction_id=j.id,species_id=taxon.id,scientific_name=taxon.scientific_name,status="ACTIVE");model=HabitatSuitabilityModel(model_version="m",scientific_name=taxon.scientific_name,algorithm="x",feature_list_json="[]",training_generation_version="v",training_sample_count=1,eligible_presence_count=1,eligible_background_count=0,spatial_block_count=1,validation_metrics_json="{}",coefficients_json="{}",artifact_path="x");s.add_all([program,model]);s.flush();deployment=SuitabilityDeployment(species_program_id=program.id,habitat_suitability_model_id=model.id,model_version="m",status="ACTIVE");s.add(deployment);s.commit();assert deployment.public_display_status=="NOT_APPROVED";before=(deployment.status,model.model_version);deployment.public_display_status="PUBLIC_APPROVED";deployment.public_display_approval_reference="review";deployment.public_display_approved_by_user_id=user.id;s.commit();assert (deployment.status,model.model_version)==before;deployment.public_display_status="REVOKED";s.commit();assert deployment.status=="ACTIVE"
 service=PublicMediaService(s);media=service.create({"media_type":"TAXON_REFERENCE_IMAGE","taxon_id":taxon.id,"source_provider":"Museum","source_reference":"https://source","license":"CC-BY","attribution_text":"Museum","remote_url":"https://image.test/a.jpg","provenance_json":"{}","limitations_json":"[]"});service.review(media,user.id,"APPROVED");service.publish(media,True)
 # Directory media is obtained by one batched query and never includes unpublished rows.
 assert service.public_for_taxon(taxon.id)==[media]

def test_migration_defaults_existing_deployments_to_not_approved(tmp_path):
 path=tmp_path/"x.db";c=sqlite3.connect(path);c.execute("CREATE TABLE suitability_deployments(id INTEGER PRIMARY KEY)");first=run_migration(c);second=run_migration(c);assert len(first["columns_added"])==6 and second["columns_added"]==[];c.execute("INSERT INTO suitability_deployments(id) VALUES(1)");assert c.execute("SELECT public_display_status FROM suitability_deployments").fetchone()[0]=="NOT_APPROVED"

def test_frontend_closure_contract():
 directory=Path("marine-monitoring-frontend/src/pages/PublicDirectoryPages.jsx").read_text(encoding="utf-8");submit=Path("marine-monitoring-frontend/src/pages/SubmitPage.jsx").read_text(encoding="utf-8");admin=Path("marine-monitoring-frontend/src/components/admin/PublicMediaPanel.jsx").read_text(encoding="utf-8");assert "No approved public image" in directory and "attribution_text" in directory;assert "Reporting in:" in submit and "Suggested species:" in submit and "searchParams.get(\"name\")" not in submit;assert "Registration does not publish media" in admin
