import hashlib,json,sqlite3
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import *
from obis_occurrence_adapter import OBISOccurrenceAdapter
from occurrence_evidence_service import _date
from occurrence_source_governance import OccurrenceSourceGovernanceService,source_fingerprint
from phase12c1_migrate_occurrence_evidence import run_migration as c1_migration
from phase12c2_migrate_occurrence_sources import run_migration

def source_payload():return {"source_registration_id":"OBIS_V3","source_name":"OBIS occurrence API","scientific_provider":"RECORD_LEVEL_PROVIDER_AS_REPORTED_BY_OBIS","transport_interface":"OBIS","provider_dataset_id":None,"provider_dataset_version":"v3","acquisition_mechanism":"OBIS_V3_API","documentation_reference":"https://api.obis.org/","license":"RECORD_LEVEL_LICENSE","reuse_conditions":"Respect record-level dataset license and attribution.","geographic_scope":{"type":"BOUNDARY_QUERY","description":"Global API constrained to governed boundary"},"taxonomic_scope":{"type":"AUTHORITATIVE_TAXON_ID"},"source_provenance":{"operator":"OBIS Secretariat"},"limitations":["Underlying provider may be unavailable on individual records."],"configuration":{"api_url":"https://api.obis.org/v3/occurrence","page_size":2},"configuration_version":"obis-adapter-v1"}

@pytest.fixture()
def db():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);session=sessionmaker(bind=engine)();user=User(email="a@b.c",display_name="Admin",password_hash="x",is_platform_admin=True);session.add(user);session.commit();return session,user

def test_generic_registration_lifecycle_and_deterministic_fingerprint(db):
 session,user=db;service=OccurrenceSourceGovernanceService(session);payload=source_payload();assert source_fingerprint(payload)==source_fingerprint(dict(reversed(list(payload.items()))));row=service.register(payload,user.id);assert row.workflow_status=="READY_FOR_REVIEW";assert service.register(payload,user.id).id==row.id;service.approve(row,user.id,"review");assert row.workflow_status=="APPROVED";service.activate(row);assert row.workflow_status=="ACTIVE";service.deactivate(row);assert row.workflow_status=="DEACTIVATED"

def test_configuration_change_invalidates_approval(db):
 session,user=db;service=OccurrenceSourceGovernanceService(session);row=service.register(source_payload(),user.id);service.approve(row,user.id,"review");row.license="changed"
 with pytest.raises(ValueError,match="stale"):service.activate(row)

class Response:
 def __init__(self,payload):self.payload=payload
 def raise_for_status(self):pass
 def json(self):return self.payload
class PagedHTTP:
 def __init__(self,records,total=None):self.records=records;self.total=len(records) if total is None else total;self.calls=[]
 def get(self,url,params,timeout):
  self.calls.append(dict(params));start=params["offset"];size=params["size"];return Response({"total":self.total,"results":self.records[start:start+size]})

def registration(db):
 session,user=db;service=OccurrenceSourceGovernanceService(session);row=service.register(source_payload(),user.id);service.approve(row,user.id,"review");service.activate(row);return row
def obis_record(index):return {"id":f"obis-{index}","occurrenceID":f"urn:event:{index}","eventID":f"event-{index}","catalogNumber":f"cat-{index}","scientificName":"Pterois volitans","AphiaID":159559,"decimalLatitude":18+index/100,"decimalLongitude":-77,"eventDate":"2020-01-01","basisOfRecord":"HumanObservation","institutionCode":"UWI","dataset_id":"dataset-x","datasetName":"Survey X","license":"CC-BY"}

def test_obis_adapter_is_generic_paginated_complete_and_preserves_provenance(db,tmp_path):
 row=registration(db);http=PagedHTTP([obis_record(i) for i in range(5)]);adapter=OBISOccurrenceAdapter(row,http,tmp_path);jurisdiction=SimpleNamespace(id=77,slug="any-jurisdiction");taxon=SimpleNamespace(id=88,scientific_name="Any species",authoritative_identifier="159559");boundary=SimpleNamespace(id=99,geometry_json=json.dumps({"type":"Polygon","coordinates":[[[-80,15],[-70,15],[-70,25],[-80,25],[-80,15]]]}),geometry_hash="g"*64)
 result=adapter.acquire(jurisdiction,taxon,boundary);assert len(http.calls)==3 and len(result.records)==5;diagnostics=result.acquisition_parameters["diagnostics"];assert diagnostics["complete"] and diagnostics["pages_retrieved"]==3 and diagnostics["actual_records_retrieved"]==5;first=result.records[0];assert first["source_metadata"]["transport_interface"]=="OBIS" and first["source_metadata"]["scientific_provider"]=="UWI";assert hashlib.sha256(open(result.raw_artifact_reference,"rb").read()).hexdigest()==result.raw_artifact_sha256
 assert result.acquisition_parameters["provider_query_geometry_method"]=="GOVERNED_BOUNDARY_ENVELOPE"

def test_provider_timestamps_are_normalized_to_utc():
 assert _date("2024-01-02T20:58:37-05:00").isoformat()=="2024-01-03T01:58:37"

def test_incomplete_provider_result_fails_closed(db,tmp_path):
 row=registration(db);adapter=OBISOccurrenceAdapter(row,PagedHTTP([obis_record(1)],total=2),tmp_path);jurisdiction=SimpleNamespace(id=1,slug="j");taxon=SimpleNamespace(id=1,scientific_name="x",authoritative_identifier="1");boundary=SimpleNamespace(id=1,geometry_json=json.dumps({"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}),geometry_hash="x")
 with pytest.raises(RuntimeError,match="Incomplete"):adapter.acquire(jurisdiction,taxon,boundary)

def test_migration_idempotent(tmp_path):
 connection=sqlite3.connect(tmp_path/"m.db");connection.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY);CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY);CREATE TABLE species(id INTEGER PRIMARY KEY);CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY);CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE scientific_datasets(id INTEGER PRIMARY KEY);");c1_migration(connection);assert run_migration(connection)=={"source_table_created":True,"preparation_link_added":True};assert run_migration(connection)=={"source_table_created":False,"preparation_link_added":False}

def test_admin_source_mutations_are_protected():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).post("/admin/occurrence-sources",json=source_payload()).status_code==401
