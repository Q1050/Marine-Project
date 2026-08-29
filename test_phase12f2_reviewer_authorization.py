from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from auth_service import reviewer_jurisdiction_ids
from models import Jurisdiction, Observation, ObservationNotificationEvent, ObservationOperationalCase, ObservationOperationalEvent, ObservationReviewerGrant, Region, User
from observation_operations_service import ObservationOperationsService


def session():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def fixture(db):
    region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");db.add(region);db.flush()
    jamaica=Jurisdiction(region_id=region.id,name="Jamaica",slug="jamaica",country_code="JM",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="JM",jurisdiction_type="COUNTRY",status="ACTIVE",center_latitude=18.1,center_longitude=-77.3,default_zoom=8)
    bahamas=Jurisdiction(region_id=region.id,name="Bahamas",slug="bahamas",country_code="BS",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="BS",jurisdiction_type="COUNTRY",status="ACTIVE",center_latitude=24.2,center_longitude=-76.0,default_zoom=7)
    admin=User(email="admin@example.test",display_name="Admin",password_hash="x",status="ACTIVE",is_platform_admin=True)
    reviewer=User(email="reviewer@example.test",display_name="Reviewer",password_hash="x",status="ACTIVE",is_platform_admin=False)
    db.add_all([jamaica,bahamas,admin,reviewer]);db.flush()
    db.add(ObservationReviewerGrant(user_id=reviewer.id,jurisdiction_id=jamaica.id,role="JURISDICTION_REVIEWER",status="ACTIVE",granted_by_user_id=admin.id,grant_reference="test"))
    obs=Observation(jurisdiction_id=jamaica.id,species="Pterois volitans",latitude=18.2,longitude=-77.1,image_filename="private.jpg",identification_status="REVIEW_REQUIRED",ecological_status="UNKNOWN",decision="REVIEW",priority="NORMAL",verification_status="PENDING")
    db.add(obs);db.commit();return jamaica,bahamas,admin,reviewer,obs


def test_grant_scope_revocation_and_admin_override():
    db=session();jm,bs,admin,reviewer,_=fixture(db)
    assert reviewer_jurisdiction_ids(db,reviewer)=={jm.id}
    assert reviewer_jurisdiction_ids(db,admin)=={jm.id,bs.id}
    grant=db.query(ObservationReviewerGrant).one();grant.status="REVOKED";db.commit()
    assert reviewer_jurisdiction_ids(db,reviewer)==set()


def test_assignment_information_timeline_and_firewall():
    db=session();_,_,_,reviewer,obs=fixture(db);service=ObservationOperationsService(db)
    service.claim(obs.id,reviewer.id,"Claimed")
    service.request_information(obs.id,reviewer.id,"Please provide another image")
    case=db.query(ObservationOperationalCase).one()
    assert case.assigned_reviewer_user_id==reviewer.id
    assert case.workflow_state=="AWAITING_REPORTER_INFORMATION"
    assert [e.event_type for e in db.query(ObservationOperationalEvent).order_by(ObservationOperationalEvent.id)]==["CASE_OPENED","ASSIGNED","ADDITIONAL_INFORMATION_REQUESTED"]
    assert [e.event_type for e in db.query(ObservationNotificationEvent).order_by(ObservationNotificationEvent.id)]==["CASE_ASSIGNED","ADDITIONAL_INFORMATION_REQUESTED"]
    assert service.history(obs.id)[-1]["actor_display_name"]=="Reviewer"
    assert obs.verification_status == "PENDING"


def test_invalid_cross_jurisdiction_assignment_and_claim_race():
    db=session();jm,_,admin,reviewer,obs=fixture(db)
    outsider=User(email="other@example.test",display_name="Other",password_hash="x",status="ACTIVE",is_platform_admin=False);db.add(outsider);db.commit()
    service=ObservationOperationsService(db)
    try:service.assign(obs.id,outsider.id,admin.id,"invalid")
    except ValueError as error:assert "lacks" in str(error)
    else:assert False
    service.claim(obs.id,reviewer.id,"claim")
    try:service.assign(obs.id,admin.id,admin.id,"stale",expected_reviewer_id=None)
    except ValueError:pass
    # Explicit optimistic expectation rejects stale clients.
    try:service.assign(obs.id,admin.id,admin.id,"stale",expected_reviewer_id=outsider.id)
    except ValueError as error:assert "changed" in str(error)
    else:assert False
