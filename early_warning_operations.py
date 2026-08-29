"""Scientific reviewer, configuration, assignment, and controlled-event operations."""
from datetime import datetime,timezone
import hashlib,json
from sqlalchemy.exc import IntegrityError
from anomaly_repository import canonical_json
from early_warning_service import EarlyWarningService,RULE_VERSION
from models import AnomalyAssessment,AnomalyConfiguration,AnomalyReviewAssignment,ScientificDomainEvent,ScientificReviewerGrant

EVENT_TYPES={"OBSERVATION_EXPERT_VERIFIED","OBSERVATION_EXPERT_CORRECTED","GOVERNED_OCCURRENCE_BASELINE_CHANGED","SUITABILITY_DEPLOYMENT_CHANGED","ANOMALY_CONFIGURATION_CHANGED"}
class EarlyWarningOperations:
 def __init__(self,s):self.s=s
 def _validate_rules(self,values):
  mode=values.get("mode","DESCRIPTIVE_ONLY")
  for key in ("spatial_rule_json","temporal_rule_json"):
   raw=values.get(key)
   if not raw:continue
   rule=json.loads(raw) if isinstance(raw,str) else raw
   if mode=="DESCRIPTIVE_ONLY":raise ValueError("Reviewed trigger rules require a rule-based configuration mode")
   if not rule.get("rule_id") or not rule.get("rule_version"):raise ValueError("Reviewed rules require rule_id and rule_version metadata")
  limitations=values.get("limitations_json","[]");limitations=json.loads(limitations) if isinstance(limitations,str) else limitations
  if (values.get("spatial_rule_json") or values.get("temporal_rule_json")) and not limitations:raise ValueError("Reviewed trigger rules require explicit limitations")
 def grant(self,user_id,jurisdiction_id,actor_id,reference):
  row=self.s.query(ScientificReviewerGrant).filter_by(user_id=user_id,jurisdiction_id=jurisdiction_id).one_or_none()
  if row:row.status="ACTIVE";row.revoked_at=None;row.revoked_by_user_id=None;row.grant_reference=reference
  else:row=ScientificReviewerGrant(user_id=user_id,jurisdiction_id=jurisdiction_id,granted_by_user_id=actor_id,grant_reference=reference);self.s.add(row)
  self.s.flush();return row
 def revoke(self,row,actor_id):row.status="REVOKED";row.revoked_by_user_id=actor_id;row.revoked_at=datetime.now(timezone.utc);self.s.flush();return row
 def config_draft(self,values):
  values={**values,"mode":values.get("mode","DESCRIPTIVE_ONLY"),"review_status":"DRAFT","automatic_evaluation_enabled":False}
  self._validate_rules(values)
  fingerprint=hashlib.sha256(canonical_json({k:v for k,v in values.items() if k not in {"reviewed_by_user_id","review_reference"}}).encode()).hexdigest();row=AnomalyConfiguration(**values,dependency_fingerprint=fingerprint);self.s.add(row);self.s.flush();return row
 def update_draft(self,row,values):
  if row.review_status!="DRAFT":raise ValueError("Only DRAFT configurations may be edited; create a replacement version instead.")
  self._validate_rules(values)
  for key,value in values.items():
   if key not in {"jurisdiction_id","taxon_id","configuration_version","review_status","reviewed_by_user_id","review_reference","reviewed_at","activated_at","deactivated_at","superseded_at","supersedes_configuration_id","dependency_fingerprint"}:setattr(row,key,value)
  fingerprint_values={column.name:getattr(row,column.name) for column in row.__table__.columns if column.name not in {"id","created_at","reviewed_by_user_id","review_reference","reviewed_at","dependency_fingerprint"}}
  row.dependency_fingerprint=hashlib.sha256(canonical_json(fingerprint_values).encode()).hexdigest();self.s.flush();return row
 def transition_config(self,row,target,actor_id=None,reference=None):
  allowed={"DRAFT":{"READY_FOR_REVIEW"},"READY_FOR_REVIEW":{"APPROVED","REJECTED"},"APPROVED":{"ACTIVE"},"ACTIVE":{"DEACTIVATED","SUPERSEDED"}}
  if target not in allowed.get(row.review_status,set()):raise ValueError(f"Invalid configuration transition: {row.review_status} -> {target}")
  row.review_status=target
  if target in {"APPROVED","REJECTED"}:row.reviewed_by_user_id=actor_id;row.review_reference=reference;row.reviewed_at=datetime.now(timezone.utc)
  if target=="ACTIVE":
   previous=self.s.query(AnomalyConfiguration).filter_by(jurisdiction_id=row.jurisdiction_id,taxon_id=row.taxon_id,review_status="ACTIVE").filter(AnomalyConfiguration.id!=row.id).all()
   for prior in previous:prior.review_status="SUPERSEDED";prior.deactivated_at=datetime.now(timezone.utc);prior.superseded_at=datetime.now(timezone.utc);row.supersedes_configuration_id=prior.id
   row.activated_at=datetime.now(timezone.utc);self.invalidate(row.jurisdiction_id,row.taxon_id,"configuration activated");self.emit("ANOMALY_CONFIGURATION_CHANGED",row.jurisdiction_id,row.taxon_id,dependency_reference=f"configuration:{row.id}:{row.dependency_fingerprint}",payload={"configuration_id":row.id,"configuration_version":row.configuration_version,"state":"ACTIVE"})
  if target in {"DEACTIVATED","SUPERSEDED"}:
   row.deactivated_at=datetime.now(timezone.utc);row.superseded_at=datetime.now(timezone.utc) if target=="SUPERSEDED" else row.superseded_at
   self.invalidate(row.jurisdiction_id,row.taxon_id,"configuration inactive");self.emit("ANOMALY_CONFIGURATION_CHANGED",row.jurisdiction_id,row.taxon_id,dependency_reference=f"configuration:{row.id}:{row.dependency_fingerprint}:{target}",payload={"configuration_id":row.id,"configuration_version":row.configuration_version,"state":target})
  self.s.flush();return row
 def claim(self,assessment,reviewer_id,actor_id,reason):
  current=self.s.query(AnomalyReviewAssignment).filter_by(anomaly_assessment_id=assessment.id,status="ASSIGNED").one_or_none()
  if current:
   if current.reviewer_user_id==reviewer_id:return current
   raise ValueError("Assessment is already assigned")
  row=AnomalyReviewAssignment(anomaly_assessment_id=assessment.id,jurisdiction_id=assessment.jurisdiction_id,reviewer_user_id=reviewer_id,assigned_by_user_id=actor_id,reason=reason);self.s.add(row)
  try:self.s.flush()
  except IntegrityError as exc:self.s.rollback();raise ValueError("Assessment is already assigned") from exc
  return row
 def reassign(self,assessment,reviewer_id,actor_id,reason):
  current=self.s.query(AnomalyReviewAssignment).filter_by(anomaly_assessment_id=assessment.id,status="ASSIGNED").one_or_none()
  if current and current.reviewer_user_id==reviewer_id:return current
  if current:current.status="UNASSIGNED";current.unassigned_at=datetime.now(timezone.utc);self.s.flush()
  row=AnomalyReviewAssignment(anomaly_assessment_id=assessment.id,jurisdiction_id=assessment.jurisdiction_id,reviewer_user_id=reviewer_id,assigned_by_user_id=actor_id,reason=reason);self.s.add(row)
  try:self.s.flush()
  except IntegrityError as exc:self.s.rollback();raise ValueError("Assessment assignment changed; refresh before retrying") from exc
  return row
 def emit(self,event_type,jurisdiction_id,taxon_id=None,observation_id=None,dependency_reference=None,payload=None):
  if event_type not in EVENT_TYPES:raise ValueError("Unsupported scientific event type")
  identity={"event_type":event_type,"jurisdiction_id":jurisdiction_id,"taxon_id":taxon_id,"observation_id":observation_id,"dependency_reference":dependency_reference};fp=hashlib.sha256(canonical_json(identity).encode()).hexdigest();row=self.s.query(ScientificDomainEvent).filter_by(event_fingerprint=fp).one_or_none()
  if row:return row
  row=ScientificDomainEvent(**identity,event_fingerprint=fp,payload_json=canonical_json(payload or {}));self.s.add(row);self.s.flush();return row
 def process(self,row):
  row.processing_state="PROCESSING";row.attempts+=1;row.last_attempted_at=datetime.now(timezone.utc)
  try:
   if row.event_type in {"GOVERNED_OCCURRENCE_BASELINE_CHANGED","SUITABILITY_DEPLOYMENT_CHANGED","ANOMALY_CONFIGURATION_CHANGED"}:self.invalidate(row.jurisdiction_id,row.taxon_id,row.event_type);row.processing_state="PROCESSED"
   elif row.observation_id:
    config=self.s.query(AnomalyConfiguration).filter_by(jurisdiction_id=row.jurisdiction_id,taxon_id=row.taxon_id,review_status="ACTIVE",automatic_evaluation_enabled=True).first()
    if not config:row.processing_state="SKIPPED";row.last_error="Automatic anomaly evaluation is disabled."
    else:EarlyWarningService(self.s).evaluate(row.observation_id);row.processing_state="PROCESSED"
   else:row.processing_state="SKIPPED";row.last_error="No observation was supplied."
   row.processed_at=datetime.now(timezone.utc)
  except Exception as exc:row.processing_state="RETRYABLE";row.last_error=str(exc)
  self.s.flush();return row
 def invalidate(self,jurisdiction_id,taxon_id,reason):
  rows=self.s.query(AnomalyAssessment).filter_by(jurisdiction_id=jurisdiction_id,current_state="CURRENT").all();count=0
  for row in rows:
   if taxon_id:
    from models import Species
    taxon=self.s.get(Species,taxon_id)
    if not taxon or row.evaluated_species!=taxon.scientific_name:continue
   from anomaly_repository import AnomalyRepository
   AnomalyRepository(self.s).mark_assessment_stale(row);count+=1
  return count
