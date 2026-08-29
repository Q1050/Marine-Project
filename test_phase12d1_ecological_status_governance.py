import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from ecological_status_governance import EcologicalStatusGovernanceService
from ecological_status_read_service import EcologicalStatusReadService
from jurisdiction_taxon_readiness import JurisdictionTaxonReadinessService
from phase12d1_migrate_ecological_status import run_migration

@pytest.fixture()
def context():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);s=sessionmaker(bind=engine)();admin=User(email="admin@test",display_name="Admin",password_hash="x",is_platform_admin=True);region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");s.add_all([admin,region]);s.flush();jamaica=Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",status="ACTIVE",center_latitude=18.1,center_longitude=-77.3,default_zoom=7);bahamas=Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",status="ACTIVE",center_latitude=25,center_longitude=-77,default_zoom=7);barbados=Jurisdiction(region_id=region.id,name="Barbados",slug="barbados",country_code="BB",status="ACTIVE",center_latitude=13.1,center_longitude=-59.6,default_zoom=8);taxon=Species(scientific_name="Pterois volitans",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159559",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);s.add_all([jamaica,bahamas,barbados,taxon]);s.flush();s.add(RegionalTaxonRegistry(region_id=region.id,taxon_id=taxon.id,registry_version="v1",inclusion_basis="review",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="b"*64));s.commit();return s,admin,jamaica,bahamas,barbados,taxon

def payload(jurisdiction,taxon,statuses=("NON_NATIVE","ESTABLISHED"),authority="AUTHORITATIVE_FOR_JURISDICTION",title="Agency list"):
 return {"jurisdiction_id":jurisdiction.id,"source_organization":"Agency","source_title":title,"source_version":"2026","publication_date":"2026-01-01","source_reference":"https://agency.test/list","evidence_type":"GOVERNMENT_OR_AGENCY_LIST","authority_classification":authority,"geographic_scope":{"type":"JURISDICTION","jurisdiction_id":jurisdiction.id},"limitations":["Reviewed source assertion; not occurrence inference."],"assertions":[{"scientific_name":taxon.scientific_name,"authoritative_identifier_scheme":"WORMS_APHIA_ID","authoritative_identifier":"159559","statuses":list(statuses),"effective_from":"2026-01-01"}]}

def approve_apply(service,value,admin):
 prep=service.prepare(value,admin.id);service.approve(prep["id"],[prep["candidates"][0]["id"]],admin.id,"review");return service.apply(prep["id"])

def test_multi_status_explicit_apply_projection_firewall_and_isolation(context):
 s,admin,jamaica,bahamas,barbados,taxon=context;service=EcologicalStatusGovernanceService(s);before={m:s.query(m).count() for m in (SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal,GovernedOccurrenceEvidence)};result=approve_apply(service,payload(jamaica,taxon),admin);assert result["apply_status"]=="APPLIED" and service.apply(result["id"])["apply_status"]=="NO-OP"
 projection=service.projection(jamaica.id,taxon.id);assert projection["statuses"]==["ESTABLISHED","NON_NATIVE"] and projection["projection_state"]=="CURRENT_APPROVED";assert service.projection(bahamas.id,taxon.id)["statuses"]==[] and service.projection(barbados.id,taxon.id)["statuses"]==[]
 assert before=={m:s.query(m).count() for m in before};row=s.query(SpeciesJurisdictionStatus).one();assert json.loads(row.status_set_json)==["ESTABLISHED","NON_NATIVE"]
 assert EcologicalStatusReadService(s).invasive_species(jamaica.id)==[];assert JurisdictionTaxonReadinessService(s).evaluate(jamaica,taxon).as_dict()["dimensions"]["ecological_status"]["state"]=="READY"

def test_conflict_preserved_without_guessing(context):
 s,admin,jamaica,_,_,taxon=context;service=EcologicalStatusGovernanceService(s);approve_apply(service,payload(jamaica,taxon,("NATIVE",),title="Source A"),admin);approve_apply(service,payload(jamaica,taxon,("NON_NATIVE",),title="Source B"),admin);projection=service.projection(jamaica.id,taxon.id);assert projection["projection_state"]=="REVIEW_REQUIRED_CONFLICT" and projection["conflicts"]==[["NATIVE","NON_NATIVE"]];assert JurisdictionTaxonReadinessService(s).evaluate(jamaica,taxon).as_dict()["dimensions"]["ecological_status"]["state"]=="REVIEW_REQUIRED"

