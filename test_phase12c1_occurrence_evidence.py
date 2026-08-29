import hashlib, json, sqlite3
from datetime import datetime, timezone
import pytest
from shapely.geometry import mapping, Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from jurisdiction_boundary_registry import canonical_json
from models import *
from occurrence_evidence_service import *
from phase12c1_migrate_occurrence_evidence import run_migration

class FixtureSource(OccurrenceSourceAdapter):
 contract=OccurrenceSourceContract("ECOREEF","UWI ECOREEF","GBIF","dataset-1","2026","https://example.test","CC-BY","Attribution","Jamaica survey",("Incomplete sampling",))
 def __init__(self,root,records):self.root=root;self.records=records
 def acquire(self,jurisdiction,taxon,boundary):
  path=self.root/"source.json";path.write_text(canonical_json(self.records),encoding="utf-8");digest=hashlib.sha256(path.read_bytes()).hexdigest();return SourceAcquisition(tuple(self.records),{"taxon":taxon.scientific_name},{"jurisdiction":jurisdiction.slug},str(path),digest,datetime.now(timezone.utc).isoformat())

@pytest.fixture()
def context(tmp_path):
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);session=sessionmaker(bind=engine)();region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");admin=User(email="admin@test",display_name="Admin",password_hash="x",is_platform_admin=True);session.add_all([region,admin]);session.flush();jamaica=Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",status="ACTIVE",center_latitude=18.1,center_longitude=-77.3,default_zoom=7);barbados=Jurisdiction(region_id=region.id,name="Barbados",slug="barbados",country_code="BB",status="ACTIVE",center_latitude=13.1,center_longitude=-59.6,default_zoom=8);taxon=Species(scientific_name="Pterois volitans",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="159559",taxonomic_rank="SPECIES",accepted_name_status="ACCEPTED",provenance_fingerprint="a"*64);synonym=Species(scientific_name="Gasterosteus volitans",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier="301175",taxonomic_rank="SPECIES",accepted_name_status="SYNONYM",accepted_taxon=taxon,provenance_fingerprint="c"*64);session.add_all([jamaica,barbados,taxon,synonym]);session.flush();session.add(RegionalTaxonRegistry(region_id=region.id,taxon_id=taxon.id,registry_version="v1",inclusion_basis="review",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint="b"*64));source=OccurrenceSourceRegistration(source_registration_id="ECOREEF",source_name="ECOREEF",scientific_provider="UWI ECOREEF",transport_interface="GBIF",provider_dataset_id="dataset-1",provider_dataset_version="2026",acquisition_mechanism="TEST",documentation_reference="https://example.test",license="CC-BY",reuse_conditions="Attribution",geographic_scope_json="{}",taxonomic_scope_json="{}",source_provenance_json="{}",limitations_json="[]",configuration_json="{}",configuration_version="v1",configuration_fingerprint="f"*64,workflow_status="ACTIVE",created_by_user_id=admin.id,approved_configuration_fingerprint="f"*64);session.add(source);session.flush();FixtureSource.registration=source;geometry=canonical_json(mapping(Polygon([(-79,16),(-75,16),(-75,20),(-79,20),(-79,16)])));boundary=JurisdictionBoundary(jurisdiction_id=jamaica.id,boundary_type="MARINE_MONITORING",geometry_json=geometry,source="Marine Regions",source_version="v1",source_reference="ref",provider_boundary_identifier="JM",crs="EPSG:4326",geometry_hash=hashlib.sha256(geometry.encode()).hexdigest(),acquisition_metadata_json="{}",limitations_json="[]",status="ACTIVE");session.add(boundary);session.commit();return session,tmp_path,admin,region,jamaica,barbados,taxon,boundary

def record(identifier="r1",name="Pterois volitans",taxon_id="159559",lat=18.0,lon=-77.0,date="2020-01-02",**extra):return {"provider_occurrence_id":identifier,"observation_reference":f"https://example.test/{identifier}","original_record_reference":f"https://example.test/{identifier}","scientific_name":name,"authoritative_identifier":taxon_id,"latitude":lat,"longitude":lon,"event_date":date,"basis_of_record":"HUMAN_OBSERVATION","source_metadata":{"scientific_provider":"UWI ECOREEF","provider_identity_status":"REPORTED","transport_interface":"GBIF","license":"CC-BY"},**extra}

def test_source_contract_distinguishes_provider_transport_and_fingerprint(context):
 session,root,*_=context;service=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,[record()])]))
 source=service.sources()[0];assert source["scientific_provider"]=="UWI ECOREEF" and source["transport_interface"]=="GBIF"

