import os,threading,uuid
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from auth_service import hash_password
from early_warning_operations import EarlyWarningOperations
from models import AnomalyAssessment,AnomalyReviewAssignment,Jurisdiction,Observation,ObservationNotificationEvent,ObservationOperationalCase,ObservationOperationalEvent,ObservationReviewerGrant,Region,ScientificDomainEvent,ScientificReviewerGrant,User
from observation_operations_service import ObservationOperationsService
from production_operations import EventWorker

URL=os.getenv("TEST_POSTGRES_URL")
pytestmark=pytest.mark.skipif(not URL,reason="TEST_POSTGRES_URL is required for PostgreSQL integration")

@pytest.fixture
def pg():
    engine=create_engine(URL,pool_pre_ping=True);Session=sessionmaker(bind=engine,expire_on_commit=False);suffix=uuid.uuid4().hex[:8]
    with Session() as db:
        jurisdiction=db.query(Jurisdiction).filter_by(slug="jamaica").one_or_none();created_region=None;created_jurisdiction=None
        if jurisdiction is None:
            created_region=Region(name="M15 Test Region",slug=f"m15-test-{suffix}",status="ACTIVE");db.add(created_region);db.flush();jurisdiction=Jurisdiction(region_id=created_region.id,name="M15 Test Jurisdiction",slug="jamaica",country_code="ZZ",status="ACTIVE",center_latitude=0,center_longitude=0,default_zoom=4);db.add(jurisdiction);db.flush();created_jurisdiction=jurisdiction.id
        actor=db.query(User).filter_by(is_platform_admin=True).first();created_actor=None
        if actor is None:actor=User(email=f"m15-admin-{suffix}@test.invalid",display_name="M15 Test Admin",password_hash=hash_password("controlled-test-password"),status="ACTIVE",is_platform_admin=True);db.add(actor);db.flush();created_actor=actor.id
        users=[]
        for index in range(2):
            row=User(email=f"m15-{suffix}-{index}@test.invalid",display_name=f"M15 Reviewer {index}",password_hash=hash_password("controlled-test-password"),status="ACTIVE",is_platform_admin=False);db.add(row);db.flush();users.append(row)
            db.add(ObservationReviewerGrant(user_id=row.id,jurisdiction_id=jurisdiction.id,role="JURISDICTION_REVIEWER",status="ACTIVE",granted_by_user_id=actor.id,grant_reference="M15 concurrency fixture"));db.add(ScientificReviewerGrant(user_id=row.id,jurisdiction_id=jurisdiction.id,role="JURISDICTION_SCIENTIFIC_REVIEWER",status="ACTIVE",granted_by_user_id=actor.id,grant_reference="M15 concurrency fixture"))
        observation=Observation(jurisdiction_id=jurisdiction.id,image_filename="m15-private-fixture.jpg",latitude=18,longitude=-77,identification_status="UNCERTAIN",species=None,candidates_json="[]",ecological_status="UNKNOWN",decision="REVIEW",priority="NORMAL",reason="M15 TEST ONLY",verification_status="PENDING");db.add(observation);db.flush();case=ObservationOperationalCase(observation_id=observation.id,jurisdiction_id=jurisdiction.id);db.add(case)
        assessment=AnomalyAssessment(observation_id=observation.id,jurisdiction_id=jurisdiction.id,overall_status="INSUFFICIENT_EVIDENCE",overall_classification=None,assessment_confidence="LOW",requires_review=True,review_type="SCIENTIFIC_REVIEW",provenance_version="m15-test",current_state="CURRENT",evidence_summary_json="{}",limitations_json='["TEST ONLY"]',provenance_json="{}") ;db.add(assessment)
        event=ScientificDomainEvent(event_type="OBSERVATION_EXPERT_VERIFIED",jurisdiction_id=jurisdiction.id,observation_id=observation.id,event_fingerprint=uuid.uuid4().hex.ljust(64,"0"),payload_json="{}",processing_state="PENDING");db.add(event);db.commit();ids={"users":[u.id for u in users],"observation":observation.id,"assessment":assessment.id,"event":event.id,"created_actor":created_actor,"created_jurisdiction":created_jurisdiction,"created_region":created_region.id if created_region else None}
    yield engine,Session,ids
    with engine.begin() as c:
        c.execute(text("DELETE FROM platform_audit_events WHERE target_type='ScientificDomainEvent' AND target_id=:target"),{"target":str(ids["event"])})
        c.execute(text("DELETE FROM anomaly_review_assignments WHERE anomaly_assessment_id=:id"),{"id":ids["assessment"]});c.execute(text("DELETE FROM anomaly_review_events WHERE anomaly_assessment_id=:id"),{"id":ids["assessment"]});c.execute(text("DELETE FROM anomaly_signals WHERE anomaly_assessment_id=:id"),{"id":ids["assessment"]});c.execute(text("DELETE FROM anomaly_assessments WHERE id=:id"),{"id":ids["assessment"]})
        c.execute(text("DELETE FROM scientific_domain_events WHERE id=:id"),{"id":ids["event"]});c.execute(text("DELETE FROM observation_notification_events WHERE case_id IN (SELECT id FROM observation_operational_cases WHERE observation_id=:id)"),{"id":ids["observation"]});c.execute(text("DELETE FROM observation_operational_events WHERE observation_id=:id"),{"id":ids["observation"]});c.execute(text("DELETE FROM observation_operational_cases WHERE observation_id=:id"),{"id":ids["observation"]});c.execute(text("DELETE FROM observation_reviewer_grants WHERE user_id=ANY(:ids)"),{"ids":ids["users"]});c.execute(text("DELETE FROM scientific_reviewer_grants WHERE user_id=ANY(:ids)"),{"ids":ids["users"]});c.execute(text("DELETE FROM observations WHERE id=:id"),{"id":ids["observation"]});c.execute(text("DELETE FROM users WHERE id=ANY(:ids)"),{"ids":ids["users"]})
        if ids["created_actor"]:c.execute(text("DELETE FROM users WHERE id=:id"),{"id":ids["created_actor"]})
        if ids["created_jurisdiction"]:c.execute(text("DELETE FROM jurisdictions WHERE id=:id"),{"id":ids["created_jurisdiction"]})
        if ids["created_region"]:c.execute(text("DELETE FROM regions WHERE id=:id"),{"id":ids["created_region"]})

