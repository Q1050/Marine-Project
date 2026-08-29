from datetime import datetime,timedelta,timezone
from pathlib import Path
from test_phase12f2_reviewer_authorization import fixture,session
from models import EcologicalStatusAssertion,GovernedOccurrenceEvidence,ObservationNotificationEvent,ObservationOperationalCase,ReporterAccessToken,ReporterAdditionalInformation
from observation_operations_service import ObservationOperationsService
from pilot_readiness_service import NotificationDeliveryService,ReporterAccessService

def test_opaque_reporter_status_token_is_hashed_and_private():
    db=session();*_,obs=fixture(db);service=ReporterAccessService(db);row,raw=service.issue(obs.id);db.commit()
    assert raw not in row.token_hash and len(row.token_hash)==64
    status=service.safe_status(raw);assert status["status"]=="SUBMITTED"
    assert "reviewer" not in status and "priority" not in status

def test_information_request_response_audit_and_scientific_firewall():
    db=session();_,_,_,reviewer,obs=fixture(db);before=(db.query(GovernedOccurrenceEvidence).count(),db.query(EcologicalStatusAssertion).count());result=ObservationOperationsService(db).request_information(obs.id,reviewer.id,"Please provide context");raw=result["reporter_response_token"]
    ReporterAccessService(db).respond(raw,"Photographed from the pier.")
    case=db.query(ObservationOperationalCase).one();assert case.workflow_state=="IN_REVIEW";assert db.query(ReporterAdditionalInformation).count()==1;assert (db.query(GovernedOccurrenceEvidence).count(),db.query(EcologicalStatusAssertion).count())==before
    try:ReporterAccessService(db).respond(raw,"replay")
    except ValueError:pass
    else:assert False

def test_expired_token_and_notification_retry_lifecycle():
    db=session();_,_,_,reviewer,obs=fixture(db);result=ObservationOperationsService(db).request_information(obs.id,reviewer.id,"Need context");token=db.query(ReporterAccessToken).filter_by(purpose="RESPONSE").one();token.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    try:ReporterAccessService(db).resolve(result["reporter_response_token"])
    except ValueError:pass
    else:assert False
    event=db.query(ObservationNotificationEvent).one();NotificationDeliveryService(db).attempt(event.id);assert event.delivery_state=="RETRYABLE" and event.delivery_attempts==1 and event.last_delivery_error

def test_legacy_upload_mount_removed_and_frontend_contracts_present():
    api=Path("api.py").read_text(encoding="utf-8");assert 'app.mount(\n    "/uploads"' not in api;assert "protected_observation_image" in api
    app=Path("marine-monitoring-frontend/src/App.jsx").read_text(encoding="utf-8");assert "ReviewerHomePage" in app and "AdminReviewerAccessPage" in app and "ReporterStatusPage" in app
