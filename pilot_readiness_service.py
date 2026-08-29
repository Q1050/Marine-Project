"""Operational pilot utilities without scientific side effects."""
import hashlib,json,secrets
from datetime import datetime,timedelta,timezone
from models import Observation,ObservationOperationalCase,ObservationOperationalEvent,ObservationNotificationEvent,ReporterAccessToken,ReporterAdditionalInformation

TOKEN_LIFETIME=timedelta(days=30)
def utcnow():return datetime.now(timezone.utc)
def _aware(value):return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
class ReporterAccessService:
 def __init__(self,session):self.session=session
 def issue(self,observation_id,purpose="STATUS",case_id=None):
  raw=secrets.token_urlsafe(32);now=utcnow();row=ReporterAccessToken(observation_id=observation_id,case_id=case_id,purpose=purpose,token_hash=hashlib.sha256(raw.encode()).hexdigest(),public_reference=f"MM-{secrets.token_hex(5).upper()}",expires_at=now+TOKEN_LIFETIME,created_at=now);self.session.add(row);self.session.flush();return row,raw
 def resolve(self,raw,purpose=None):
  row=self.session.query(ReporterAccessToken).filter_by(token_hash=hashlib.sha256(raw.encode()).hexdigest()).one_or_none()
  if not row or row.revoked_at or _aware(row.expires_at)<=utcnow() or purpose and row.purpose!=purpose:raise ValueError("Reporter access link is invalid or expired")
  return row
 def safe_status(self,raw):
  token=self.resolve(raw);observation=self.session.get(Observation,token.observation_id);case=self.session.query(ObservationOperationalCase).filter_by(observation_id=observation.id).one_or_none();state=case.workflow_state if case else "SUBMITTED"
  public="MORE_INFORMATION_REQUESTED" if state=="AWAITING_REPORTER_INFORMATION" else "VERIFIED" if state in {"VERIFIED","CORRECTED"} else "CLOSED" if state=="CLOSED" else "UNDER_REVIEW" if case else "SUBMITTED"
  return {"reference":token.public_reference,"status":public,"submitted_at":observation.created_at,"message":"AI-assisted identification is preliminary until expert review."}
 def respond(self,raw,text,image_filename=None):
  token=self.resolve(raw,"RESPONSE");case=self.session.get(ObservationOperationalCase,token.case_id)
  if not case or case.observation_id!=token.observation_id:raise ValueError("Reporter request is no longer available")
  row=ReporterAdditionalInformation(observation_id=token.observation_id,case_id=case.id,token_id=token.id,response_text=text.strip(),image_filename=image_filename);self.session.add(row);self.session.add(ObservationOperationalEvent(case_id=case.id,observation_id=token.observation_id,actor_user_id=None,event_type="REPORTER_INFORMATION_RECEIVED",previous_state=case.workflow_state,current_state="IN_REVIEW",reason_reference="Reporter supplied additional information",identity_state_json="{}",provenance_version="observation-operations-v1"));case.workflow_state="IN_REVIEW";token.revoked_at=utcnow();self.session.commit();return row

class NotificationDeliveryService:
 def __init__(self,session):self.session=session
 def attempt(self,event_id):
  row=self.session.get(ObservationNotificationEvent,event_id)
  if not row:raise ValueError("Notification event not found")
  if row.delivery_state=="DELIVERED":return row
  row.delivery_attempts+=1;row.last_attempted_at=utcnow();row.delivery_state="RETRYABLE";row.last_delivery_error="External delivery is disabled; manual inspection required.";self.session.commit();return row
