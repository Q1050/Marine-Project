"""Governed, provider-neutral jurisdiction occurrence-evidence preparation."""
from __future__ import annotations
import hashlib, json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from shapely.geometry import Point, shape
from sqlalchemy import inspect as sa_inspect
from jurisdiction_boundary_registry import canonical_json
from models import *

NORMALIZATION_VERSION="jurisdiction-occurrence-candidate-v1"

@dataclass(frozen=True)
class OccurrenceSourceContract:
 source_key:str; scientific_provider:str; transport_interface:str|None; provider_dataset_id:str; provider_dataset_version:str|None; source_reference:str; license:str; reuse_conditions:str; ownership_scope:str; limitations:tuple[str,...]=()

@dataclass(frozen=True)
class SourceAcquisition:
 records:tuple[dict,...]; acquisition_parameters:dict; declared_extent:dict; raw_artifact_reference:str; raw_artifact_sha256:str; acquired_at:str

class OccurrenceSourceAdapter:
 contract:OccurrenceSourceContract
 def acquire(self,jurisdiction,taxon,boundary):raise NotImplementedError

class OccurrenceSourceRegistry:
 def __init__(self,adapters=()):self.adapters={adapter.contract.source_key:adapter for adapter in adapters}
 def list(self):return [asdict(adapter.contract)|{"configured":True} for adapter in self.adapters.values()]
 def require(self,key):
  if key not in self.adapters:raise ValueError("Occurrence source is not configured")
  return self.adapters[key]

def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=lambda item:item.isoformat() if isinstance(item,datetime) else str(item)).encode()).hexdigest()
def _date(value):
 if not value:return None
 try:
  parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
  return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
 except (ValueError,TypeError):return None
def _name(value):return " ".join(str(value or "").strip().casefold().split())

