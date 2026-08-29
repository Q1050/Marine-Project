"""Governed, conservative early-warning evaluation for verified observations."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
import hashlib, json

from anomaly_domain import (ANOMALY_PROVENANCE_VERSION, AnomalyReviewState,
    AssessmentStatus, EvidenceConfidence, ReviewType, SignalStatus, SignalType)
from anomaly_repository import AnomalyRepository, canonical_json
from models import (AnomalyAssessment, AnomalyConfiguration, AnomalyReviewEvent,
    AnomalySignal, EcologicalStatusAssertion, GovernedOccurrenceEvidence,
    HabitatSuitabilityV3GridCell, JurisdictionBoundary, Observation,
    RegionalTaxonRegistry, Species, SpeciesProgram, SuitabilityDeployment)

RULE_VERSION="marine-early-warning-v1"

def haversine(a,b,c,d):
 p1,p2=radians(a),radians(c);dp=radians(c-a);dl=radians(d-b)
 x=sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2
 return 6371.0088*2*asin(sqrt(x))

class EarlyWarningService:
 def __init__(self,session):self.session=session;self.repository=AnomalyRepository(session)
 def readiness(self,observation_id):
  o=self.session.get(Observation,observation_id)
  if not o:raise LookupError("Observation not found")
  reasons=[];species=None;registry=None
  if o.jurisdiction_id is None:reasons.append("Observation has no configured jurisdiction.")
  if o.latitude is None or o.longitude is None or not(-90<=o.latitude<=90 and -180<=o.longitude<=180):reasons.append("Observation coordinates are invalid.")
  if o.verification_status not in {"CONFIRMED","CORRECTED"} or not o.verified_species:reasons.append("Expert-confirmed or expert-corrected identity is required.")
  else:species=self.session.query(Species).filter(Species.scientific_name==o.verified_species).one_or_none()
  if species and o.jurisdiction:registry=self.session.query(RegionalTaxonRegistry).filter_by(region_id=o.jurisdiction.region_id,taxon_id=species.id,review_status="APPROVED").filter(RegionalTaxonRegistry.superseded_at.is_(None)).first()
  if o.verified_species and not species:reasons.append("Verified identity requires governed taxonomy review.")
  elif species and not registry:reasons.append("Resolved taxon is not approved in the jurisdiction's regional catalog.")
  if o.is_possible_duplicate or o.duplicate_of_observation_id:reasons.append("Duplicate observations are not independent anomaly evidence.")
  if o.verification_status=="REJECTED":reasons.append("Rejected observations are not eligible.")
  return {"eligible":not reasons,"observation":o,"species":species,"registry":registry,"reasons":reasons,
          "handoff":"ELIGIBLE_FOR_ANOMALY_EVALUATION" if not reasons else "TAXONOMY_REVIEW_REQUIRED" if o.verified_species and not species else "BLOCKED"}
 def evaluate(self,observation_id):
  ready=self.readiness(observation_id);o=ready["observation"]
  if not ready["eligible"]:raise ValueError("; ".join(ready["reasons"]))
  species=ready["species"];j=o.jurisdiction
  boundary=self.session.query(JurisdictionBoundary).filter_by(jurisdiction_id=j.id,status="ACTIVE").order_by(JurisdictionBoundary.id.desc()).first()
  occurrences=self.session.query(GovernedOccurrenceEvidence).filter_by(jurisdiction_id=j.id,taxon_id=species.id).order_by(GovernedOccurrenceEvidence.id).all()
  assertions=self.session.query(EcologicalStatusAssertion).filter_by(jurisdiction_id=j.id,taxon_id=species.id,review_status="APPROVED",authority_classification="AUTHORITATIVE_FOR_JURISDICTION",lifecycle_state="CURRENT").order_by(EcologicalStatusAssertion.id).all()
  program=self.session.query(SpeciesProgram).filter_by(jurisdiction_id=j.id,species_id=species.id,status="ACTIVE").first()
  deployment=self.session.query(SuitabilityDeployment).filter_by(species_program_id=program.id,status="ACTIVE").first() if program else None
  config=self.session.query(AnomalyConfiguration).filter_by(jurisdiction_id=j.id,taxon_id=species.id,review_status="ACTIVE").order_by(AnomalyConfiguration.id.desc()).first()
  deps={"rule_version":RULE_VERSION,"observation":{"id":o.id,"verified_species":o.verified_species,"verification_status":o.verification_status,"latitude":o.latitude,"longitude":o.longitude},"boundary":None if not boundary else [boundary.id,boundary.geometry_hash],"registry":ready["registry"].provenance_fingerprint,"occurrences":[[x.id,x.evidence_fingerprint] for x in occurrences],"assertions":[x.provenance_fingerprint for x in assertions],"deployment":None if not deployment else [deployment.id,deployment.artifact_hash],"configuration":None if not config else config.dependency_fingerprint}
  fingerprint=hashlib.sha256(canonical_json(deps).encode()).hexdigest();current=self.repository.get_current_assessment(o.id)
  if current and current.dependency_fingerprint==fingerprint:return current
  if current:self.repository.mark_assessment_stale(current)
  signal_payloads=self._signals(o,species,occurrences,assertions,deployment,config)
  occurrence_category=signal_payloads[0][1]["categorical_result"]
  trigger_families=[p[0].value if hasattr(p[0],"value") else str(p[0]) for p in signal_payloads if p[1].get("review_trigger")];configured_signal=bool(trigger_families)
  if configured_signal:status=AssessmentStatus.REVIEW_SUGGESTED;requires=True
  elif occurrence_category in {"NO_GOVERNED_BASELINE","LIMITED_BASELINE"}:status=AssessmentStatus.INSUFFICIENT_BASELINE;requires=False
  else:status=AssessmentStatus.NO_REVIEW_SIGNAL;requires=False
  explanation=self._explanation(o,occurrence_category,len(occurrences),config,trigger_families)
  assessment=self.repository.create_assessment(observation_id=o.id,jurisdiction_id=j.id,species_program_id=program.id if program else None,evaluated_species=species.scientific_name,evaluated_species_source="EXPERT_VERIFIED",overall_status=status,overall_classification=None,assessment_confidence="VERIFIED",requires_review=requires,review_type=ReviewType.ECOLOGICAL_REVIEW if requires else ReviewType.NO_REVIEW,provenance_version=RULE_VERSION,dependency_fingerprint=fingerprint,evidence_summary_json={"explanation":explanation,"signal_count":len(signal_payloads),"baseline_record_count":len(occurrences)},limitations_json=["Anomaly is a review signal, not invasive status, range expansion, threat, or ecological conclusion."],provenance_json=deps)
  for signal_type,evidence,limitations,deployment_id in signal_payloads:self.repository.create_signal(anomaly_assessment_id=assessment.id,signal_type=signal_type,status=SignalStatus.SIGNAL_DETECTED if evidence.get("review_trigger") else SignalStatus.INSUFFICIENT_EVIDENCE if evidence["categorical_result"] in {"NO_GOVERNED_BASELINE","LIMITED_BASELINE","NO_GOVERNED_TEMPORAL_BASELINE"} else SignalStatus.NO_SIGNAL,anomaly_strength=None,evidence_confidence=EvidenceConfidence.NONE if not occurrences else EvidenceConfidence.LOW,evidence_summary_json=evidence,limitations_json=limitations,source_dataset_ids_json=[],suitability_deployment_id=deployment_id,supporting_observation_ids_json=[],provenance_version=RULE_VERSION)
  if current:self.repository.mark_assessment_superseded(current)
  return assessment
 def _signals(self,o,species,occurrences,assertions,deployment,config):
  nearest=min((haversine(o.latitude,o.longitude,x.latitude,x.longitude) for x in occurrences),default=None)
  dates=sorted(x.event_date for x in occurrences if x.event_date)
  occ="BASELINE_PRESENT" if occurrences else "NO_GOVERNED_BASELINE"
  enabled=set(json.loads(config.enabled_signal_types_json)) if config else set();review_trigger=False
  # Numeric spatial rules are used only when an explicitly approved configuration exists.
  if config and config.mode!="DESCRIPTIVE_ONLY" and config.spatial_rule_json and "GEOGRAPHIC_CONTEXT" in enabled:
   rule=json.loads(config.spatial_rule_json);threshold=rule.get("review_distance_km");minimum=int(rule.get("minimum_baseline_records",1))
   review_trigger=nearest is not None and threshold is not None and len(occurrences)>=minimum and nearest>float(threshold)
  temporal_trigger=False;temporal_rule=None;temporal_gap_days=None;minimum_dated=1
  if config and config.mode!="DESCRIPTIVE_ONLY" and config.temporal_rule_json and "TEMPORAL_CONTEXT" in enabled:
   temporal_rule=json.loads(config.temporal_rule_json);minimum_dated=int(temporal_rule.get("minimum_dated_records",1));threshold_days=temporal_rule.get("minimum_days_since_latest_record")
   if dates and len(dates)>=minimum_dated and threshold_days is not None:
    observed_date=(o.created_at or datetime.now(timezone.utc)).date();temporal_gap_days=(observed_date-dates[-1].date()).days;temporal_trigger=temporal_gap_days>float(threshold_days)
  cell=None
  if deployment:
   cell=self.session.query(HabitatSuitabilityV3GridCell).filter_by(model_version=deployment.model_version,prediction_status="SCORED").order_by((HabitatSuitabilityV3GridCell.latitude-o.latitude)*(HabitatSuitabilityV3GridCell.latitude-o.latitude)+(HabitatSuitabilityV3GridCell.longitude-o.longitude)*(HabitatSuitabilityV3GridCell.longitude-o.longitude)).first()
  environmental="MODEL_UNAVAILABLE" if not deployment else "OUTSIDE_MODEL_DOMAIN" if not cell or abs(cell.latitude-o.latitude)>.051 or abs(cell.longitude-o.longitude)>.051 else {"HIGH":"WITHIN_HIGHER_SUITABILITY_CONTEXT","VERY_HIGH":"WITHIN_HIGHER_SUITABILITY_CONTEXT","MODERATE":"WITHIN_MODERATE_CONTEXT"}.get(cell.suitability_band,"WITHIN_LOWER_SUITABILITY_CONTEXT")
  statuses=sorted({a.asserted_status for a in assertions});eco="STATUS_UNAVAILABLE" if not statuses else "STATUS_CONFLICT" if {"NATIVE","INVASIVE"}.issubset(statuses) else "+".join(statuses)
  common=["No governed baseline does not mean first occurrence.","Absence of evidence is not evidence of absence."]
  return [(SignalType.OCCURRENCE_NOVELTY,{"categorical_result":occ,"governed_record_count":len(occurrences)},common,None),(SignalType.GEOGRAPHIC_CONTEXT,{"categorical_result":"DESCRIPTIVE_ONLY" if occurrences else "INSUFFICIENT_EVIDENCE","nearest_governed_occurrence_km":None if nearest is None else round(nearest,3),"review_trigger":review_trigger,"reviewed_rule":json.loads(config.spatial_rule_json) if config and config.spatial_rule_json and config.mode!="DESCRIPTIVE_ONLY" else None},["Distance is descriptive unless an approved configuration supplies a rule."],None),(SignalType.TEMPORAL_CONTEXT,{"categorical_result":"NO_GOVERNED_TEMPORAL_BASELINE" if not dates else "INSUFFICIENT_TEMPORAL_COVERAGE" if len(dates)<minimum_dated else "PRIOR_DATED_RECORDS_PRESENT","dated_records":len(dates),"earliest":dates[0].isoformat() if dates else None,"latest":dates[-1].isoformat() if dates else None,"days_since_latest_record":temporal_gap_days,"review_trigger":temporal_trigger,"reviewed_rule":temporal_rule},["No recent governed record does not mean absence or first occurrence.","A temporal trigger exists only when an active reviewed rule and sufficient dated evidence are available."],None),(SignalType.ENVIRONMENTAL_CONTEXT,{"categorical_result":environmental,"suitability_band":cell.suitability_band if cell else None,"suitability_score":cell.suitability_score if cell else None},["Suitability is environmental context, not occurrence probability or observation validity."],deployment.id if deployment else None),(SignalType.ECOLOGICAL_CONTEXT,{"categorical_result":eco,"approved_statuses":statuses},["Ecological status is context and never creates an anomaly signal by itself."],None)]
 @staticmethod
 def _explanation(o,category,count,config,triggers):
  if triggers:return f"Expert-verified {o.verified_species} observation met explicitly reviewed {', '.join(triggers)} rule(s) in configuration {config.configuration_version}. The governed baseline contained {count} records. Human scientific review is suggested; rule limitations remain applicable."
  if category=="NO_GOVERNED_BASELINE":return f"Expert-verified {o.verified_species} observation has no matching governed jurisdiction occurrence baseline. This does not mean first occurrence; human interpretation is limited."
  return f"Expert-verified {o.verified_species} observation was evaluated against {count} governed jurisdiction occurrence records. No configured review signal was produced."
 def disposition(self,assessment_id,user_id,to_state,reason):
  if to_state not in {x.value for x in AnomalyReviewState}:raise ValueError("Invalid review state")
  if not reason.strip():raise ValueError("Scientific disposition reason is required")
  assessment=self.session.get(AnomalyAssessment,assessment_id)
  if not assessment:raise LookupError("Assessment not found")
  prior=self.session.query(AnomalyReviewEvent).filter_by(anomaly_assessment_id=assessment_id).order_by(AnomalyReviewEvent.id.desc()).first();from_state=prior.to_state if prior else AnomalyReviewState.PENDING_REVIEW.value
  row=AnomalyReviewEvent(anomaly_assessment_id=assessment.id,jurisdiction_id=assessment.jurisdiction_id,reviewer_user_id=user_id,from_state=from_state,to_state=to_state,reason=reason.strip());self.session.add(row);self.session.flush();return row
 def queue(self,jurisdiction_id=None):
  query=self.session.query(AnomalyAssessment).filter_by(current_state="CURRENT");
  if jurisdiction_id:query=query.filter_by(jurisdiction_id=jurisdiction_id)
  rows=query.order_by(AnomalyAssessment.generated_at.desc()).all();items=[]
  for a in rows:
   event=self.session.query(AnomalyReviewEvent).filter_by(anomaly_assessment_id=a.id).order_by(AnomalyReviewEvent.id.desc()).first();items.append(self.payload(a,event))
  return items
 def payload(self,a,event=None):
  from models import AnomalyReviewAssignment
  observation=self.session.get(Observation,a.observation_id)
  species=self.session.query(Species).filter_by(scientific_name=a.evaluated_species).one_or_none() if a.evaluated_species else None
  baseline=self.session.query(GovernedOccurrenceEvidence).filter_by(jurisdiction_id=a.jurisdiction_id,taxon_id=species.id).order_by(GovernedOccurrenceEvidence.id).all() if species else []
  verified=self.session.query(Observation).filter(Observation.jurisdiction_id==a.jurisdiction_id,Observation.verified_species==a.evaluated_species,Observation.verification_status.in_(["CONFIRMED","CORRECTED"]),Observation.is_possible_duplicate.is_(False),Observation.duplicate_of_observation_id.is_(None)).order_by(Observation.id).all()
  boundary=self.session.query(JurisdictionBoundary).filter_by(jurisdiction_id=a.jurisdiction_id,status="ACTIVE").order_by(JurisdictionBoundary.id.desc()).first()
  program=self.session.query(SpeciesProgram).filter_by(jurisdiction_id=a.jurisdiction_id,species_id=species.id,status="ACTIVE").first() if species else None
  deployment=self.session.query(SuitabilityDeployment).filter_by(species_program_id=program.id,status="ACTIVE").order_by(SuitabilityDeployment.id.desc()).first() if program else None
  suitability_cells=self.session.query(HabitatSuitabilityV3GridCell).filter_by(suitability_deployment_id=deployment.id,prediction_status="SCORED").order_by(HabitatSuitabilityV3GridCell.id).all() if deployment else []
  assignment=self.session.query(AnomalyReviewAssignment).filter_by(anomaly_assessment_id=a.id,status="ASSIGNED").order_by(AnomalyReviewAssignment.id.desc()).first()
  history=self.session.query(AnomalyReviewEvent).filter_by(anomaly_assessment_id=a.id).order_by(AnomalyReviewEvent.id).all()
  return {"id":a.id,"observation_id":a.observation_id,"jurisdiction_id":a.jurisdiction_id,"evaluated_species":a.evaluated_species,"overall_status":a.overall_status,"lifecycle_state":a.current_state,"review_state":event.to_state if event else history[-1].to_state if history else "PENDING_REVIEW","generated_at":a.generated_at,"explanation":json.loads(a.evidence_summary_json or "{}").get("explanation"),"limitations":json.loads(a.limitations_json),"observation":{"latitude":observation.latitude,"longitude":observation.longitude,"submitted_at":observation.created_at,"verification_status":observation.verification_status} if observation else None,"assignment":{"reviewer_user_id":assignment.reviewer_user_id,"assigned_at":assignment.assigned_at} if assignment else None,"review_history":[{"from_state":x.from_state,"to_state":x.to_state,"reviewer_user_id":x.reviewer_user_id,"reason":x.reason,"created_at":x.created_at} for x in history],"spatial_context":{"boundary":json.loads(boundary.geometry_json) if boundary and boundary.geometry_json else None,"governed_occurrences":[{"id":x.id,"latitude":x.latitude,"longitude":x.longitude,"event_date":x.event_date,"considered_by_assessment":True} for x in baseline if x.latitude is not None and x.longitude is not None],"verified_observations":[{"id":x.id,"latitude":x.latitude,"longitude":x.longitude,"submitted_at":x.created_at} for x in verified],"suitability":{"available":bool(deployment and suitability_cells),"deployment_id":deployment.id if deployment else None,"model_version":deployment.model_version if deployment else None,"cells":[{"id":x.id,"latitude":x.latitude,"longitude":x.longitude,"grid_size":x.grid_size,"score":x.suitability_score,"band":x.suitability_band} for x in suitability_cells],"limitation":"Environmental suitability is contextual evidence and does not confirm or exclude species presence."}},"signals":[{"id":s.id,"signal_type":s.signal_type,"status":s.status,"evidence":json.loads(s.evidence_summary_json or "{}"),"limitations":json.loads(s.limitations_json)} for s in a.signals]}
 def summary(self,jurisdiction_id=None):return dict(Counter(x["overall_status"] for x in self.queue(jurisdiction_id)))