def test_dry_run_taxonomy_boundary_and_zero_writes(context):
 session,root,admin,_,jamaica,_,taxon,_=context;records=[record(),record("syn","Gasterosteus volitans","301175"),record("complex","Pterois volitans/miles",None),record("outside",lat=25),record("unknown",name="",taxon_id=None,lat=None,lon=None)]
 service=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,records)]));before={m:session.query(m).count() for m in (OccurrenceAcquisitionPreparation,OccurrenceCandidateRecord,GovernedOccurrenceEvidence,ScientificDataset,SpeciesJurisdictionStatus,AnomalyAssessment)};result=service.prepare(jamaica.id,taxon.id,"ECOREEF",admin.id,True)
 assert result["summary"]["taxonomy"]=={"EXACT_ACCEPTED_TAXON":2,"SYNONYM_TO_ACCEPTED_TAXON":1,"SPECIES_COMPLEX":1,"UNRESOLVED":1};assert result["summary"]["boundary"]["OUTSIDE_BOUNDARY"]==1 and result["summary"]["boundary"]["UNRESOLVED"]==1;assert before=={m:session.query(m).count() for m in before}

def test_overlap_classification_is_conservative(context):
 session,root,admin,_,jamaica,_,taxon,boundary=context;historical=HistoricalOccurrence(scientific_name=taxon.scientific_name,taxon_id=159559,latitude=18,longitude=-77,event_date=datetime(2020,1,2),occurrence_id="same",source="OBIS",deduplication_key="same",imported_at=datetime.now(timezone.utc));session.add(historical);session.commit();records=[record("same"),record("different"),record(None,upstream_occurrence_id=None,event_date=None,latitude=18.2,longitude=-77.2)]
 result=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,records)])).prepare(jamaica.id,taxon.id,"ECOREEF",admin.id,True);classes={item["provider_occurrence_id"]:item["overlap_classification"] for item in result["candidates"]};assert classes["same"]=="VERIFIED_OVERLAP" and classes["different"]=="POSSIBLE_OVERLAP" and classes[None]=="INDEPENDENCE_UNKNOWN"

def test_review_apply_staleness_idempotency_and_firewall(context):
 session,root,admin,_,jamaica,barbados,taxon,_=context;service=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,[record()])]))
 prepared=service.prepare(jamaica.id,taxon.id,"ECOREEF",admin.id);candidate=prepared["candidates"][0];service.approve(prepared["id"],[candidate["id"]],admin.id,"review-1");before={m:session.query(m).count() for m in (SpeciesJurisdictionStatus,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)};applied=service.apply(prepared["id"]);assert applied["apply_status"]=="APPLIED" and applied["firewall"]["status"]=="PASS" and session.query(GovernedOccurrenceEvidence).count()==1 and before=={m:session.query(m).count() for m in before};assert service.apply(prepared["id"])["apply_status"]=="NO-OP";assert session.query(GovernedOccurrenceEvidence).filter_by(jurisdiction_id=barbados.id).count()==0

def test_changed_artifact_invalidates_approval(context):
 session,root,admin,_,jamaica,_,taxon,_=context;service=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,[record()])])) ;prepared=service.prepare(jamaica.id,taxon.id,"ECOREEF",admin.id);service.approve(prepared["id"],[prepared["candidates"][0]["id"]],admin.id,"review");open(session.get(OccurrenceAcquisitionPreparation,prepared["id"]).raw_artifact_reference,"w",encoding="utf-8").write("changed")
 with pytest.raises(ValueError,match="stale"):service.apply(prepared["id"])
 assert session.get(OccurrenceAcquisitionPreparation,prepared["id"]).workflow_status=="STALE"

def test_empty_jurisdiction_and_readiness(context):
 session,root,_,_,jamaica,barbados,taxon,_=context;service=OccurrenceEvidenceService(session,OccurrenceSourceRegistry([FixtureSource(root,[])]));assert service.readiness(jamaica.id,taxon.id,"ECOREEF")=="READY_FOR_ACQUISITION" and service.readiness(barbados.id,taxon.id,"ECOREEF")=="BOUNDARY_UNAVAILABLE" and session.query(GovernedOccurrenceEvidence).filter_by(jurisdiction_id=barbados.id).count()==0

def test_migration_twice(tmp_path):
 connection=sqlite3.connect(tmp_path/"m.db");connection.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY);CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY);CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE scientific_datasets(id INTEGER PRIMARY KEY);");first=run_migration(connection);second=run_migration(connection);assert all(first.values()) and not any(second.values())

def test_admin_authorization():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).get("/admin/occurrence-sources").status_code==401
