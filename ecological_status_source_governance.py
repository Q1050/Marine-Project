"""Lifecycle governance for ecological-status claim sources."""
import json
from datetime import datetime,timezone
from jurisdiction_boundary_registry import canonical_json
from occurrence_evidence_service import _hash,_date
from models import EcologicalStatusSourceRegistration

SCOPES={"JURISDICTION_SPECIFIC","REGIONAL","GLOBAL","OTHER"}
def configuration(payload):
 value={key:payload.get(key) for key in ("source_registration_id","source_organization","source_title","source_type","scope_type","jurisdiction_id","region_id","source_version","publication_date","source_reference","documentation_reference","license","reuse_terms","acquisition_method","expected_semantics","field_mapping","semantic_mapping","provenance","limitations","configuration_version")}
 value["publication_date"]=_date(value.get("publication_date")).date().isoformat() if value.get("publication_date") else None
 return value
def fingerprint(payload):return _hash(configuration(payload))
def row_fingerprint(row):return fingerprint({"source_registration_id":row.source_registration_id,"source_organization":row.source_organization,"source_title":row.source_title,"source_type":row.source_type,"scope_type":row.scope_type,"jurisdiction_id":row.jurisdiction_id,"region_id":row.region_id,"source_version":row.source_version,"publication_date":row.publication_date,"source_reference":row.source_reference,"documentation_reference":row.documentation_reference,"license":row.license,"reuse_terms":row.reuse_terms,"acquisition_method":row.acquisition_method,"expected_semantics":json.loads(row.expected_semantics_json),"field_mapping":json.loads(row.field_mapping_json),"semantic_mapping":json.loads(row.semantic_mapping_json),"provenance":json.loads(row.provenance_json),"limitations":json.loads(row.limitations_json),"configuration_version":row.configuration_version})
class EcologicalStatusSourceGovernanceService:
 def __init__(self,session):self.session=session
 def register(self,payload,user_id):
  if payload.get("scope_type") not in SCOPES:raise ValueError("Invalid ecological source scope")
  if payload["scope_type"]=="JURISDICTION_SPECIFIC" and not payload.get("jurisdiction_id"):raise ValueError("Jurisdiction-specific source requires jurisdiction_id")
  value=fingerprint(payload);existing=self.session.query(EcologicalStatusSourceRegistration).filter_by(configuration_fingerprint=value).one_or_none()
  if existing:return existing
  prior=self.session.query(EcologicalStatusSourceRegistration).filter_by(source_registration_id=payload["source_registration_id"],workflow_status="ACTIVE").one_or_none();row=EcologicalStatusSourceRegistration(source_registration_id=payload["source_registration_id"],source_organization=payload["source_organization"],source_title=payload["source_title"],source_type=payload["source_type"],scope_type=payload["scope_type"],jurisdiction_id=payload.get("jurisdiction_id"),region_id=payload.get("region_id"),source_version=payload.get("source_version"),publication_date=_date(payload.get("publication_date")),source_reference=payload["source_reference"],documentation_reference=payload.get("documentation_reference"),license=payload["license"],reuse_terms=payload["reuse_terms"],acquisition_method=payload["acquisition_method"],expected_semantics_json=canonical_json(payload.get("expected_semantics") or {}),field_mapping_json=canonical_json(payload.get("field_mapping") or {}),semantic_mapping_json=canonical_json(payload.get("semantic_mapping") or {}),provenance_json=canonical_json(payload.get("provenance") or {}),limitations_json=canonical_json(payload.get("limitations") or []),configuration_version=payload["configuration_version"],configuration_fingerprint=value,workflow_status="READY_FOR_REVIEW",created_by_user_id=user_id,predecessor_id=prior.id if prior else None);self.session.add(row);self.session.commit();return row
 def approve(self,row,user_id,reference):
  if row.workflow_status!="READY_FOR_REVIEW" or row_fingerprint(row)!=row.configuration_fingerprint:raise ValueError("Source is not reviewable or configuration changed")
  row.workflow_status="APPROVED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;row.approved_configuration_fingerprint=row.configuration_fingerprint;self.session.commit();return row
 def activate(self,row):
  if row.workflow_status=="ACTIVE":return row
  if row.workflow_status!="APPROVED" or row.approved_configuration_fingerprint!=row.configuration_fingerprint or row_fingerprint(row)!=row.configuration_fingerprint:raise ValueError("Source approval is stale or absent")
  now=datetime.now(timezone.utc)
  for prior in self.session.query(EcologicalStatusSourceRegistration).filter_by(source_registration_id=row.source_registration_id,workflow_status="ACTIVE"):prior.workflow_status="SUPERSEDED";prior.superseded_at=now
  row.workflow_status="ACTIVE";row.activated_at=now;self.session.commit();return row
 def reject(self,row,user_id,reference):
  if row.workflow_status!="READY_FOR_REVIEW":raise ValueError("Source is not rejectable")
  row.workflow_status="REJECTED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;self.session.commit();return row
 def deactivate(self,row):
  if row.workflow_status!="ACTIVE":raise ValueError("Only ACTIVE sources may be deactivated")
  row.workflow_status="DEACTIVATED";row.deactivated_at=datetime.now(timezone.utc);self.session.commit();return row
 def payload(self,row):return {"id":row.id,"source_registration_id":row.source_registration_id,"source_organization":row.source_organization,"source_title":row.source_title,"source_type":row.source_type,"scope_type":row.scope_type,"jurisdiction_id":row.jurisdiction_id,"region_id":row.region_id,"source_version":row.source_version,"publication_date":row.publication_date,"source_reference":row.source_reference,"documentation_reference":row.documentation_reference,"license":row.license,"reuse_terms":row.reuse_terms,"acquisition_method":row.acquisition_method,"expected_semantics":json.loads(row.expected_semantics_json),"field_mapping":json.loads(row.field_mapping_json),"semantic_mapping":json.loads(row.semantic_mapping_json),"limitations":json.loads(row.limitations_json),"configuration_version":row.configuration_version,"configuration_fingerprint":row.configuration_fingerprint,"workflow_status":row.workflow_status,"approval_reference":row.approval_reference,"activated_at":row.activated_at,"predecessor_id":row.predecessor_id}
