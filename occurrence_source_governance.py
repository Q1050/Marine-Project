"""Durable governance for provider-neutral occurrence acquisition sources."""
import hashlib,json
from datetime import datetime,timezone
from jurisdiction_boundary_registry import canonical_json
from models import OccurrenceSourceRegistration

def source_configuration(payload):
 return {key:payload.get(key) for key in ("source_registration_id","source_name","scientific_provider","transport_interface","provider_dataset_id","provider_dataset_version","acquisition_mechanism","documentation_reference","license","reuse_conditions","geographic_scope","taxonomic_scope","source_provenance","limitations","configuration","configuration_version")}
def source_fingerprint(payload):return hashlib.sha256(canonical_json(source_configuration(payload)).encode()).hexdigest()
def row_fingerprint(row):return source_fingerprint({"source_registration_id":row.source_registration_id,"source_name":row.source_name,"scientific_provider":row.scientific_provider,"transport_interface":row.transport_interface,"provider_dataset_id":row.provider_dataset_id,"provider_dataset_version":row.provider_dataset_version,"acquisition_mechanism":row.acquisition_mechanism,"documentation_reference":row.documentation_reference,"license":row.license,"reuse_conditions":row.reuse_conditions,"geographic_scope":json.loads(row.geographic_scope_json),"taxonomic_scope":json.loads(row.taxonomic_scope_json),"source_provenance":json.loads(row.source_provenance_json),"limitations":json.loads(row.limitations_json),"configuration":json.loads(row.configuration_json),"configuration_version":row.configuration_version})

class OccurrenceSourceGovernanceService:
 def __init__(self,session):self.session=session
 def register(self,payload,user_id):
  fingerprint=source_fingerprint(payload);existing=self.session.query(OccurrenceSourceRegistration).filter_by(configuration_fingerprint=fingerprint).one_or_none()
  if existing:return existing
  active=self.session.query(OccurrenceSourceRegistration).filter_by(source_registration_id=payload["source_registration_id"],workflow_status="ACTIVE").one_or_none()
  row=OccurrenceSourceRegistration(source_registration_id=payload["source_registration_id"],source_name=payload["source_name"],scientific_provider=payload["scientific_provider"],transport_interface=payload.get("transport_interface"),provider_dataset_id=payload.get("provider_dataset_id"),provider_dataset_version=payload.get("provider_dataset_version"),acquisition_mechanism=payload["acquisition_mechanism"],documentation_reference=payload["documentation_reference"],license=payload["license"],reuse_conditions=payload["reuse_conditions"],geographic_scope_json=canonical_json(payload.get("geographic_scope") or {}),taxonomic_scope_json=canonical_json(payload.get("taxonomic_scope") or {}),source_provenance_json=canonical_json(payload.get("source_provenance") or {}),limitations_json=canonical_json(payload.get("limitations") or []),configuration_json=canonical_json(payload.get("configuration") or {}),configuration_version=payload["configuration_version"],configuration_fingerprint=fingerprint,workflow_status="READY_FOR_REVIEW",created_by_user_id=user_id,predecessor_id=active.id if active else None);self.session.add(row);self.session.commit();return row
 def approve(self,row,user_id,reference):
  if row_fingerprint(row)!=row.configuration_fingerprint:raise ValueError("Source configuration changed; create a new reviewed version")
  if row.workflow_status=="APPROVED" and row.approved_configuration_fingerprint==row.configuration_fingerprint:return row
  if row.workflow_status!="READY_FOR_REVIEW":raise ValueError("Source is not ready for review")
  row.workflow_status="APPROVED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;row.approved_configuration_fingerprint=row.configuration_fingerprint;self.session.commit();return row
 def activate(self,row):
  if row.workflow_status=="ACTIVE":return row
  if row.workflow_status!="APPROVED" or row.approved_configuration_fingerprint!=row.configuration_fingerprint or row_fingerprint(row)!=row.configuration_fingerprint:raise ValueError("Source approval is stale or absent")
  active=self.session.query(OccurrenceSourceRegistration).filter_by(source_registration_id=row.source_registration_id,workflow_status="ACTIVE").all()
  now=datetime.now(timezone.utc)
  for prior in active:prior.workflow_status="SUPERSEDED";prior.superseded_at=now
  row.workflow_status="ACTIVE";row.activated_at=now;self.session.commit();return row
 def reject(self,row,user_id,reference):
  if row.workflow_status!="READY_FOR_REVIEW":raise ValueError("Source is not rejectable")
  row.workflow_status="REJECTED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;self.session.commit();return row
 def deactivate(self,row):
  if row.workflow_status!="ACTIVE":raise ValueError("Only ACTIVE sources may be deactivated")
  row.workflow_status="DEACTIVATED";row.deactivated_at=datetime.now(timezone.utc);self.session.commit();return row
 def payload(self,row):return {"id":row.id,"source_registration_id":row.source_registration_id,"source_name":row.source_name,"scientific_provider":row.scientific_provider,"transport_interface":row.transport_interface,"provider_dataset_id":row.provider_dataset_id,"provider_dataset_version":row.provider_dataset_version,"acquisition_mechanism":row.acquisition_mechanism,"documentation_reference":row.documentation_reference,"license":row.license,"reuse_conditions":row.reuse_conditions,"geographic_scope":json.loads(row.geographic_scope_json),"taxonomic_scope":json.loads(row.taxonomic_scope_json),"source_provenance":json.loads(row.source_provenance_json),"limitations":json.loads(row.limitations_json),"configuration":json.loads(row.configuration_json),"configuration_version":row.configuration_version,"configuration_fingerprint":row.configuration_fingerprint,"workflow_status":row.workflow_status,"approval_reference":row.approval_reference,"activated_at":row.activated_at,"predecessor_id":row.predecessor_id}
