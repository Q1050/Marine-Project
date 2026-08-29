import hashlib,json,sqlite3
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from phase12b2_migrate_taxonomy_workflow import run_migration
from taxonomy_provider import TaxonomyProvider,TaxonomyRecord,WoRMSTaxonomyProvider
from taxonomy_preparation_service import TaxonomyPreparationService,reconciliation

@pytest.fixture()
def db(tmp_path):
 e=create_engine("sqlite:///:memory:"); Base.metadata.create_all(e); s=sessionmaker(bind=e)(); r=Region(name="Caribbean",slug="caribbean",status="ACTIVE"); s.add(r); s.flush()
 for name,code in (("Jamaica","JM"),("Bahamas","BS"),("Barbados","BB")): s.add(Jurisdiction(region_id=r.id,name=name,slug=name.lower(),country_code=code,status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=7))
 user=User(email="a@b.c",display_name="Admin",password_hash="x",is_platform_admin=True); taxon=Species(scientific_name="Pterois volitans",common_name="Lionfish"); s.add_all([user,taxon]); s.flush()
 s.add(HistoricalOccurrence(scientific_name=taxon.scientific_name,taxon_id=159559,latitude=18,longitude=-77,source="OBIS",deduplication_key="one")); s.commit(); yield s,tmp_path; s.close()

class FakeProvider(TaxonomyProvider):
 def __init__(self,path): self.path=path
 def resolve_name(self,name): return "159559"
 def fetch_taxon(self,identifier): return {}
 def fetch_classification(self,identifier): return {}
 def acquire(self,name):
  record=TaxonomyRecord("World Register of Marine Species (WoRMS)","WORMS_APHIA_ID","159559","Pterois volitans","Pterois volitans","(Linnaeus, 1758)","SPECIES","ACCEPTED","159559","154410","Pterois",({"aphia_id":"159559","rank":"Species","scientific_name":"Pterois volitans"},),"live-rest-v1","https://www.marinespecies.org/aphia.php?p=taxdetails&id=159559")
  self.path.write_text('{"provider":"WoRMS"}',encoding="utf-8"); sha=hashlib.sha256(self.path.read_bytes()).hexdigest(); return record,self.path,sha,"content"

def test_provider_interface_and_worms_parsing(monkeypatch,tmp_path):
 assert issubclass(WoRMSTaxonomyProvider,TaxonomyProvider)
 provider=WoRMSTaxonomyProvider(); responses=[[{"AphiaID":159559,"scientificname":"Pterois volitans"}],{"AphiaID":159559,"scientificname":"Pterois volitans","valid_AphiaID":159559,"valid_name":"Pterois volitans","authority":"(Linnaeus, 1758)","rank":"Species","status":"accepted","parentNameUsageID":154410,"parentNameUsage":"Pterois"},{"AphiaID":1,"rank":"Kingdom","scientificname":"Animalia","child":{"AphiaID":159559,"rank":"Species","scientificname":"Pterois volitans","child":None}}]
 monkeypatch.setattr(provider,"_get",lambda path:responses.pop(0)); monkeypatch.chdir(tmp_path)
 record,path,sha,_=provider.acquire("Pterois volitans"); assert record.identifier=="159559" and record.rank=="SPECIES" and record.parent_identifier=="154410" and path.exists() and sha==hashlib.sha256(path.read_bytes()).hexdigest()

def test_ambiguous_name_refused_before_lookup():
 with pytest.raises(ValueError,match="Ambiguous"): WoRMSTaxonomyProvider().resolve_name("Pterois volitans/miles")

def test_prepare_approve_apply_idempotent_and_firewall(db):
 s,tmp=db; service=TaxonomyPreparationService(s,FakeProvider(tmp/"raw.json")); taxon=s.query(Species).one(); region=s.query(Region).one()
 before={m:s.query(m).count() for m in (SpeciesProgram,SpeciesJurisdictionStatus,ScientificDatasetApplicability,HistoricalOccurrence,SuitabilityDeployment,AnomalyAssessment)}
 row=service.prepare(taxon_id=taxon.id,region_id=region.id,prepared_by="test"); s.commit(); assert row.reconciliation_result=="MATCH" and row.workflow_status=="READY_FOR_REVIEW"
 assert service.prepare(taxon_id=taxon.id,region_id=region.id,prepared_by="test").id==row.id
 service.approve(row,user_id=1,approval_reference="review",expected_fingerprint=row.preparation_fingerprint); s.commit(); result=service.apply(row)
 assert result["status"]=="APPLIED" and service.apply(row)["status"]=="NO-OP"; s.refresh(taxon); assert taxon.id==1 and taxon.aphia_id==159559 and taxon.authoritative_identifier=="159559"
 assert s.query(RegionalTaxonRegistry).count()==1 and s.query(RegionalTaxonRegistry).one().review_status=="APPROVED"
 assert before=={m:s.query(m).count() for m in before}

def test_stale_approval_refused(db):
 s,tmp=db; service=TaxonomyPreparationService(s,FakeProvider(tmp/"raw.json")); row=service.prepare(taxon_id=1,region_id=1,prepared_by="test"); s.commit(); service.approve(row,user_id=1,approval_reference="r",expected_fingerprint=row.preparation_fingerprint); s.commit(); row.proposed_rank="GENUS"
 with pytest.raises(ValueError,match="stale"): service.apply(row)

def test_conflict_and_synonym_reconciliation(db):
 s,_=db; taxon=s.query(Species).one(); accepted=TaxonomyRecord("WoRMS","WORMS_APHIA_ID","159559","Pterois volitans","Pterois volitans",None,"SPECIES","ACCEPTED","159559",None,None,(),"v","url")
 assert reconciliation(accepted,taxon,{159559})[0]=="MATCH"
 conflict=TaxonomyRecord("WoRMS","WORMS_APHIA_ID","999","Other fish","Other fish",None,"SPECIES","ACCEPTED","999",None,None,(),"v","url")
 assert reconciliation(conflict,taxon,{159559})[0]=="CONFLICT"
 synonym=TaxonomyRecord("WoRMS","WORMS_APHIA_ID","301175","Gasterosteus volitans","Pterois volitans",None,"SPECIES","SYNONYM","159559",None,None,(),"v","url")
 assert synonym.accepted_identifier=="159559" and synonym.identifier!="159559"

def test_migration_idempotent(tmp_path):
 c=sqlite3.connect(tmp_path/"m.db"); c.executescript("CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE regions(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE regional_taxon_registry(id INTEGER PRIMARY KEY);")
 assert run_migration(c)["table_created"] and not run_migration(c)["table_created"]

def test_admin_authorization():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).post("/admin/taxonomy/prepare",json={"taxon_id":1,"region_id":1}).status_code==401
