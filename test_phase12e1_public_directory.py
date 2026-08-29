from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from models import *
from api import app
from ecological_status_governance import EcologicalStatusGovernanceService

@pytest.fixture()
def public_context():
 engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(engine);Session=sessionmaker(bind=engine);s=Session();region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");s.add(region);s.flush();jamaica=Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="JM",jurisdiction_type="SOVEREIGN_STATE",status="ACTIVE",center_latitude=18.1,center_longitude=-77.3,default_zoom=7);bahamas=Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",status="ACTIVE",center_latitude=25,center_longitude=-77,default_zoom=7);barbados=Jurisdiction(region_id=region.id,name="Barbados",slug="barbados",country_code="BB",status="ACTIVE",center_latitude=13.1,center_longitude=-59.6,default_zoom=8);admin=User(email="admin@e.test",display_name="Admin",password_hash="x",is_platform_admin=True);lionfish=Species(scientific_name="Pterois volitans",common_name="Red lionfish",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);alga=Species(scientific_name="Halophila stipulacea",common_name="Halophila seagrass",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="b"*64);s.add_all([jamaica,bahamas,barbados,admin,lionfish,alga]);s.flush();s.add(JurisdictionBoundary(jurisdiction_id=jamaica.id,boundary_type="MARINE_MONITORING",geometry_json='{"type":"Polygon","coordinates":[]}',source="Public boundary source",status="ACTIVE"));s.add(SpeciesJurisdictionStatus(species_id=lionfish.id,jurisdiction_id=jamaica.id,ecological_status="INVASIVE",source="legacy-unverified"));s.commit()
 def override():
  db=Session()
  try:yield db
  finally:db.close()
 app.dependency_overrides[get_db]=override;client=TestClient(app);yield s,client,region,jamaica,bahamas,barbados,admin,lionfish,alga;app.dependency_overrides.clear();s.close()

def approve_alga(s,admin,jamaica,alga):
 s.add(RegionalTaxonRegistry(region_id=jamaica.region_id,taxon_id=alga.id,registry_version="v1",inclusion_basis="review",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="d"*64));s.commit()
 value={"jurisdiction_id":jamaica.id,"source_organization":"Marine Agency","source_title":"Reviewed ecological list","source_reference":"https://agency.test/list","evidence_type":"GOVERNMENT_OR_AGENCY_LIST","authority_classification":"AUTHORITATIVE_FOR_JURISDICTION","geographic_scope":{"type":"JURISDICTION","jurisdiction_id":jamaica.id},"limitations":[],"assertions":[{"scientific_name":alga.scientific_name,"statuses":["NON_NATIVE"]}]};service=EcologicalStatusGovernanceService(s);prepared=service.prepare(value,admin.id);service.approve(prepared["id"],[prepared["candidates"][0]["id"]],admin.id,"review");service.apply(prepared["id"])

def test_public_regions_and_scientifically_empty_jurisdictions(public_context):
 _,client,region,jamaica,bahamas,barbados,*_=public_context;listing=client.get("/regions").json();assert listing["regions"][0]["jurisdiction_count"]==3;detail=client.get(f"/regions/{region.slug}").json();assert {row["name"] for row in detail["jurisdictions"]}=={"Jamaica","Bahamas","Barbados"};assert next(row for row in detail["jurisdictions"] if row["id"]==jamaica.id)["geographic_configuration_state"]=="CONFIGURED";assert client.get(f"/jurisdictions/{bahamas.id}").json()["governed_species_directory_state"]=="EMPTY";assert client.get(f"/jurisdictions/{barbados.id}/invasive-species").json()["items"]==[]

def test_legacy_excluded_generic_directory_search_pagination_and_detail(public_context):
 s,client,_,jamaica,_,_,admin,lionfish,alga=public_context;assert client.get(f"/jurisdictions/{jamaica.id}/invasive-species").json()["items"]==[];approve_alga(s,admin,jamaica,alga);directory=client.get(f"/jurisdictions/{jamaica.id}/marine-species?page=1&page_size=1&search=Halophila").json();assert directory["total"]==1 and directory["items"][0]["taxon_id"]==alga.id and directory["items"][0]["common_name"]=="Halophila seagrass";assert client.get(f"/jurisdictions/{jamaica.id}/invasive-species").json()["items"]==[];detail=client.get(f"/jurisdictions/{jamaica.id}/species/{alga.id}").json();assert detail["current_reviewed_status"]["statuses"]==["NON_NATIVE"] and detail["occurrence_summary"]["count"]==0;legacy=client.get(f"/jurisdictions/{jamaica.id}/species/{lionfish.id}").json();assert legacy["current_reviewed_status"]["statuses"]==[]

def test_map_filters_and_all_public_gets_are_read_only(public_context):
 s,client,_,jamaica,_,_,_,lionfish,_=public_context;before={model:s.query(model).count() for model in (EcologicalStatusAssertion,GovernedOccurrenceEvidence,HistoricalOccurrence,SpeciesJurisdictionStatus,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)};result=client.get(f"/jurisdictions/{jamaica.id}/species/{lionfish.id}/map").json();assert result["occurrence_points"]==[] and result["verified_observations"]==[] and "Candidate" in result["excluded_evidence"];assert "geometry_hash" not in str(result) and "artifact" not in str(result).lower();assert before=={model:s.query(model).count() for model in before}

def test_frontend_routes_empty_states_and_generic_language():
 app_text=Path("marine-monitoring-frontend/src/App.jsx").read_text(encoding="utf-8");page=Path("marine-monitoring-frontend/src/pages/PublicDirectoryPages.jsx").read_text(encoding="utf-8");assert "/jurisdictions/:jurisdictionId/invasive-species" in app_text and "/regions/:regionSlug" in app_text;assert "No governed invasive marine-species records" in page and "Halophila" not in page and "lionfish" not in page.lower();assert "Source claim" not in page and "fingerprint" not in page.lower()