def parallel(callables):
    barrier=threading.Barrier(len(callables));results=[];lock=threading.Lock()
    def run(fn):
        barrier.wait()
        try:value=("OK",fn())
        except Exception as exc:value=("ERROR",type(exc).__name__)
        with lock:results.append(value)
    threads=[threading.Thread(target=run,args=(fn,)) for fn in callables]
    for thread in threads:thread.start()
    for thread in threads:thread.join(15)
    return results

def test_true_postgres_operational_scientific_and_worker_claims(pg):
    engine,Session,ids=pg
    def operational(user):
        with Session() as db:return ObservationOperationsService(db).claim(ids["observation"],user,"M15 competing claim")["assigned_reviewer_user_id"]
    results=parallel([lambda:operational(ids["users"][0]),lambda:operational(ids["users"][1])]);assert [r[0] for r in results].count("OK")==1;assert [r[0] for r in results].count("ERROR")==1
    def scientific(user):
        with Session() as db:
            row=db.get(AnomalyAssessment,ids["assessment"]);value=EarlyWarningOperations(db).claim(row,user,user,"M15 competing scientific claim");db.commit();return value.reviewer_user_id
    results=parallel([lambda:scientific(ids["users"][0]),lambda:scientific(ids["users"][1])]);assert [r[0] for r in results].count("OK")==1;assert [r[0] for r in results].count("ERROR")==1
    def worker(name):
        with Session() as db:
            row=EventWorker(db,name).claim_one(ids["event"]);return row.id if row else None
    results=parallel([lambda:worker("m15-worker-a"),lambda:worker("m15-worker-b")]);assert sum(r[0]=="OK" and r[1] is not None for r in results)==1

def test_sequences_advance_beyond_migrated_ids_and_rollback(pg):
    engine,_,_=pg
    with engine.connect() as c:
        transaction=c.begin();maximum=c.execute(text("SELECT max(id) FROM jurisdictions")).scalar();new_id=c.execute(text("INSERT INTO jurisdictions(region_id,name,slug,country_code,status,center_latitude,center_longitude,default_zoom,created_at,updated_at) VALUES (1,'M15 TEST','m15-sequence-test','ZZ','INACTIVE',0,0,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id")).scalar();assert new_id>maximum;transaction.rollback()
