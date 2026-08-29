"""Operational case management, deliberately separate from scientific interpretation."""
import json
from datetime import datetime,timezone
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from models import Observation,ObservationOperationalCase,ObservationOperationalEvent,ObservationNotificationEvent,ObservationReviewerGrant,User,GovernedOccurrenceEvidence,EcologicalStatusAssertion
from pilot_readiness_service import ReporterAccessService
STATES={"SUBMITTED","TRIAGE_REQUIRED","IN_REVIEW","AWAITING_IDENTIFICATION","AWAITING_EXPERT_REVIEW","AWAITING_REPORTER_INFORMATION","VERIFIED","CORRECTED","REJECTED","DUPLICATE","CLOSED"};PRIORITIES={"LOW","NORMAL","HIGH","URGENT"}
class ObservationOperationsService:
 def __init__(self,session):self.session=session
 def identity(self,o):
  if o.verification_status in {"CONFIRMED","CORRECTED"} and o.verified_species:return {"source":"EXPERT","species":o.verified_species,"state":o.verification_status}
  if o.identification_status not in {"UNKNOWN","UNRESOLVED","REVIEW_REQUIRED"} and o.species:return {"source":"AI","species":o.species,"state":"AI_SUGGESTED"}
  if o.reporter_suggested_scientific_name:return {"source":"REPORTER","species":o.reporter_suggested_scientific_name,"state":"REPORTER_SUGGESTED"}
  return {"source":"NONE","species":None,"state":"UNRESOLVED"}
 def triage_route(self,o):
  if not o.image_filename or o.latitude is None or o.longitude is None:return "METADATA_INCOMPLETE"
  if o.is_possible_duplicate:return "DUPLICATE_REVIEW"
  if not o.species:return "IDENTIFICATION_REQUIRED"
  if o.verification_status in {"CONFIRMED","CORRECTED"}:return "READY_FOR_REVIEW"
  return "EXPERT_REVIEW_REQUIRED"
 def case(self,observation_id,create=True):
  o=self.session.get(Observation,observation_id)
  if not o:raise ValueError("Observation not found")
  row=self.session.query(ObservationOperationalCase).filter_by(observation_id=o.id).one_or_none()
  if not row and create:
   row=ObservationOperationalCase(observation_id=o.id,jurisdiction_id=o.jurisdiction_id,workflow_state="TRIAGE_REQUIRED",operational_priority="NORMAL",duplicate_disposition="POSSIBLE_DUPLICATE" if o.is_possible_duplicate else "NOT_ASSESSED");self.session.add(row)
   try:self.session.flush();self._event(row,None,"CASE_OPENED",None,"TRIAGE_REQUIRED","Compatibility case created from existing observation facts")
   except IntegrityError:self.session.rollback();o=self.session.get(Observation,observation_id);row=self.session.query(ObservationOperationalCase).filter_by(observation_id=o.id).one()
  return o,row
 def triage(self,id,actor):
  o,row=self.case(id);route=self.triage_route(o);target={"IDENTIFICATION_REQUIRED":"AWAITING_IDENTIFICATION","EXPERT_REVIEW_REQUIRED":"AWAITING_EXPERT_REVIEW","DUPLICATE_REVIEW":"IN_REVIEW","READY_FOR_REVIEW":"IN_REVIEW","METADATA_INCOMPLETE":"IN_REVIEW"}[route];self._transition(row,target,"TRIAGE",actor,route,o);row.triage_route=route;self.session.commit();return self.payload(o,row)
 def reviewer_allowed(self,reviewer_id,jurisdiction_id):
  user=self.session.get(User,reviewer_id)
  return bool(user and user.status=="ACTIVE" and (user.is_platform_admin or self.session.query(ObservationReviewerGrant).filter_by(user_id=reviewer_id,jurisdiction_id=jurisdiction_id,status="ACTIVE",role="JURISDICTION_REVIEWER").first()))
 def assign(self,id,reviewer_id,actor,reason,expected_reviewer_id=None):
  o,row=self.case(id)
  if reviewer_id is not None and not self.reviewer_allowed(reviewer_id,row.jurisdiction_id):raise ValueError("Reviewer lacks active jurisdiction access")
  if expected_reviewer_id is not None and row.assigned_reviewer_user_id!=expected_reviewer_id:raise ValueError("Assignment changed; refresh before retrying")
  previous_reviewer=row.assigned_reviewer_user_id;previous=row.workflow_state;row.assigned_reviewer_user_id=reviewer_id;row.assigned_at=datetime.now(timezone.utc) if reviewer_id else None
  event="UNASSIGNED" if reviewer_id is None else "REASSIGNED" if previous_reviewer else "ASSIGNED";self._event(row,actor,event,previous,row.workflow_state,reason);self._notify(row,"CASE_ASSIGNED",reviewer_id,{"previous_reviewer_user_id":previous_reviewer}) if reviewer_id else None;self.session.commit();return self.payload(o,row)
 def claim(self,id,actor,reason):
  o,row=self.case(id)
  if not self.reviewer_allowed(actor,row.jurisdiction_id):raise ValueError("Reviewer lacks active jurisdiction access")
  if row.assigned_reviewer_user_id==actor:return self.payload(o,row)
  updated=self.session.query(ObservationOperationalCase).filter(ObservationOperationalCase.id==row.id,ObservationOperationalCase.assigned_reviewer_user_id.is_(None)).update({ObservationOperationalCase.assigned_reviewer_user_id:actor,ObservationOperationalCase.assigned_at:datetime.now(timezone.utc)},synchronize_session=False)
  if updated!=1:self.session.rollback();raise ValueError("Case has already been claimed")
  self.session.refresh(row);self._event(row,actor,"ASSIGNED",row.workflow_state,row.workflow_state,reason);self._notify(row,"CASE_ASSIGNED",actor,{"previous_reviewer_user_id":None});self.session.commit();return self.payload(o,row)
 def priority(self,id,value,actor,reason):
  if value not in PRIORITIES:raise ValueError("Invalid operational priority")
  o,row=self.case(id);row.operational_priority=value;row.priority_reason=reason;row.priority_changed_by_user_id=actor;self._event(row,actor,"PRIORITY_CHANGED",row.workflow_state,row.workflow_state,reason);self.session.commit();return self.payload(o,row)
 def disposition(self,id,value,actor,species=None,reason=None):
  o,row=self.case(id);previous_identity=self.identity(o)
  if value=="CONFIRMED":o.verification_status="CONFIRMED";o.verified_species=species or o.species;target="VERIFIED"
  elif value=="CORRECTED":
   if not species:raise ValueError("Corrected identity requires species")
   o.verification_status="CORRECTED";o.verified_species=species;target="CORRECTED"
  elif value=="UNRESOLVED":o.verification_status="NEEDS_MORE_REVIEW";target="AWAITING_IDENTIFICATION"
  elif value=="REJECTED":o.verification_status="REJECTED";target="REJECTED"
  elif value=="CONFIRMED_DUPLICATE":o.is_possible_duplicate=True;row.duplicate_disposition=value;target="DUPLICATE"
  elif value=="NOT_DUPLICATE":o.is_possible_duplicate=False;o.duplicate_of_observation_id=None;row.duplicate_disposition=value;target="IN_REVIEW"
  else:raise ValueError("Invalid review disposition")
  self._transition(row,target,"EXPERT_DISPOSITION",actor,reason,o,previous_identity);row.final_disposition=value if target in {"VERIFIED","CORRECTED","REJECTED","DUPLICATE"} else None;row.evidence_handoff_state="ELIGIBLE_FOR_SCIENTIFIC_EVIDENCE_REVIEW" if target in {"VERIFIED","CORRECTED"} else "NOT_EVALUATED"
  if target in {"VERIFIED","CORRECTED"}:self._notify(row,"VERIFICATION_COMPLETED",None,{"disposition":value})
  if target in {"VERIFIED","CORRECTED"} and o.jurisdiction_id is not None:
   from early_warning_operations import EarlyWarningOperations
   from models import Species
   taxon=self.session.query(Species).filter_by(scientific_name=o.verified_species).one_or_none()
   EarlyWarningOperations(self.session).emit("OBSERVATION_EXPERT_VERIFIED" if target=="VERIFIED" else "OBSERVATION_EXPERT_CORRECTED",o.jurisdiction_id,taxon.id if taxon else None,o.id,f"observation:{o.id}:verification:{o.verification_status}",{"evaluation_requested":False})
  self.session.commit();return self.payload(o,row)
 def request_information(self,id,actor,message):
  if not message or not message.strip():raise ValueError("A concise request message is required")
  o,row=self.case(id);self._transition(row,"AWAITING_REPORTER_INFORMATION","ADDITIONAL_INFORMATION_REQUESTED",actor,message.strip(),o);token,raw=ReporterAccessService(self.session).issue(o.id,"RESPONSE",row.id);self._notify(row,"ADDITIONAL_INFORMATION_REQUESTED",None,{"message":message.strip(),"public_reference":token.public_reference});self.session.commit();result=self.payload(o,row);result["reporter_response_token"]=raw;result["reporter_response_reference"]=token.public_reference;return result
 def close(self,id,actor,reason,reopen=False):
  o,row=self.case(id)
  if reopen:
   if row.workflow_state!="CLOSED":raise ValueError("Only closed cases may reopen")
   row.closed_at=None;self._transition(row,"IN_REVIEW","REOPENED",actor,reason,o)
  else:
   if not row.final_disposition:raise ValueError("Case requires an authorized final disposition")
   row.closed_at=datetime.now(timezone.utc);self._transition(row,"CLOSED","CLOSED",actor,reason,o);self._notify(row,"CASE_CLOSED",None,{"reason":reason})
  self.session.commit();return self.payload(o,row)
 def history(self,id):
  return [{"event_type":e.event_type,"previous_state":e.previous_state,"current_state":e.current_state,"reason_reference":e.reason_reference,"actor_user_id":e.actor_user_id,"actor_display_name":self.session.get(User,e.actor_user_id).display_name if e.actor_user_id and self.session.get(User,e.actor_user_id) else "System","identity_state":json.loads(e.identity_state_json),"created_at":e.created_at,"provenance_version":e.provenance_version} for e in self.session.query(ObservationOperationalEvent).filter_by(observation_id=id).order_by(ObservationOperationalEvent.created_at,ObservationOperationalEvent.id)]
 def payload(self,o,row=None):
  from early_warning_service import EarlyWarningService
  from models import AnomalyAssessment
  readiness=EarlyWarningService(self.session).readiness(o.id);assessment=self.session.query(AnomalyAssessment).filter_by(observation_id=o.id,current_state="CURRENT").order_by(AnomalyAssessment.id.desc()).first()
  identity=self.identity(o);return {"observation_id":o.id,"jurisdiction_id":o.jurisdiction_id,"submitted_at":o.created_at,"image_url":f"/admin/observations/{o.id}/image","location":{"latitude":o.latitude,"longitude":o.longitude},"reporter_suggestion":o.reporter_suggested_scientific_name,"ai_identification":{"species":o.species,"status":o.identification_status,"score":o.score,"margin":o.margin,"limitations":"AI assistance is not expert verification."},"expert_identification":{"species":o.verified_species,"status":o.verification_status},"resolved_identity":identity,"workflow_state":row.workflow_state if row else "TRIAGE_REQUIRED","triage_route":row.triage_route if row else self.triage_route(o),"operational_priority":row.operational_priority if row else "NORMAL","assigned_reviewer_user_id":row.assigned_reviewer_user_id if row else None,"duplicate":{"possible":o.is_possible_duplicate,"duplicate_of_observation_id":o.duplicate_of_observation_id,"disposition":row.duplicate_disposition if row else "POSSIBLE_DUPLICATE" if o.is_possible_duplicate else "NOT_ASSESSED"},"final_disposition":row.final_disposition if row else None,"evidence_handoff_state":row.evidence_handoff_state if row else "NOT_EVALUATED","scientific_context":{"anomaly_eligibility":readiness["handoff"],"eligibility_reasons":readiness["reasons"],"evaluation_state":"EVALUATED" if assessment else "NOT_EVALUATED","current_assessment":{"id":assessment.id,"overall_status":assessment.overall_status,"requires_review":assessment.requires_review} if assessment else None,"scientific_review_url":f"/scientific-review/early-warning/{assessment.id}" if assessment else None,"interpretation":"Descriptive context only; no anomaly or ecological-status conclusion. Operational priority is unchanged."}}
 def _transition(self,row,target,event,actor,reason,o,identity=None):
  if target not in STATES:raise ValueError("Invalid workflow state")
  previous=row.workflow_state;row.workflow_state=target;self._event(row,actor,event,previous,target,reason,identity or self.identity(o))
 def _event(self,row,actor,event,previous,current,reason,identity=None):self.session.add(ObservationOperationalEvent(case_id=row.id,observation_id=row.observation_id,actor_user_id=actor,event_type=event,previous_state=previous,current_state=current,reason_reference=reason,identity_state_json=json.dumps(identity or {},sort_keys=True),provenance_version="observation-operations-v1"))
 def _notify(self,row,event,recipient,payload):self.session.add(ObservationNotificationEvent(case_id=row.id,observation_id=row.observation_id,event_type=event,recipient_user_id=recipient,payload_json=json.dumps(payload or {},sort_keys=True),delivery_state="PENDING_DELIVERY_INTEGRATION"))
