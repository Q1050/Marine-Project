import hashlib
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from regional_taxonomy_bulk_service import RegionalTaxonomyBulkService
from taxonomy_provider import TaxonomyProvider,TaxonomyRecord

class FixtureProvider(TaxonomyProvider):
 def __init__(self,root):self.root=root
 def resolve_name(self,name):return name
 def fetch_taxon(self,identifier):return {}
 def fetch_classification(self,identifier):return {}
 def acquire(self,name):
  if name=="Pterois volitans/miles":raise ValueError("Ambiguous identity")
  if name=="Missing fish":raise ValueError("not found")
  if name=="Provider fail":raise RuntimeError("provider unavailable")
  values={"Pterois volitans":("159559","SPECIES","ACCEPTED","159559"),"Pterois miles":("159560","SPECIES","ACCEPTED","159560"),"Pterois":("204051","GENUS","ACCEPTED","204051"),"Gasterosteus volitans":("301175","SPECIES","SYNONYM","159559")}
  identifier,rank,status,accepted=values[name];path=self.root/(identifier+".json");path.write_text(name,encoding="utf-8");sha=hashlib.sha256(path.read_bytes()).hexdigest()
  return TaxonomyRecord("WoRMS","WORMS_APHIA_ID",identifier,name,"Pterois volitans" if status=="SYNONYM" else name,None,rank,status,accepted,None,None,(),"fixture-v1","url"),path,sha,sha

@pytest.fixture()
def db(tmp_path):
 e=create_engine("sqlite:///:memory:");Base.metadata.create_all(e);s=sessionmaker(bind=e)();r1=Region(name="Caribbean",slug="caribbean",status="ACTIVE");r2=Region(name="Pacific",slug="pacific",status="ACTIVE");s.add_all([r1,r2]);s.flush();admin=User(email="a@b.c",display_name="a",password_hash="x",is_platform_admin=True);p=Species(scientific_name="Pterois volitans",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159559",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);m=Species(scientific_name="Pterois miles");s.add_all([admin,p,m]);s.flush();s.add(RegionalTaxonRegistry(region_id=r1.id,taxon_id=p.id,registry_version="v1",inclusion_basis="review",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="b"*64));s.commit();yield s,tmp_path;s.close()

def test_dry_run_bulk_resolution_deduplication_and_failure_isolation(db):
 s,tmp=db;service=RegionalTaxonomyBulkService(s,FixtureProvider(tmp));before=s.query(TaxonomyPreparation).count()
 results=service.plan(1,[{"submitted_scientific_name":x} for x in ["Pterois volitans","Pterois miles","Pterois miles","Pterois volitans/miles","Pterois","Missing fish","Provider fail"]],True)
 assert [r["status"] for r in results]==["ALREADY_GOVERNED","CREATE_PREPARATION","CONFLICT","AMBIGUOUS","UNSUPPORTED_RANK","NOT_FOUND","PROVIDER_ERROR"]
 assert s.query(TaxonomyPreparation).count()==before

def test_authoritative_collision_and_submitted_id_conflict(db):
 s,tmp=db;service=RegionalTaxonomyBulkService(s,FixtureProvider(tmp));results=service.plan(2,[{"submitted_scientific_name":"Pterois miles"},{"submitted_scientific_name":"Pterois miles","submitted_identifier_scheme":"WORMS_APHIA_ID","submitted_identifier":"wrong"}],True)
 assert results[1]["status"] in {"CONFLICT"}

def test_prepare_approve_apply_generic_region_and_firewall(db):
 s,tmp=db;service=RegionalTaxonomyBulkService(s,FixtureProvider(tmp));models=(SpeciesProgram,SpeciesJurisdictionStatus,ScientificDatasetApplicability,HistoricalOccurrence,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal);before={m:s.query(m).count() for m in models}
 prepared=service.plan(2,[{"submitted_scientific_name":"Pterois miles","candidate_source":"CURATED_LIST","source_reference":"fixture"}],False,"test")[0];assert prepared["status"]=="READY_FOR_REVIEW"
 approved=service.approve_batch([prepared["preparation_id"]],1,"review");assert approved[0]["status"]=="APPROVED"
 applied=service.apply_batch([prepared["preparation_id"]]);assert applied[0]["status"]=="APPLIED";assert service.apply_batch([prepared["preparation_id"]])[0]["status"]=="NO-OP"
 assert s.query(RegionalTaxonRegistry).filter_by(region_id=2).count()==1 and before=={m:s.query(m).count() for m in models}

def test_new_synonym_identity_enters_local_candidate_workflow(db):
 s,tmp=db;result=RegionalTaxonomyBulkService(s,FixtureProvider(tmp)).plan(2,[{"submitted_scientific_name":"Gasterosteus volitans"}],True)[0]
 assert result["status"]=="CREATE_LOCAL_TAXON_CANDIDATE"

def test_admin_bulk_endpoint_requires_admin():
 from fastapi.testclient import TestClient
 from api import app
 response=TestClient(app).post("/admin/regions/1/taxonomy/prepare-bulk",json={"dry_run":True,"candidates":[]});assert response.status_code==401