def test_authority_unknown_taxon_bulk_preflight_duplicates_and_dry_run(context):
 s,admin,jamaica,_,_,taxon=context;service=EcologicalStatusGovernanceService(s);value=payload(jamaica,taxon);value["assertions"].append({"scientific_name":"Unknown fish","statuses":["INVASIVE"]});before=s.query(EcologicalStatusPreparation).count();result=service.preflight(value);assert result["write_performed"] is False and s.query(EcologicalStatusPreparation).count()==before;assert [row["classification"] for row in result["rows"]]==["READY","TAXON_NOT_GOVERNED"] and result["rows"][1]["taxonomy_routing"]=="GOVERNED_TAXONOMY_CANDIDATE_WORKFLOW"
 supporting=payload(jamaica,taxon,authority="SUPPORTING");prep=service.prepare(supporting,admin.id)
 with pytest.raises(ValueError,match="not approved as authoritative"):service.approve(prep["id"],[prep["candidates"][0]["id"]],admin.id,"review")
 approve_apply(service,payload(jamaica,taxon),admin);assert service.preflight(payload(jamaica,taxon))["rows"][0]["classification"]=="DUPLICATE_ASSERTION"

def test_immutable_assertion_temporal_supersession_and_stale_refusal(context):
 s,admin,jamaica,_,_,taxon=context;service=EcologicalStatusGovernanceService(s);approve_apply(service,payload(jamaica,taxon,("PRESENT",),title="Old"),admin);old=s.query(EcologicalStatusAssertion).one();old.source_title="changed"
 with pytest.raises(ValueError,match="immutable"):s.commit()
 s.rollback();approve_apply(service,payload(jamaica,taxon,("ERADICATED",),title="New"),admin);new=s.query(EcologicalStatusAssertion).filter_by(asserted_status="ERADICATED").one();service.supersede(old.id,new.id);assert s.get(EcologicalStatusAssertion,old.id).lifecycle_state=="SUPERSEDED"
 prep=service.prepare(payload(jamaica,taxon,("TRANSIENT",),title="Stale"),admin.id);row=s.get(EcologicalStatusPreparation,prep["id"]);row.manifest_json='{"changed":true}';s.commit()
 with pytest.raises(ValueError,match="stale"):service.approve(row.id,[prep["candidates"][0]["id"]],admin.id,"review")

def test_occurrence_and_legacy_status_do_not_create_governed_projection(context):
 s,_,jamaica,_,_,taxon=context;s.add(SpeciesJurisdictionStatus(species_id=taxon.id,jurisdiction_id=jamaica.id,ecological_status="INVASIVE",source="legacy-unverified"));s.commit();assert EcologicalStatusGovernanceService(s).projection(jamaica.id,taxon.id)["statuses"]==[];assert EcologicalStatusReadService(s).invasive_species(jamaica.id)==[]

def test_migration_idempotent(tmp_path):
 path=tmp_path/"d.db";c=sqlite3.connect(path);c.executescript("CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY);CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE species_jurisdiction_status(id INTEGER PRIMARY KEY,species_id INTEGER,jurisdiction_id INTEGER,ecological_status TEXT,source TEXT);")
 first=run_migration(c);second=run_migration(c);assert len(first["tables_created"])==3 and len(first["projection_columns_added"])==4 and second=={"tables_created":[],"projection_columns_added":[]}

def test_admin_mutations_protected_and_frontend_separates_concepts():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).post("/admin/ecological-status/preflight",json={}).status_code==401
 text=Path("marine-monitoring-frontend/src/components/admin/EcologicalStatusPanel.jsx").read_text(encoding="utf-8");assert "Occurrence evidence" in text and "INVASIVE" in text and "numeric confidence" in text.lower()
