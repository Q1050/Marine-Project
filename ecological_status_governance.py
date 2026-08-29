"""Governed jurisdiction ecological-status assertions; never occurrence inference."""
from __future__ import annotations
import enum,json
from datetime import datetime,timezone
from sqlalchemy import inspect
from jurisdiction_boundary_registry import canonical_json
from occurrence_evidence_service import _hash,_date,_name
from models import *

class EcologicalStatus(str,enum.Enum):
 PRESENT="PRESENT";NATIVE="NATIVE";NON_NATIVE="NON_NATIVE";INVASIVE="INVASIVE";ESTABLISHED="ESTABLISHED";TRANSIENT="TRANSIENT";ERADICATED="ERADICATED";UNCERTAIN="UNCERTAIN"
class EvidenceType(str,enum.Enum):
 GOVERNMENT_OR_AGENCY_LIST="GOVERNMENT_OR_AGENCY_LIST";PEER_REVIEWED_LITERATURE="PEER_REVIEWED_LITERATURE";STRUCTURED_MONITORING_PROGRAM="STRUCTURED_MONITORING_PROGRAM";MUSEUM_OR_SPECIMEN_EVIDENCE="MUSEUM_OR_SPECIMEN_EVIDENCE";EXPERT_REVIEW="EXPERT_REVIEW";OTHER_REVIEWED_SOURCE="OTHER_REVIEWED_SOURCE"
class AuthorityClassification(str,enum.Enum):
 AUTHORITATIVE_FOR_JURISDICTION="AUTHORITATIVE_FOR_JURISDICTION";SUPPORTING="SUPPORTING";CONFLICTING="CONFLICTING";INSUFFICIENT="INSUFFICIENT";REVIEW_REQUIRED="REVIEW_REQUIRED"

VALID_STATUSES={item.value for item in EcologicalStatus};VALID_EVIDENCE={item.value for item in EvidenceType};VALID_AUTHORITY={item.value for item in AuthorityClassification}
CONFLICT_PAIRS={frozenset(pair) for pair in (("NATIVE","NON_NATIVE"),("NATIVE","INVASIVE"),("ERADICATED","PRESENT"),("ERADICATED","ESTABLISHED"),("ERADICATED","INVASIVE"),("ERADICATED","TRANSIENT"))}

