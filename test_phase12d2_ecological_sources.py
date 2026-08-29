import json, sqlite3
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from ecological_status_source_governance import EcologicalStatusSourceGovernanceService
from ecological_status_ingestion import EcologicalStatusIngestionService
from ecological_status_read_service import EcologicalStatusReadService
from phase12d2_migrate_ecological_sources import run_migration

@pytest.fixture()
def context(tmp_path):
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);s=sessionmaker(bind=engine)();admin=User(email="admin@d2.test",display_name="Admin",password_hash="x",is_platform_admin=True);region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");s.add_all([admin,region]);s.flush();jamaica=Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=7);bahamas=Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",status="ACTIVE",center_latitude=25,center_longitude=-77,default_zoom=7);taxon=Species(scientific_name="Pterois volitans",common_name="Red lionfish",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159559",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);s.add_all([jamaica,bahamas,taxon]);s.flush();s.add(RegionalTaxonRegistry(region_id=region.id,taxon_id=taxon.id,registry_version="v1",inclusion_basis="review",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="b"*64));s.commit();return s,admin,region,jamaica,bahamas,taxon,tmp_path

def source_payload(jurisdiction,version="2026",scope="JURISDICTION_SPECIFIC"):
 return {"source_registration_id":"agency-list","source_organization":"Agency","source_title":"Reviewed marine list","source_type":"GOVERNMENT_LIST","scope_type":scope,"jurisdiction_id":jurisdiction.id if scope=="JURISDICTION_SPECIFIC" else None,"region_id":jurisdiction.region_id if scope=="REGIONAL" else None,"source_version":version,"publication_date":"2026-01-01","source_reference":"https://agency.test/list","documentation_reference":"https://agency.test/docs","license":"CC-BY-4.0","reuse_terms":"Attribution required","acquisition_method":"CONTROLLED_UPLOAD","expected_semantics":{"authority_classification":"AUTHORITATIVE_FOR_JURISDICTION","evidence_type":"GOVERNMENT_OR_AGENCY_LIST"},"field_mapping":{"scientific_name":"scientific_name","source_status":"source_status","jurisdiction":"jurisdiction","source_record_identifier":"id"},"semantic_mapping":{"Invasive Alien Species":["INVASIVE"],"Introduced":["NON_NATIVE"],"Watch List":None},"provenance":{"publisher":"Agency"},"limitations":["Membership interpreted only through approved mapping."],"configuration_version":"v1"}

def active_source(s,admin,jurisdiction,**kwargs):
 service=EcologicalStatusSourceGovernanceService(s);row=service.register(source_payload(jurisdiction,**kwargs),admin.id);service.approve(row,admin.id,"reviewed-source-contract");return service.activate(row)

def csv_bytes(*rows):
 return ("id,scientific_name,source_status,jurisdiction\n"+"\n".join(",".join(row) for row in rows)+"\n").encode()

def test_source_lifecycle_fingerprint_and_versioning(context):
 s,admin,_,jamaica,_,_,_=context;service=EcologicalStatusSourceGovernanceService(s);row=service.register(source_payload(jamaica),admin.id);assert row.workflow_status=="READY_FOR_REVIEW";service.approve(row,admin.id,"review");service.activate(row);assert row.workflow_status=="ACTIVE"
 new=service.register(source_payload(jamaica,version="2027"),admin.id);service.approve(new,admin.id,"review-v2");service.activate(new);assert row.workflow_status=="SUPERSEDED" and new.workflow_status=="ACTIVE"
 changed=service.register(source_payload(jamaica,version="2028"),admin.id);changed.source_title="Changed after registration"
 with pytest.raises(ValueError,match="configuration changed"):service.approve(changed,admin.id,"invalid")

def test_parsing_preflight_scope_semantics_and_no_writes(context):
 s,admin,_,jamaica,_,_,tmp=context;source=active_source(s,admin,jamaica);service=EcologicalStatusIngestionService(s,tmp/"artifacts");data=csv_bytes(("1","Pterois volitans","Invasive Alien Species","Jamaica"),("2","Unknown fish","Invasive Alien Species","Jamaica"),("3","Pterois volitans","Watch List","Jamaica"));before=s.query(EcologicalStatusIngestionRun).count();result=service.preflight(source.id,jamaica.id,data,"list.csv","text/csv");assert result["write_performed"] is False and s.query(EcologicalStatusIngestionRun).count()==before;assert result["counts"]=={"READY":1,"TAXON_NOT_GOVERNED":1,"UNMAPPED_SOURCE_STATUS":1};assert result["artifact_sha256"]
 parsed=service.parse(json.dumps([{"scientific_name":"Pterois volitans","source_status":"Introduced"}]).encode(),"list.json","application/json");assert parsed["kind"]=="json"
 with pytest.raises(ValueError,match="Only CSV and JSON"):service.parse(b"x","x.exe","application/octet-stream")

def test_regional_and_global_sources_do_not_propagate(context):
 s,admin,_,jamaica,_,_,tmp=context
 for scope,expected in (("REGIONAL","REGIONAL_ONLY"),("GLOBAL","GLOBAL_ONLY")):
  source=active_source(s,admin,jamaica,scope=scope);result=EcologicalStatusIngestionService(s,tmp/scope).preflight(source.id,jamaica.id,csv_bytes(("1","Pterois volitans","Invasive Alien Species","")),"list.csv","text/csv");assert result["rows"][0]["jurisdiction_result"]==expected and result["rows"][0]["preflight_classification"]=="JURISDICTION_MISMATCH"

def test_durable_run_review_apply_idempotency_firewall_and_public_read(context):
 s,admin,_,jamaica,bahamas,taxon,tmp=context;source=active_source(s,admin,jamaica);service=EcologicalStatusIngestionService(s,tmp/"artifacts");data=csv_bytes(("1","Pterois volitans","Invasive Alien Species","Jamaica"),("2","Unknown fish","Invasive Alien Species","Jamaica"));before={model:s.query(model).count() for model in (HistoricalOccurrence,GovernedOccurrenceEvidence,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)};run=service.create_run(source.id,jamaica.id,data,"official.csv","text/csv",admin.id);again=service.create_run(source.id,jamaica.id,data,"official.csv","text/csv",admin.id);assert again["rerun_status"]=="NO-OP" and run["id"]==again["id"]
 ready,blocked=run["rows"];review=service.review(run["id"],[ready["id"],blocked["id"]],"APPROVED",admin.id,"row-review");assert [item["status"] for item in review["results"]]==["APPROVED","REFUSED"]
 applied=service.apply(run["id"],[ready["id"]]);assert applied["apply_status"]=="APPLIED" and service.apply(run["id"],[ready["id"]])["apply_status"]=="NO-OP";assert s.query(EcologicalStatusAssertion).count()==1 and [item.disposition for item in s.query(EcologicalStatusIngestionReview).order_by(EcologicalStatusIngestionReview.id)]==["APPROVED","APPLIED"];assert before=={model:s.query(model).count() for model in before};assert EcologicalStatusReadService(s).invasive_species(jamaica.id)[0]["taxon_id"]==taxon.id and EcologicalStatusReadService(s).invasive_species(bahamas.id)==[]

def test_conflict_legacy_nonpromotion_and_removed_item_non_inference(context):
 s,admin,_,jamaica,_,taxon,tmp=context;s.add(SpeciesJurisdictionStatus(species_id=taxon.id,jurisdiction_id=jamaica.id,ecological_status="INVASIVE",source="legacy-unverified"));s.commit();assert EcologicalStatusReadService(s).invasive_species(jamaica.id)==[]
 source=active_source(s,admin,jamaica);service=EcologicalStatusIngestionService(s,tmp/"artifacts");old=service.create_run(source.id,jamaica.id,csv_bytes(("1","Pterois volitans","Introduced","Jamaica")),"v1.csv","text/csv",admin.id);new=service.create_run(source.id,jamaica.id,csv_bytes(("2","Pterois volitans","Invasive Alien Species","Jamaica")),"v2.csv","text/csv",admin.id);comparison=service.version_comparison(source.id,new["id"]);assert comparison["removed_items"]==[] and "No eradication" in comparison["removed_item_interpretation"]

def test_migration_idempotency(tmp_path):
 path=tmp_path/"d.db";connection=sqlite3.connect(path);first=run_migration(connection);second=run_migration(connection);assert len(first["tables_created"])==4 and second["tables_created"]==[]

def test_admin_authorization_and_frontend_scientific_safety():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).get("/admin/ecological-status/sources").status_code==401
 text=Path("marine-monitoring-frontend/src/components/admin/EcologicalSourceIngestionPanel.jsx").read_text(encoding="utf-8");assert "Source claim" in text and "Platform governed status" in text and "does not change" in text