class OccurrenceEvidenceService:
 def __init__(self,session,registry=None):
  self.session=session
  if registry is None:
   from obis_occurrence_adapter import OBISOccurrenceAdapter
   adapters=[]
   for row in session.query(OccurrenceSourceRegistration).filter_by(workflow_status="ACTIVE").all():
    if row.acquisition_mechanism=="OBIS_V3_API":adapters.append(OBISOccurrenceAdapter(row))
   registry=OccurrenceSourceRegistry(adapters)
  self.registry=registry
 def sources(self):return self.registry.list()
 def readiness(self,jurisdiction_id,taxon_id,source_key):
  jurisdiction=self.session.get(Jurisdiction,jurisdiction_id);taxon=self.session.get(Species,taxon_id)
  if not jurisdiction or not taxon:return "BLOCKED"
  governed=self.session.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id,taxon_id=taxon.id,review_status="APPROVED").first()
  if not governed:return "TAXON_UNSUPPORTED"
  if self.session.query(JurisdictionBoundary).filter_by(jurisdiction_id=jurisdiction.id,boundary_type="MARINE_MONITORING",status="ACTIVE").count()!=1:return "BOUNDARY_UNAVAILABLE"
  if source_key not in self.registry.adapters:return "SOURCE_UNAVAILABLE"
  applied=self.session.query(OccurrenceAcquisitionPreparation).filter_by(jurisdiction_id=jurisdiction.id,taxon_id=taxon.id,source_key=source_key,workflow_status="APPLIED").first()
  return "ALREADY_GOVERNED" if applied else "READY_FOR_ACQUISITION"
 def prepare(self,jurisdiction_id,taxon_id,source_key,user_id,dry_run=False):
  jurisdiction=self.session.get(Jurisdiction,jurisdiction_id);taxon=self.session.get(Species,taxon_id)
  if not jurisdiction or not taxon:raise ValueError("Jurisdiction and taxon are required")
  if not self.session.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id,taxon_id=taxon.id,review_status="APPROVED").first():raise ValueError("Taxon is not governed for the jurisdiction region")
  boundaries=self.session.query(JurisdictionBoundary).filter_by(jurisdiction_id=jurisdiction.id,boundary_type="MARINE_MONITORING",status="ACTIVE").all()
  if len(boundaries)!=1:raise ValueError("Exactly one active MARINE_MONITORING boundary is required")
  boundary=boundaries[0];adapter=self.registry.require(source_key);acquisition=adapter.acquire(jurisdiction,taxon,boundary);contract=adapter.contract
  path=Path(acquisition.raw_artifact_reference)
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=acquisition.raw_artifact_sha256:raise ValueError("Raw artifact hash mismatch")
  normalized=[self._normalize(record,taxon,boundary,contract) for record in acquisition.records];content_fp=_hash(normalized)
  registration=getattr(adapter,"registration",None)
  # The governed content, source configuration, taxon, and boundary define the
  # preparation. Acquisition timestamps/artifact hashes remain provenance but do
  # not create duplicate preparations for an otherwise identical provider result.
  dependency={"jurisdiction_id":jurisdiction.id,"taxon_id":taxon.id,"source":asdict(contract),"source_registration":[registration.id,registration.configuration_fingerprint] if registration else None,"content":content_fp,"boundary":[boundary.id,boundary.geometry_hash,boundary.source_artifact_sha256]};dependency_fp=_hash(dependency)
  summary=self._summary(normalized)
  if dry_run:return {"dry_run":True,"dependency_fingerprint":dependency_fp,"source":asdict(contract),"summary":summary,"candidates":normalized,"firewall":{"status":"PASS","statement":"OCCURRENCE EVIDENCE != ECOLOGICAL OR INVASIVE STATUS"}}
  existing=self.session.query(OccurrenceAcquisitionPreparation).filter_by(dependency_fingerprint=dependency_fp).one_or_none()
  if existing:return self.detail(existing.id)|{"rerun_status":"NO-OP"}
  row=OccurrenceAcquisitionPreparation(region_id=jurisdiction.region_id,jurisdiction_id=jurisdiction.id,taxon_id=taxon.id,source_registration_id=registration.id if registration else None,source_key=contract.source_key,scientific_provider=contract.scientific_provider,transport_interface=contract.transport_interface,provider_dataset_id=contract.provider_dataset_id,provider_dataset_version=contract.provider_dataset_version,source_reference=contract.source_reference,license_json=canonical_json({"license":contract.license,"reuse_conditions":contract.reuse_conditions}),acquisition_parameters_json=canonical_json(acquisition.acquisition_parameters),declared_extent_json=canonical_json(acquisition.declared_extent),ownership_scope_json=canonical_json({"ownership_scope":contract.ownership_scope}),limitations_json=canonical_json(list(contract.limitations)),raw_artifact_reference=str(path),raw_artifact_sha256=acquisition.raw_artifact_sha256,normalized_content_fingerprint=content_fp,boundary_id=boundary.id,boundary_geometry_hash=boundary.geometry_hash,boundary_source_artifact_sha256=boundary.source_artifact_sha256,dependency_fingerprint=dependency_fp,workflow_status="READY_FOR_REVIEW",prepared_by_user_id=user_id,provenance_json=canonical_json({"contract":asdict(contract),"acquired_at":acquisition.acquired_at,"dependency":dependency}));self.session.add(row);self.session.flush()
  for value in normalized:self.session.add(OccurrenceCandidateRecord(preparation_id=row.id,**value))
  self.session.commit();return self.detail(row.id)
 def _normalize(self,record,taxon,boundary,contract):
  taxonomy,reconciled=self._taxonomy(record,taxon);lat=record.get("latitude");lon=record.get("longitude")
  boundary_status="UNRESOLVED" if lat is None or lon is None else ("INSIDE_OR_ON_BOUNDARY" if shape(json.loads(boundary.geometry_json)).covers(Point(float(lon),float(lat))) else "OUTSIDE_BOUNDARY")
  overlap,reason,matches=self._overlap(record,taxon,contract)
  core={"provider_occurrence_id":record.get("provider_occurrence_id"),"upstream_occurrence_id":record.get("upstream_occurrence_id"),"event_id":record.get("event_id"),"catalog_specimen_id":record.get("catalog_specimen_id"),"observation_reference":record.get("observation_reference"),"original_scientific_name":record.get("scientific_name"),"reconciled_taxon_id":reconciled,"taxonomy_reconciliation":taxonomy,"latitude":float(lat) if lat is not None else None,"longitude":float(lon) if lon is not None else None,"event_date":_date(record.get("event_date")),"basis_of_record":record.get("basis_of_record"),"occurrence_status":record.get("occurrence_status"),"coordinate_uncertainty_m":record.get("coordinate_uncertainty_m"),"depth_m":record.get("depth_m"),"locality":record.get("locality"),"boundary_reconciliation":boundary_status,"boundary_id":boundary.id,"overlap_classification":overlap,"overlap_reason":reason,"matching_evidence_ids_json":canonical_json(matches),"source_metadata_json":canonical_json(record.get("source_metadata") or {}),"original_record_reference":record.get("original_record_reference"),"normalization_version":NORMALIZATION_VERSION}
  serial={key:(value.isoformat() if isinstance(value,datetime) else value) for key,value in core.items()};core["provenance_fingerprint"]=_hash({"source_key":contract.source_key,"record":serial});return core
 def _taxonomy(self,record,target):
  name=_name(record.get("scientific_name"));target_name=_name(target.scientific_name);identifier=str(record.get("authoritative_identifier") or "")
  if identifier and target.authoritative_identifier and identifier==target.authoritative_identifier:return "EXACT_ACCEPTED_TAXON",target.id
  synonym=self.session.query(Species).filter_by(authoritative_identifier_scheme=target.authoritative_identifier_scheme,authoritative_identifier=identifier).one_or_none() if identifier else None
  if synonym and synonym.accepted_taxon_id==target.id:return "SYNONYM_TO_ACCEPTED_TAXON",target.id
  if name==target_name:return "EXACT_ACCEPTED_TAXON",target.id
  genus=target_name.split()[0] if target_name else ""
  if name in {genus,f"{genus} sp.",f"{genus} spp."}:return "BROADER_TAXON",None
  if genus and name.startswith(genus+" ") and any(marker in name for marker in ("/"," complex"," spp."," sp.")):return "SPECIES_COMPLEX",None
  return ("TAXONOMIC_CONFLICT" if name else "UNRESOLVED"),None
 def _overlap(self,record,taxon,contract):
  identifiers={str(value).casefold() for value in (record.get("provider_occurrence_id"),record.get("upstream_occurrence_id"),record.get("catalog_specimen_id")) if value};matches=[]
  for row in self.session.query(GovernedOccurrenceEvidence).filter_by(taxon_id=taxon.id).all():
   existing={str(value).casefold() for value in (row.provider_occurrence_id,row.upstream_occurrence_id,row.catalog_specimen_id) if value}
   if identifiers&existing:matches.append(f"governed:{row.id}")
  for row in self.session.query(HistoricalOccurrence).filter_by(scientific_name=taxon.scientific_name).all():
   existing={str(value).casefold() for value in (row.occurrence_id,row.raw_source_id) if value}
   if identifiers&existing:matches.append(f"historical:{row.id}")
  if matches:return "VERIFIED_OVERLAP","IDENTICAL_AUTHORITATIVE_OR_UPSTREAM_IDENTIFIER",matches
  date=_date(record.get("event_date"));lat=record.get("latitude");lon=record.get("longitude")
  composite=[]
  if lat is not None and lon is not None and date:
   for row in self.session.query(GovernedOccurrenceEvidence).filter_by(taxon_id=taxon.id,latitude=float(lat),longitude=float(lon),event_date=date).all():composite.append(f"governed:{row.id}")
   for row in self.session.query(HistoricalOccurrence).filter_by(scientific_name=taxon.scientific_name,latitude=float(lat),longitude=float(lon),event_date=date).all():composite.append(f"historical:{row.id}")
  if composite:return "POSSIBLE_OVERLAP","EXACT_TAXON_COORDINATE_DATE_MATCH",composite
  if record.get("provider_occurrence_id"):return "DISTINCT","PROVIDER_STABLE_IDENTIFIER_WITH_NO_MATCH",[]
  return "INDEPENDENCE_UNKNOWN","NO_CROSS_SOURCE_LINKAGE_IDENTIFIER",[]
 def approve(self,preparation_id,candidate_ids,user_id,reference):
  self._validate(self._row(preparation_id));from occurrence_candidate_review import OccurrenceCandidateReviewService
  OccurrenceCandidateReviewService(self.session).review(preparation_id,candidate_ids,"APPROVED_AS_NEW_EVIDENCE",user_id,reference,"Explicit governed occurrence-evidence approval.");return self.detail(preparation_id)
 def reject(self,preparation_id,candidate_ids,user_id,reference,disposition="UNRESOLVED",note=None):
  from occurrence_candidate_review import OccurrenceCandidateReviewService
  OccurrenceCandidateReviewService(self.session).review(preparation_id,candidate_ids,disposition,user_id,reference,note);return self.detail(preparation_id)
 def apply(self,preparation_id):
  row=self._row(preparation_id)
  if row.workflow_status=="APPLIED":return self.detail(row.id)|{"apply_status":"NO-OP"}
  if row.workflow_status!="APPROVED" or row.approved_dependency_fingerprint!=row.dependency_fingerprint:raise ValueError("Preparation approval is stale or absent")
  self._validate(row);approved=self.session.query(OccurrenceCandidateRecord).filter_by(preparation_id=row.id,review_status="APPROVED_AS_NEW_EVIDENCE").all()
  if not approved:raise ValueError("No candidates are approved as new evidence")
  firewall_models=(SpeciesJurisdictionStatus,SpeciesProgram,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal);existing_tables=set(sa_inspect(self.session.get_bind()).get_table_names());before={m.__tablename__:(self.session.query(m).count() if m.__tablename__ in existing_tables else 0) for m in firewall_models}
  manifest=json.loads(row.provenance_json);manifest["reviewed_snapshot"]={"preparation_id":row.id,"candidate_count":self.session.query(OccurrenceCandidateRecord).filter_by(preparation_id=row.id).count(),"approved_new_evidence_count":len(approved),"source_registration_id":row.source_registration_id,"artifact_sha256":row.raw_artifact_sha256,"boundary_geometry_hash":row.boundary_geometry_hash}
  dataset=ScientificDataset(slug=f"occurrence-{row.source_key.lower()}-{row.jurisdiction_id}-{row.taxon_id}-{row.normalized_content_fingerprint[:12]}",name=f"{row.scientific_provider} occurrence evidence",dataset_type="OCCURRENCE",species_id=row.taxon_id,geographic_scope_type="JURISDICTION",region_id=row.region_id,jurisdiction_id=row.jurisdiction_id,source_name=row.scientific_provider,source_type="SCIENTIFIC_PROVIDER",source_reference=row.source_reference,source_version=row.provider_dataset_version,acquisition_manifest_json=canonical_json(manifest),retrieved_at=row.prepared_at,record_count=len(approved),artifact_path=row.raw_artifact_reference,artifact_sha256=row.raw_artifact_sha256,notes="Governed occurrence evidence; OCCURRENCE_HISTORY only; no ecological status inference.");self.session.add(dataset);self.session.flush()
  applicability_payload={"dataset_id":dataset.id,"jurisdiction_id":row.jurisdiction_id,"role":"OCCURRENCE_HISTORY","preparation_id":row.id,"boundary_hash":row.boundary_geometry_hash};self.session.add(ScientificDatasetApplicability(scientific_dataset_id=dataset.id,jurisdiction_id=row.jurisdiction_id,evidence_role="OCCURRENCE_HISTORY",applicability_status="AUTHORIZED",reconciliation_method="GOVERNED_OCCURRENCE_PREPARATION",reconciliation_version=NORMALIZATION_VERSION,jurisdiction_boundary_id=row.boundary_id,provenance_reference=row.source_reference,provenance_json=canonical_json(applicability_payload),provenance_fingerprint=_hash(applicability_payload),approved_by=row.approval_reference,approved_at=row.approved_at))
  new_evidence_count=0
  for candidate in approved:
   fingerprint=_hash({"candidate":candidate.provenance_fingerprint,"jurisdiction":row.jurisdiction_id,"taxon":row.taxon_id})
   evidence=self.session.query(GovernedOccurrenceEvidence).filter_by(evidence_fingerprint=fingerprint).one_or_none()
   if not evidence:evidence=GovernedOccurrenceEvidence(preparation_id=row.id,candidate_record_id=candidate.id,scientific_dataset_id=dataset.id,jurisdiction_id=row.jurisdiction_id,taxon_id=row.taxon_id,provider_occurrence_id=candidate.provider_occurrence_id,upstream_occurrence_id=candidate.upstream_occurrence_id,event_id=candidate.event_id,catalog_specimen_id=candidate.catalog_specimen_id,latitude=candidate.latitude,longitude=candidate.longitude,event_date=candidate.event_date,basis_of_record=candidate.basis_of_record,boundary_id=row.boundary_id,evidence_fingerprint=fingerprint,provenance_json=canonical_json({"preparation_id":row.id,"candidate_id":candidate.id,"candidate_fingerprint":candidate.provenance_fingerprint}));self.session.add(evidence);self.session.flush();new_evidence_count+=1
   candidate.applied_evidence_id=evidence.id
   from occurrence_candidate_review import OccurrenceCandidateReviewService
   OccurrenceCandidateReviewService(self.session).record_application(candidate,evidence,row.approved_by_user_id)
  after={m.__tablename__:(self.session.query(m).count() if m.__tablename__ in existing_tables else 0) for m in firewall_models};changes={key:after[key]-before[key] for key in before}
  if any(changes.values()):raise ValueError("Scientific firewall violation")
  report={"status":"PASS","statement":"OCCURRENCE EVIDENCE != ECOLOGICAL OR INVASIVE STATUS","changes":changes};row.workflow_status="APPLIED";row.applied_at=datetime.now(timezone.utc);row.scientific_dataset_id=dataset.id;row.firewall_report_json=canonical_json(report)
  if new_evidence_count:
   from early_warning_operations import EarlyWarningOperations
   EarlyWarningOperations(self.session).emit("GOVERNED_OCCURRENCE_BASELINE_CHANGED",row.jurisdiction_id,row.taxon_id,dependency_reference=f"occurrence-preparation:{row.id}:dataset:{dataset.id}:artifact:{row.raw_artifact_sha256}",payload={"preparation_id":row.id,"scientific_dataset_id":dataset.id,"new_evidence_count":new_evidence_count})
  self.session.commit();return self.detail(row.id)|{"apply_status":"APPLIED","scientific_event_emitted":bool(new_evidence_count)}
 def retry(self,preparation_id):
  row=self._row(preparation_id)
  if row.workflow_status=="FAILED" and row.approved_dependency_fingerprint==row.dependency_fingerprint:
   row.workflow_status="APPROVED";row.last_error=None;self.session.commit()
  return self.apply(preparation_id)
 def _validate(self,row):
  path=Path(row.raw_artifact_reference)
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row.raw_artifact_sha256:row.workflow_status="STALE";self.session.commit();raise ValueError("Raw artifact changed; approval is stale")
  boundary=self.session.get(JurisdictionBoundary,row.boundary_id)
  if not boundary or boundary.status!="ACTIVE" or boundary.geometry_hash!=row.boundary_geometry_hash:row.workflow_status="STALE";self.session.commit();raise ValueError("Boundary dependency changed; approval is stale")
 def detail(self,preparation_id):
  row=self._row(preparation_id);candidates=self._candidates(row.id)
  return {"id":row.id,"region_id":row.region_id,"jurisdiction_id":row.jurisdiction_id,"taxon_id":row.taxon_id,"source":{"source_key":row.source_key,"scientific_provider":row.scientific_provider,"transport_interface":row.transport_interface,"provider_dataset_id":row.provider_dataset_id,"provider_dataset_version":row.provider_dataset_version,"source_reference":row.source_reference},"workflow_status":row.workflow_status,"dependency_fingerprint":row.dependency_fingerprint,"boundary":{"id":row.boundary_id,"geometry_hash":row.boundary_geometry_hash,"source_artifact_sha256":row.boundary_source_artifact_sha256},"summary":self._summary([self.candidate_payload(c) for c in candidates]),"candidates":[self.candidate_payload(c) for c in candidates],"scientific_dataset_id":row.scientific_dataset_id,"firewall":json.loads(row.firewall_report_json) if row.firewall_report_json else None,"limitations":json.loads(row.limitations_json)}
 def candidate_payload(self,row):
  payload={"id":row.id,"provider_occurrence_id":row.provider_occurrence_id,"upstream_occurrence_id":row.upstream_occurrence_id,"event_id":row.event_id,"catalog_specimen_id":row.catalog_specimen_id,"observation_reference":row.observation_reference,"original_scientific_name":row.original_scientific_name,"taxonomy_reconciliation":row.taxonomy_reconciliation,"latitude":row.latitude,"longitude":row.longitude,"event_date":row.event_date,"basis_of_record":row.basis_of_record,"occurrence_status":row.occurrence_status,"coordinate_uncertainty_m":row.coordinate_uncertainty_m,"depth_m":row.depth_m,"locality":row.locality,"boundary_reconciliation":row.boundary_reconciliation,"overlap_classification":row.overlap_classification,"overlap_reason":row.overlap_reason,"matching_evidence_ids":json.loads(row.matching_evidence_ids_json),"review_status":row.review_status,"provenance_fingerprint":row.provenance_fingerprint,"source_metadata":json.loads(row.source_metadata_json or "{}"),"applied_evidence_id":row.applied_evidence_id}
  if row.id:
   from occurrence_candidate_review import OccurrenceCandidateReviewService
   review=OccurrenceCandidateReviewService(self.session);latest=review.latest(row.id);payload["review_disposition"]=latest.disposition if latest else "REVIEW_REQUIRED";payload["review_reason_code"]=latest.reason_code if latest else "NOT_INITIALIZED";payload["eligibility"]=review.eligibility(row)
  return payload
 def legacy_reconciliation(self,preparation_id):
  row=self._row(preparation_id);current=self._candidates(row.id);taxon=self.session.get(Species,row.taxon_id);legacy=self.session.query(HistoricalOccurrence).filter_by(scientific_name=taxon.scientific_name).order_by(HistoricalOccurrence.id).all();matched_legacy=set();matched_current=set();taxonomy_differences=coordinate_differences=date_differences=0
  occurrence_index={old.occurrence_id.casefold():old for old in legacy if old.occurrence_id};source_index={old.raw_source_id.casefold():old for old in legacy if old.raw_source_id}
  def day(value):return value.date() if isinstance(value,datetime) else value
  exact_pairs=[];source_pairs=[]
  for candidate in current:
   old=occurrence_index.get(candidate.upstream_occurrence_id.casefold()) if candidate.upstream_occurrence_id else None
   if old:exact_pairs.append((candidate,old));matched_legacy.add(old.id);matched_current.add(candidate.id)
   old_source=source_index.get(candidate.provider_occurrence_id.casefold()) if candidate.provider_occurrence_id else None
   if old_source:source_pairs.append((candidate,old_source));matched_legacy.add(old_source.id);matched_current.add(candidate.id)
  composite_pairs=[(candidate,old) for candidate in current for old in legacy if candidate.reconciled_taxon_id==row.taxon_id and candidate.latitude==old.latitude and candidate.longitude==old.longitude and day(candidate.event_date)==day(old.event_date)]
  for candidate,old in exact_pairs or source_pairs:
   taxonomy_differences+=int(candidate.taxonomy_reconciliation not in {"EXACT_ACCEPTED_TAXON","SYNONYM_TO_ACCEPTED_TAXON"});coordinate_differences+=int((candidate.latitude,candidate.longitude)!=(old.latitude,old.longitude));date_differences+=int(day(candidate.event_date)!=day(old.event_date))
  for candidate,old in composite_pairs:matched_legacy.add(old.id);matched_current.add(candidate.id)
  exact_occurrence=len(exact_pairs);provider_ids=len(source_pairs);composite=len({candidate.id for candidate,_ in composite_pairs})
  return {"preparation_id":row.id,"legacy_count":len(legacy),"current_acquisition_count":len(current),"exact_occurrence_id_overlap":exact_occurrence,"provider_source_id_overlap":provider_ids,"exact_taxon_coordinate_date_overlap":composite,"records_only_in_legacy":len(legacy)-len(matched_legacy),"records_only_in_current":len(current)-len(matched_current),"taxonomy_differences":taxonomy_differences,"coordinate_differences":coordinate_differences,"date_differences":date_differences,"boundary_reconciliation":{"inside":sum(c.boundary_reconciliation=="INSIDE_OR_ON_BOUNDARY" for c in current),"outside":sum(c.boundary_reconciliation=="OUTSIDE_BOUNDARY" for c in current),"unresolved":sum(c.boundary_reconciliation=="UNRESOLVED" for c in current)},"provider_provenance_difference":"Legacy rows identify OBIS as source; governed candidates preserve OBIS as transport and record-level underlying provider metadata.","limitations":["Count changes may reflect provider updates, corrections, deletions, boundary geometry, taxonomy, or acquisition timing.","Additional records are review candidates and are not automatically valid production evidence."]}
 def _row(self,id):
  row=self.session.get(OccurrenceAcquisitionPreparation,id)
  if not row:raise ValueError("Occurrence preparation does not exist")
  return row
 def _candidates(self,preparation_id,ids=None):
  query=self.session.query(OccurrenceCandidateRecord).filter_by(preparation_id=preparation_id)
  if ids is not None:query=query.filter(OccurrenceCandidateRecord.id.in_(ids))
  rows=query.order_by(OccurrenceCandidateRecord.id).all()
  if ids is not None and len(rows)!=len(set(ids)):raise ValueError("Candidate selection is invalid")
  return rows
 def _summary(self,records):
  def value(record,key):return record.get(key,"PENDING_REVIEW") if isinstance(record,dict) else getattr(record,key)
  result={"total":len(records),"taxonomy":{},"boundary":{},"overlap":{},"review":{}}
  for record in records:
   for section,key in (("taxonomy","taxonomy_reconciliation"),("boundary","boundary_reconciliation"),("overlap","overlap_classification"),("review","review_status")):
    item=value(record,key);result[section][item]=result[section].get(item,0)+1
  return result