class EcologicalStatusGovernanceService:
 def __init__(self,session):self.session=session
 def preflight(self,payload):
  jurisdiction=self.session.get(Jurisdiction,payload.get("jurisdiction_id"));rows=[]
  if not jurisdiction:return {"write_performed":False,"rows":[],"error":"JURISDICTION_MISMATCH"}
  for index,item in enumerate(payload.get("assertions") or []):rows.append(self._preflight_row(jurisdiction,item,index))
  counts={}
  for row in rows:counts[row["classification"]]=counts.get(row["classification"],0)+1
  return {"write_performed":False,"jurisdiction_id":jurisdiction.id,"counts":counts,"rows":rows,"taxonomy_routing":"Unknown taxa must be submitted through the governed taxonomy candidate workflow."}
 def prepare(self,payload,user_id,dry_run=False):
  preflight=self.preflight(payload)
  if dry_run:return preflight
  if preflight.get("error"):raise ValueError(preflight["error"])
  self._validate_source(payload)
  manifest={key:payload.get(key) for key in ("jurisdiction_id","source_organization","source_title","source_version","publication_date","source_reference","evidence_type","authority_classification","geographic_scope","limitations","assertions")};fingerprint=_hash(manifest)
  existing=self.session.query(EcologicalStatusPreparation).filter_by(dependency_fingerprint=fingerprint).one_or_none()
  if existing:return self.detail(existing.id)|{"rerun_status":"NO-OP"}
  row=EcologicalStatusPreparation(jurisdiction_id=payload["jurisdiction_id"],source_organization=payload["source_organization"],source_title=payload["source_title"],source_version=payload.get("source_version"),publication_date=_date(payload.get("publication_date")),source_reference=payload["source_reference"],evidence_type=payload["evidence_type"],authority_classification=payload["authority_classification"],geographic_scope_json=canonical_json(payload.get("geographic_scope") or {"type":"JURISDICTION","jurisdiction_id":payload["jurisdiction_id"]}),limitations_json=canonical_json(payload.get("limitations") or []),manifest_json=canonical_json(manifest),dependency_fingerprint=fingerprint,workflow_status="READY_FOR_REVIEW",prepared_by_user_id=user_id);self.session.add(row);self.session.flush()
  for source,checked in zip(payload.get("assertions") or [],preflight["rows"]):
   self.session.add(EcologicalStatusCandidate(preparation_id=row.id,submitted_scientific_name=source["scientific_name"],submitted_identifier_scheme=source.get("authoritative_identifier_scheme"),submitted_identifier=source.get("authoritative_identifier"),reconciled_taxon_id=checked.get("taxon_id"),taxonomy_reconciliation=checked["taxonomy_reconciliation"],asserted_statuses_json=canonical_json(sorted(set(source.get("statuses") or []))),effective_from=_date(source.get("effective_from")),effective_to=_date(source.get("effective_to")),source_note=source.get("notes"),preflight_classification=checked["classification"],candidate_fingerprint=_hash({"preparation":fingerprint,"row":source}),review_status="REVIEW_REQUIRED"))
  self.session.commit();return self.detail(row.id)
 def approve(self,preparation_id,candidate_ids,user_id,reference):
  row=self._preparation(preparation_id);self._current(row);candidates=self._candidates(row.id,candidate_ids)
  if row.authority_classification!="AUTHORITATIVE_FOR_JURISDICTION":raise ValueError("Source is not approved as authoritative for this jurisdiction")
  for item in candidates:
   if item.preflight_classification not in {"READY","CONFLICT_WITH_EXISTING_STATUS"}:raise ValueError(f"Candidate {item.id} is not approvable: {item.preflight_classification}")
   item.review_status="APPROVED";item.reviewer_user_id=user_id;item.review_reference=reference;item.reviewed_at=datetime.now(timezone.utc)
  row.workflow_status="APPROVED";row.reviewed_by_user_id=user_id;row.review_reference=reference;row.reviewed_at=datetime.now(timezone.utc);row.approved_dependency_fingerprint=row.dependency_fingerprint;self.session.commit();return self.detail(row.id)
 def dispose(self,preparation_id,candidate_ids,status,user_id,reference):
  if status not in {"REJECTED","UNRESOLVED"}:raise ValueError("Unsupported review disposition")
  row=self._preparation(preparation_id);self._current(row)
  for item in self._candidates(row.id,candidate_ids):item.review_status=status;item.reviewer_user_id=user_id;item.review_reference=reference;item.reviewed_at=datetime.now(timezone.utc)
  self.session.commit();return self.detail(row.id)
 def apply(self,preparation_id):
  row=self._preparation(preparation_id)
  if row.workflow_status=="APPLIED":return self.detail(row.id)|{"apply_status":"NO-OP"}
  if row.workflow_status!="APPROVED" or row.approved_dependency_fingerprint!=row.dependency_fingerprint:raise ValueError("Preparation approval is stale or absent")
  approved=self.session.query(EcologicalStatusCandidate).filter_by(preparation_id=row.id,review_status="APPROVED").all()
  if not approved:raise ValueError("No ecological-status candidates are approved")
  before=self._firewall_counts();created=[]
  for candidate in approved:
   for status in json.loads(candidate.asserted_statuses_json):
    provenance={"preparation_id":row.id,"candidate_id":candidate.id,"dependency_fingerprint":row.dependency_fingerprint,"source_reference":row.source_reference,"status":status};fingerprint=_hash(provenance);assertion=self.session.query(EcologicalStatusAssertion).filter_by(provenance_fingerprint=fingerprint).one_or_none()
    if not assertion:
     assertion=EcologicalStatusAssertion(preparation_id=row.id,candidate_id=candidate.id,jurisdiction_id=row.jurisdiction_id,taxon_id=candidate.reconciled_taxon_id,asserted_status=status,source_organization=row.source_organization,source_title=row.source_title,source_version=row.source_version,publication_date=row.publication_date,source_reference=row.source_reference,evidence_type=row.evidence_type,authority_classification=row.authority_classification,geographic_scope_json=row.geographic_scope_json,effective_from=candidate.effective_from,effective_to=candidate.effective_to,review_status="APPROVED",reviewer_user_id=candidate.reviewer_user_id,review_reference=candidate.review_reference,reviewed_at=candidate.reviewed_at,limitations_json=row.limitations_json,supporting_occurrence_evidence_ids_json="[]",provenance_json=canonical_json(provenance),provenance_fingerprint=fingerprint,lifecycle_state="CURRENT");self.session.add(assertion);self.session.flush()
    created.append(assertion.id)
  for taxon_id in sorted({candidate.reconciled_taxon_id for candidate in approved}):self.materialize_projection(row.jurisdiction_id,taxon_id)
  after=self._firewall_counts();changes={key:after[key]-before[key] for key in before}
  if any(changes.values()):raise ValueError("Scientific firewall violation")
  row.workflow_status="APPLIED";row.applied_at=datetime.now(timezone.utc);self.session.commit();return self.detail(row.id)|{"apply_status":"APPLIED","assertion_ids":created,"firewall":{"status":"PASS","changes":changes,"statement":"ECOLOGICAL STATUS ASSERTION DOES NOT ACTIVATE MODELS OR ANOMALIES"}}
 def projection(self,jurisdiction_id,taxon_id,at=None):
  at=at or datetime.now(timezone.utc).replace(tzinfo=None);rows=self.session.query(EcologicalStatusAssertion).filter_by(jurisdiction_id=jurisdiction_id,taxon_id=taxon_id,review_status="APPROVED",authority_classification="AUTHORITATIVE_FOR_JURISDICTION",lifecycle_state="CURRENT").order_by(EcologicalStatusAssertion.id).all();rows=[row for row in rows if (not row.effective_from or row.effective_from<=at) and (not row.effective_to or row.effective_to>=at)];statuses=sorted({row.asserted_status for row in rows});conflicts=sorted([sorted(pair) for pair in CONFLICT_PAIRS if pair.issubset(statuses)]);state="REVIEW_REQUIRED_CONFLICT" if conflicts else "CURRENT_APPROVED" if statuses else "REVIEW_REQUIRED";return {"jurisdiction_id":jurisdiction_id,"taxon_id":taxon_id,"projection_state":state,"statuses":statuses,"assertion_ids":[row.id for row in rows],"conflicts":conflicts,"numeric_confidence":None}
 def materialize_projection(self,jurisdiction_id,taxon_id):
  value=self.projection(jurisdiction_id,taxon_id);row=self.session.query(SpeciesJurisdictionStatus).filter_by(jurisdiction_id=jurisdiction_id,species_id=taxon_id).one_or_none()
  if value["projection_state"]!="CURRENT_APPROVED":
   if row:
    row.status_set_json=canonical_json(value["statuses"]);row.projection_state=value["projection_state"];row.projection_fingerprint=_hash(value);row.source_assertion_ids_json=canonical_json(value["assertion_ids"]);row.source="GOVERNED_ASSERTION_PROJECTION";row.last_reviewed_at=None;row.updated_at=datetime.now(timezone.utc)
   return value
  primary="INVASIVE" if "INVASIVE" in value["statuses"] else value["statuses"][0];fingerprint=_hash(value)
  if not row:row=SpeciesJurisdictionStatus(jurisdiction_id=jurisdiction_id,species_id=taxon_id,ecological_status=primary,source="GOVERNED_ASSERTION_PROJECTION");self.session.add(row)
  row.ecological_status=primary;row.status_set_json=canonical_json(value["statuses"]);row.projection_state=value["projection_state"];row.projection_fingerprint=fingerprint;row.source_assertion_ids_json=canonical_json(value["assertion_ids"]);row.source="GOVERNED_ASSERTION_PROJECTION";row.last_reviewed_at=datetime.now(timezone.utc);row.updated_at=datetime.now(timezone.utc);return value
 def supersede(self,assertion_id,replacement_id):
  old=self.session.get(EcologicalStatusAssertion,assertion_id);new=self.session.get(EcologicalStatusAssertion,replacement_id)
  if not old or not new or (old.jurisdiction_id,old.taxon_id)!=(new.jurisdiction_id,new.taxon_id):raise ValueError("Assertions are not supersession-compatible")
  old.lifecycle_state="SUPERSEDED";old.superseded_at=datetime.now(timezone.utc);self.materialize_projection(old.jurisdiction_id,old.taxon_id);self.session.commit()
 def history(self,jurisdiction_id,taxon_id):return [self._assertion_payload(row) for row in self.session.query(EcologicalStatusAssertion).filter_by(jurisdiction_id=jurisdiction_id,taxon_id=taxon_id).order_by(EcologicalStatusAssertion.id).all()]
 def detail(self,id):
  row=self._preparation(id);candidates=self._candidates(row.id);return {"id":row.id,"jurisdiction_id":row.jurisdiction_id,"source":{"organization":row.source_organization,"title":row.source_title,"version":row.source_version,"reference":row.source_reference,"evidence_type":row.evidence_type,"authority_classification":row.authority_classification},"workflow_status":row.workflow_status,"dependency_fingerprint":row.dependency_fingerprint,"candidates":[{"id":item.id,"scientific_name":item.submitted_scientific_name,"taxon_id":item.reconciled_taxon_id,"taxonomy_reconciliation":item.taxonomy_reconciliation,"statuses":json.loads(item.asserted_statuses_json),"preflight_classification":item.preflight_classification,"review_status":item.review_status,"effective_from":item.effective_from,"effective_to":item.effective_to} for item in candidates],"limitations":json.loads(row.limitations_json),"applied_at":row.applied_at}
 def _preflight_row(self,jurisdiction,item,index):
  statuses=set(item.get("statuses") or []);classification=None
  if not statuses or not statuses.issubset(VALID_STATUSES):classification="INVALID_STATUS"
  taxon=self._taxon(item);taxonomy="EXACT_ACCEPTED_TAXON" if taxon else "UNRESOLVED"
  governed=taxon and self.session.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id,taxon_id=taxon.id,review_status="APPROVED").first()
  if not classification and not taxon:classification="TAXON_NOT_GOVERNED"
  elif not classification and not governed:classification="TAXON_NOT_GOVERNED"
  existing=self.projection(jurisdiction.id,taxon.id) if taxon else None
  if not classification and existing["statuses"] and statuses==set(existing["statuses"]):classification="DUPLICATE_ASSERTION"
  elif not classification and any(pair.issubset(statuses|set(existing["statuses"])) for pair in CONFLICT_PAIRS):classification="CONFLICT_WITH_EXISTING_STATUS"
  elif not classification:classification="READY"
  return {"row_index":index,"scientific_name":item.get("scientific_name"),"taxon_id":taxon.id if taxon else None,"taxonomy_reconciliation":taxonomy,"statuses":sorted(statuses),"classification":classification,"taxonomy_routing":"GOVERNED_TAXONOMY_CANDIDATE_WORKFLOW" if not taxon else None}
 def _taxon(self,item):
  scheme=item.get("authoritative_identifier_scheme");identifier=item.get("authoritative_identifier")
  if scheme and identifier:
   row=self.session.query(Species).filter_by(authoritative_identifier_scheme=scheme,authoritative_identifier=str(identifier)).one_or_none()
   if row:return row.accepted_taxon or row
  return self.session.query(Species).filter(Species.scientific_name.ilike(str(item.get("scientific_name") or "").strip())).one_or_none()
 def _validate_source(self,payload):
  if payload.get("evidence_type") not in VALID_EVIDENCE:raise ValueError("Invalid ecological evidence type")
  if payload.get("authority_classification") not in VALID_AUTHORITY:raise ValueError("Invalid source authority classification")
  for field in ("source_organization","source_title","source_reference"):
   if not payload.get(field):raise ValueError(f"{field} is required")
 def _current(self,row):
  if row.workflow_status in {"STALE","SUPERSEDED","APPLIED"}:raise ValueError("Preparation is not reviewable")
  if _hash({key:json.loads(row.manifest_json).get(key) for key in json.loads(row.manifest_json)})!=row.dependency_fingerprint:raise ValueError("Preparation dependency is stale")
 def _preparation(self,id):
  row=self.session.get(EcologicalStatusPreparation,id)
  if not row:raise ValueError("Ecological-status preparation does not exist")
  return row
 def _candidates(self,id,ids=None):
  q=self.session.query(EcologicalStatusCandidate).filter_by(preparation_id=id)
  if ids is not None:q=q.filter(EcologicalStatusCandidate.id.in_(ids))
  rows=q.order_by(EcologicalStatusCandidate.id).all()
  if ids is not None and len(rows)!=len(set(ids)):raise ValueError("Candidate selection is invalid")
  return rows
 def _assertion_payload(self,row):return {"id":row.id,"jurisdiction_id":row.jurisdiction_id,"taxon_id":row.taxon_id,"asserted_status":row.asserted_status,"source_organization":row.source_organization,"source_title":row.source_title,"source_reference":row.source_reference,"evidence_type":row.evidence_type,"authority_classification":row.authority_classification,"effective_from":row.effective_from,"effective_to":row.effective_to,"review_status":row.review_status,"lifecycle_state":row.lifecycle_state,"limitations":json.loads(row.limitations_json),"provenance_fingerprint":row.provenance_fingerprint}
 def _firewall_counts(self):
  # Inspect through the Session-owned transactional connection. Inspecting the
  # Engine here can check out (and then roll back) the same physical connection
  # used by an in-memory SQLite SingletonThreadPool, discarding assertions that
  # were flushed earlier in this transaction.
  tables=set(inspect(self.session.connection()).get_table_names())
  return {model.__tablename__:self.session.query(model).count() for model in (SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal) if model.__tablename__ in tables}
