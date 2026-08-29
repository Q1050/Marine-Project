"""Generic, governed review of occurrence candidates; no ecological inference."""
from datetime import datetime,timezone
import json
from jurisdiction_boundary_registry import canonical_json
from occurrence_evidence_service import _hash
from models import (HistoricalOccurrence,OccurrenceAcquisitionPreparation,
                    OccurrenceCandidateRecord,OccurrenceCandidateReview,
                    OccurrenceLegacyLink,OccurrenceSourceRegistration)

DISPOSITIONS={"APPROVED_AS_NEW_EVIDENCE","REJECTED_OUTSIDE_JURISDICTION","REJECTED_TAXONOMIC_MISMATCH","REJECTED_DUPLICATE","KNOWN_LEGACY_OVERLAP","REVIEW_REQUIRED","UNRESOLVED","FAILED"}
APPROVABLE_TAXONOMY={"EXACT_ACCEPTED_TAXON","SYNONYM_TO_ACCEPTED_TAXON"}

class OccurrenceCandidateReviewService:
 def __init__(self,session):self.session=session
 def initialize(self,preparation_id,user_id):
  preparation=self._preparation(preparation_id)
  for candidate in self._candidates(preparation_id):
   self._link_legacy(preparation,candidate)
   if self.latest(candidate.id):continue
   if candidate.boundary_reconciliation!="INSIDE_OR_ON_BOUNDARY":disposition,reason="REJECTED_OUTSIDE_JURISDICTION","OUTSIDE_GOVERNED_BOUNDARY"
   elif candidate.taxonomy_reconciliation not in APPROVABLE_TAXONOMY:disposition,reason="REJECTED_TAXONOMIC_MISMATCH","TAXONOMY_NOT_ACCEPTABLE"
   elif candidate.overlap_classification=="VERIFIED_OVERLAP":disposition,reason="KNOWN_LEGACY_OVERLAP","IDENTICAL_AUTHORITATIVE_OR_UPSTREAM_IDENTIFIER"
   else:disposition,reason="REVIEW_REQUIRED","SCIENTIFIC_REVIEW_REQUIRED"
   self._append(preparation,candidate,disposition,reason,"Deterministic initial disposition.",user_id)
  self.session.commit();return self.report(preparation_id)
 def eligibility(self,candidate):
  preparation=self._preparation(candidate.preparation_id);reasons=[];metadata=json.loads(candidate.source_metadata_json or "{}")
  source=self.session.get(OccurrenceSourceRegistration,preparation.source_registration_id) if preparation.source_registration_id else None
  if preparation.workflow_status in {"STALE","FAILED","APPLIED"}:reasons.append("PREPARATION_NOT_REVIEWABLE")
  if not source or source.workflow_status!="ACTIVE":reasons.append("SOURCE_NOT_ACTIVE")
  elif source.configuration_fingerprint not in preparation.provenance_json:reasons.append("SOURCE_DEPENDENCY_NOT_CURRENT")
  if candidate.taxonomy_reconciliation not in APPROVABLE_TAXONOMY:reasons.append("TAXONOMY_NOT_ACCEPTABLE")
  if candidate.boundary_reconciliation!="INSIDE_OR_ON_BOUNDARY":reasons.append("OUTSIDE_GOVERNED_BOUNDARY")
  if candidate.overlap_classification!="DISTINCT":reasons.append("NOT_DISTINCT")
  if not (candidate.provider_occurrence_id or candidate.upstream_occurrence_id):reasons.append("STABLE_RECORD_ID_MISSING")
  if not candidate.original_record_reference:reasons.append("SOURCE_REFERENCE_MISSING")
  if metadata.get("provider_identity_status")!="REPORTED" or not metadata.get("scientific_provider"):reasons.append("SCIENTIFIC_PROVIDER_UNRESOLVED")
  if not metadata.get("license"):reasons.append("RECORD_LICENSE_UNRESOLVED")
  return {"eligible":not reasons,"blocking_reasons":reasons,"license_status":"PRESENT_REQUIRES_COMPLIANCE" if metadata.get("license") else "UNRESOLVED","scientific_provider":metadata.get("scientific_provider"),"transport_interface":metadata.get("transport_interface"),"record_license":metadata.get("license")}
 def review(self,preparation_id,candidate_ids,disposition,user_id,reason_code,note=None):
  if disposition not in DISPOSITIONS:raise ValueError("Unknown occurrence candidate disposition")
  preparation=self._preparation(preparation_id);self._validate_preparation(preparation)
  candidates=self._candidates(preparation_id,candidate_ids)
  for candidate in candidates:
   eligibility=self.eligibility(candidate)
   if disposition=="APPROVED_AS_NEW_EVIDENCE" and not eligibility["eligible"]:raise ValueError(f"Candidate {candidate.id} is not eligible: {', '.join(eligibility['blocking_reasons'])}")
   if disposition=="REJECTED_OUTSIDE_JURISDICTION" and candidate.boundary_reconciliation=="INSIDE_OR_ON_BOUNDARY":raise ValueError(f"Candidate {candidate.id} is not outside the governed boundary")
   self._append(preparation,candidate,disposition,reason_code,note,user_id)
  if disposition=="APPROVED_AS_NEW_EVIDENCE":preparation.workflow_status="APPROVED";preparation.approved_by_user_id=user_id;preparation.approval_reference=reason_code;preparation.approved_dependency_fingerprint=preparation.dependency_fingerprint;preparation.approved_at=datetime.now(timezone.utc)
  self.session.commit();return self.report(preparation_id)
 def record_application(self,candidate,evidence,user_id):
  preparation=self._preparation(candidate.preparation_id)
  return self._append(preparation,candidate,"APPROVED_AS_NEW_EVIDENCE","APPLIED_TO_GOVERNED_EVIDENCE",f"GovernedOccurrenceEvidence:{evidence.id}",user_id,resulting_evidence_id=evidence.id)
 def latest(self,candidate_id):return self.session.query(OccurrenceCandidateReview).filter_by(candidate_id=candidate_id).order_by(OccurrenceCandidateReview.id.desc()).first()
 def report(self,preparation_id):
  preparation=self._preparation(preparation_id);candidates=self._candidates(preparation_id);payload=[self.payload(c) for c in candidates];counts={}
  for item in payload:counts[item["review_disposition"]]=counts.get(item["review_disposition"],0)+1
  return {"preparation_id":preparation_id,"workflow_status":preparation.workflow_status,"scientific_dataset_id":preparation.scientific_dataset_id,"applied_at":preparation.applied_at,"counts":counts,"candidates":payload,"legacy_links":self.session.query(OccurrenceLegacyLink).filter_by(preparation_id=preparation_id).count(),"firewall_report":json.loads(preparation.firewall_report_json) if preparation.firewall_report_json else None,"scientific_firewall":"OCCURRENCE EVIDENCE != ECOLOGICAL OR INVASIVE STATUS"}
 def payload(self,candidate):
  review=self.latest(candidate.id);eligibility=self.eligibility(candidate);metadata=json.loads(candidate.source_metadata_json or "{}")
  return {"candidate_id":candidate.id,"review_disposition":review.disposition if review else "REVIEW_REQUIRED","reason_code":review.reason_code if review else "NOT_INITIALIZED","reviewed_at":review.reviewed_at if review else None,"evidence_note":review.evidence_note if review else None,"resulting_evidence_id":candidate.applied_evidence_id,"eligibility":eligibility,"source_metadata":metadata}
 def _append(self,preparation,candidate,disposition,reason,note,user_id,resulting_evidence_id=None):
  metadata=json.loads(candidate.source_metadata_json or "{}");license_payload={"license":metadata.get("license"),"dataset_id":metadata.get("obis_dataset_id"),"dataset_name":metadata.get("dataset_name"),"scientific_provider":metadata.get("scientific_provider"),"transport_interface":metadata.get("transport_interface")};fingerprint=_hash({"candidate":candidate.id,"dependency":preparation.dependency_fingerprint,"disposition":disposition,"reason":reason,"note":note,"resulting_evidence_id":resulting_evidence_id})
  existing=self.session.query(OccurrenceCandidateReview).filter_by(review_fingerprint=fingerprint).one_or_none()
  if existing:return existing
  row=OccurrenceCandidateReview(preparation_id=preparation.id,candidate_id=candidate.id,disposition=disposition,reason_code=reason,evidence_note=note,reviewer_user_id=user_id,reviewed_at=datetime.now(timezone.utc),dependency_fingerprint=preparation.dependency_fingerprint,source_license_json=canonical_json(license_payload),provenance_json=canonical_json({"candidate_fingerprint":candidate.provenance_fingerprint,"source_registration_id":preparation.source_registration_id,"artifact_sha256":preparation.raw_artifact_sha256}),review_fingerprint=fingerprint,resulting_evidence_id=resulting_evidence_id);self.session.add(row);candidate.review_status=disposition;candidate.reviewed_by_user_id=user_id;candidate.review_reference=reason;candidate.reviewed_at=row.reviewed_at;return row
 def _link_legacy(self,preparation,candidate):
  if candidate.overlap_classification!="VERIFIED_OVERLAP":return
  for value in json.loads(candidate.matching_evidence_ids_json or "[]"):
   if not str(value).startswith("historical:"):continue
   historical_id=int(str(value).split(":",1)[1]);fingerprint=_hash({"candidate":candidate.id,"historical":historical_id,"basis":candidate.overlap_reason})
   if not self.session.query(OccurrenceLegacyLink).filter_by(link_fingerprint=fingerprint).first():self.session.add(OccurrenceLegacyLink(preparation_id=preparation.id,candidate_id=candidate.id,historical_occurrence_id=historical_id,overlap_basis=candidate.overlap_reason,provider_occurrence_id=candidate.provider_occurrence_id,upstream_occurrence_id=candidate.upstream_occurrence_id,candidate_provenance_fingerprint=candidate.provenance_fingerprint,link_fingerprint=fingerprint,created_at=datetime.now(timezone.utc)))
 def _validate_preparation(self,preparation):
  if preparation.workflow_status in {"STALE","FAILED","APPLIED"}:raise ValueError("Preparation is not reviewable")
 def _preparation(self,id):
  row=self.session.get(OccurrenceAcquisitionPreparation,id)
  if not row:raise ValueError("Occurrence preparation does not exist")
  return row
 def _candidates(self,preparation_id,ids=None):
  query=self.session.query(OccurrenceCandidateRecord).filter_by(preparation_id=preparation_id)
  if ids is not None:query=query.filter(OccurrenceCandidateRecord.id.in_(ids))
  rows=query.order_by(OccurrenceCandidateRecord.id).all()
  if ids is not None and len(rows)!=len(set(ids)):raise ValueError("Candidate selection is invalid")
  return rows
