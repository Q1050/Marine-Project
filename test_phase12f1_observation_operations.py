import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest
from database import Base
from models import *
from observation_operations_service import ObservationOperationsService
from phase12f1_migrate_observation_operations import run_migration

@pytest.fixture()
def context():
 e=create_engine("sqlite:///:memory:");Base.metadata.create_all(e);s=sessionmaker(bind=e)();r=Region(name="Caribbean",slug="caribbean",status="ACTIVE");u=User(email="admin@test",display_name="Admin",password_hash="x",is_platform_admin=True);s.add_all([r,u]);s.flush();j=Jurisdiction(region_id=r.id,name="Jamaica",slug="jamaica",country_code="JM",status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=7);b=Jurisdiction(region_id=r.id,name="Barbados",slug="barbados",country_code="BB",status="ACTIVE",center_latitude=13,center_longitude=-59,default_zoom=7);s.add_all([j,b]);s.flush();o=Observation(jurisdiction_id=j.id,image_filename="x.jpg",latitude=18,longitude=-77,identification_status="AI_SUPPORTED",species="Pterois volitans",score=.8,ecological_status="UNKNOWN",decision="REVIEW",priority="HIGH",verification_status="PENDING",reporter_suggested_scientific_name="Pterois miles");other=Observation(jurisdiction_id=b.id,image_filename="y.jpg",latitude=13,longitude=-59,identification_status="UNKNOWN",ecological_status="UNKNOWN",decision="REVIEW",priority="LOW",verification_status="PENDING");s.add_all([o,other]);s.commit();return s,u,j,b,o,other

def test_triage_assignment_priority_identity_and_audit(context):
 s,u,_,_,o,_=context;service=ObservationOperationsService(s);assert s.query(ObservationOperationalCase).count()==0 and service.identity(o)["source"]=="AI";value=service.triage(o.id,u.id);assert value["triage_route"]=="EXPERT_REVIEW_REQUIRED" and value["workflow_state"]=="AWAITING_EXPERT_REVIEW";service.assign(o.id,u.id,u.id,"assignment");service.priority(o.id,"HIGH",u.id,"workload urgency only");assert len(service.history(o.id))==4
 event=s.query(ObservationOperationalEvent).first();event.reason_reference="changed"
 with pytest.raises(ValueError,match="append-only"):s.commit()

def test_expert_precedence_correction_duplicate_closure_and_handoff_firewall(context):
 s,u,_,_,o,_=context;service=ObservationOperationsService(s);before={m:s.query(m).count() for m in (GovernedOccurrenceEvidence,EcologicalStatusAssertion,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal)};corrected=service.disposition(o.id,"CORRECTED",u.id,"Pterois antennata","expert evidence");assert corrected["resolved_identity"]=={"source":"EXPERT","species":"Pterois antennata","state":"CORRECTED"} and corrected["reporter_suggestion"]=="Pterois miles" and corrected["ai_identification"]["species"]=="Pterois volitans";assert corrected["evidence_handoff_state"]=="ELIGIBLE_FOR_SCIENTIFIC_EVIDENCE_REVIEW";service.close(o.id,u.id,"review complete");assert service.case(o.id)[1].workflow_state=="CLOSED";assert before=={m:s.query(m).count() for m in before}

def test_duplicate_and_jurisdiction_isolation(context):
 s,u,j,b,o,other=context;service=ObservationOperationsService(s);o.is_possible_duplicate=True;o.duplicate_of_observation_id=other.id;s.commit();assert service.triage_route(o)=="DUPLICATE_REVIEW";value=service.disposition(o.id,"CONFIRMED_DUPLICATE",u.id,reason="same submission");assert value["workflow_state"]=="DUPLICATE";assert o.jurisdiction_id==j.id and other.jurisdiction_id==b.id

def test_migration_idempotent_and_no_backfill(tmp_path):
 c=sqlite3.connect(tmp_path/"x.db");first=run_migration(c);second=run_migration(c);assert len(first["tables_created"])==2 and second["tables_created"]==[];assert c.execute("select count(*) from observation_operational_cases").fetchone()[0]==0

def test_admin_protected_and_frontend_contract():
 from fastapi.testclient import TestClient
 from api import app
 assert TestClient(app).get("/admin/observations/queue").status_code==401
 text=open("marine-monitoring-frontend/src/pages/AdminObservationOperationsPage.jsx",encoding="utf-8").read();assert "priority is not ecological severity" in text and "does not establish ecological status" in text
