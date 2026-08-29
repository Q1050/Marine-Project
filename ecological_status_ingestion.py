"""Controlled CSV/JSON ecological-list ingestion into the Phase 12D-1 workflow."""
import csv,hashlib,io,json,re
from datetime import datetime,timezone
from pathlib import Path
from jurisdiction_boundary_registry import canonical_json
from occurrence_evidence_service import _hash,_date
from ecological_status_governance import CONFLICT_PAIRS,EcologicalStatusGovernanceService,VALID_STATUSES
from models import *

PARSER_VERSION="ecological-status-list-parser-v1";MAX_BYTES=5*1024*1024;MEDIA={"text/csv":"csv","application/csv":"csv","application/json":"json","text/json":"json"}
class EcologicalStatusIngestionService:
 def __init__(self,session,artifact_root="artifacts/ecological_status_sources"):self.session=session;self.root=Path(artifact_root)
 def parse(self,data,filename,media_type):
  if not data or len(data)>MAX_BYTES:raise ValueError("Artifact is empty or exceeds the 5 MiB limit")
  suffix=Path(filename or "").suffix.lower();kind=MEDIA.get(media_type) or ("csv" if suffix==".csv" else "json" if suffix==".json" else None)
  if not kind:raise ValueError("Only CSV and JSON artifacts are accepted")
  try:
   text=data.decode("utf-8-sig")
   if kind=="csv":rows=[dict(row) for row in csv.DictReader(io.StringIO(text))]
   else:
    value=json.loads(text);rows=value.get("records") if isinstance(value,dict) else value
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError("JSON must be an array of objects or an object containing records")
  except (UnicodeDecodeError,csv.Error,json.JSONDecodeError) as exc:raise ValueError(f"Malformed {kind.upper()} artifact: {exc}") from exc
  fields=sorted({key for row in rows for key in row});proposals={target:target for target in ("scientific_name","authoritative_taxon_identifier","common_name","source_status","effective_date","notes","source_record_identifier","jurisdiction") if target in fields}
  return {"kind":kind,"rows":rows,"available_fields":fields,"proposed_mapping":proposals,"warnings":[] if rows else ["Artifact contains no data rows."]}
 def preflight(self,source_id,jurisdiction_id,data,filename,media_type,mapping=None):
  source=self._source(source_id);jurisdiction=self.session.get(Jurisdiction,jurisdiction_id)
  if not jurisdiction:raise ValueError("Jurisdiction does not exist")
  parsed=self.parse(data,filename,media_type);mapping=mapping or json.loads(source.field_mapping_json)
  missing=[key for key in ("scientific_name","source_status") if not mapping.get(key)]
  if missing:return {"write_performed":False,"mapping_status":"REVIEW_REQUIRED","available_fields":parsed["available_fields"],"proposed_mapping":parsed["proposed_mapping"],"errors":[f"Required mapping missing: {key}" for key in missing],"rows":[],"counts":{}}
  results=[self._row(source,jurisdiction,row,index+1,mapping) for index,row in enumerate(parsed["rows"])];counts={}
  for row in results:counts[row["preflight_classification"]]=counts.get(row["preflight_classification"],0)+1
  return {"write_performed":False,"mapping_status":"APPROVED_CONFIGURATION" if mapping==json.loads(source.field_mapping_json) else "EXPLICIT_REQUEST_MAPPING","available_fields":parsed["available_fields"],"proposed_mapping":parsed["proposed_mapping"],"warnings":parsed["warnings"],"errors":[],"rows":results,"counts":counts,"artifact_sha256":hashlib.sha256(data).hexdigest(),"byte_size":len(data)}
 def create_run(self,source_id,jurisdiction_id,data,filename,media_type,user_id,mapping=None):
  source=self._source(source_id);result=self.preflight(source_id,jurisdiction_id,data,filename,media_type,mapping);mapping=mapping or json.loads(source.field_mapping_json)
  if result.get("errors"):raise ValueError("Artifact mapping is not ready")
  digest=result["artifact_sha256"];content=_hash(result["rows"]);run_fp=_hash({"source":[source.id,source.configuration_fingerprint],"jurisdiction":jurisdiction_id,"artifact":digest,"content":content,"mapping":mapping,"semantics":json.loads(source.semantic_mapping_json),"parser":PARSER_VERSION});existing=self.session.query(EcologicalStatusIngestionRun).filter_by(run_fingerprint=run_fp).one_or_none()
  if existing:return self.detail(existing.id)|{"rerun_status":"NO-OP"}
  self.root.mkdir(parents=True,exist_ok=True);safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(filename or "artifact").name)[:120];path=self.root/f"{digest[:16]}-{safe}";path.write_bytes(data)
  run=EcologicalStatusIngestionRun(source_registration_id=source.id,jurisdiction_id=jurisdiction_id,original_filename=safe,media_type=media_type,byte_size=len(data),artifact_sha256=digest,artifact_reference=str(path),parser_version=PARSER_VERSION,normalized_content_fingerprint=content,mapping_json=canonical_json(mapping),semantic_mapping_json=source.semantic_mapping_json,warnings_json=canonical_json(result.get("warnings") or []),errors_json="[]",provenance_json=canonical_json({"source_configuration_fingerprint":source.configuration_fingerprint,"source_reference":source.source_reference,"uploaded_at":datetime.now(timezone.utc).isoformat()}),limitations_json=source.limitations_json,source_row_count=len(result["rows"]),run_fingerprint=run_fp,workflow_status="READY_FOR_REVIEW",operator_user_id=user_id);self.session.add(run);self.session.flush()
  for value in result["rows"]:self.session.add(EcologicalStatusIngestionRow(ingestion_run_id=run.id,source_row_number=value["source_row_number"],source_record_identifier=value.get("source_record_identifier"),raw_row_json=canonical_json(value["raw_row"]),normalized_scientific_name=value.get("scientific_name"),common_name=value.get("common_name"),submitted_taxon_identifier=value.get("submitted_taxon_identifier"),reconciled_taxon_id=value.get("taxon_id"),taxonomy_result=value["taxonomy_result"],jurisdiction_result=value["jurisdiction_result"],source_status=value.get("source_status"),semantic_result=value["semantic_result"],proposed_statuses_json=canonical_json(value["proposed_statuses"]),conflict_state=value["conflict_state"],preflight_classification=value["preflight_classification"],effective_date=_date(value.get("effective_date")),notes=value.get("notes"),row_fingerprint=_hash({"run":run_fp,"row":value}),review_status="REVIEW_REQUIRED",apply_status="NOT_APPLIED"))
  self.session.commit();return self.detail(run.id)
 def review(self,run_id,row_ids,disposition,user_id,reference):
  if disposition not in {"APPROVED","REJECTED","UNRESOLVED","ROUTE_TO_TAXONOMY_REVIEW"}:raise ValueError("Invalid ingestion review disposition")
  run=self._run(run_id);rows=self._rows(run.id,row_ids);results=[]
  for row in rows:
   if disposition=="APPROVED" and row.preflight_classification not in {"READY","CONFLICT_WITH_EXISTING_STATUS"}:results.append({"row_id":row.id,"status":"REFUSED","reason":row.preflight_classification});continue
   row.review_status=disposition;row.reviewer_user_id=user_id;row.review_reference=reference;row.reviewed_at=datetime.now(timezone.utc);self.session.add(EcologicalStatusIngestionReview(ingestion_row_id=row.id,reviewer_user_id=user_id,disposition=disposition,review_reference=reference,dependency_fingerprint=_hash({"run":run.run_fingerprint,"row":row.row_fingerprint,"disposition":disposition,"reference":reference}),source_license_reference=self._source(run.source_registration_id).license,resulting_assertion_ids_json="[]"));results.append({"row_id":row.id,"status":disposition})
  self.session.commit();return {"results":results,"run":self.detail(run.id)}
 def apply(self,run_id,row_ids=None):
  run=self._run(run_id);source=self._source(run.source_registration_id);query=self.session.query(EcologicalStatusIngestionRow).filter_by(ingestion_run_id=run.id,review_status="APPROVED")
  if row_ids is not None:query=query.filter(EcologicalStatusIngestionRow.id.in_(row_ids))
  rows=[row for row in query.order_by(EcologicalStatusIngestionRow.id) if row.apply_status!="APPLIED"]
  if not rows:return {"apply_status":"NO-OP","run":self.detail(run.id),"results":[]}
  authority=json.loads(source.expected_semantics_json).get("authority_classification","REVIEW_REQUIRED")
  if authority!="AUTHORITATIVE_FOR_JURISDICTION":raise ValueError("Source semantics are not authoritative for jurisdiction apply")
  payload={"jurisdiction_id":run.jurisdiction_id,"source_organization":source.source_organization,"source_title":source.source_title,"source_version":source.source_version,"publication_date":source.publication_date.isoformat() if source.publication_date else None,"source_reference":source.source_reference,"evidence_type":json.loads(source.expected_semantics_json).get("evidence_type","OTHER_REVIEWED_SOURCE"),"authority_classification":authority,"geographic_scope":{"type":"JURISDICTION","jurisdiction_id":run.jurisdiction_id,"source_registration_id":source.id,"ingestion_run_id":run.id,"artifact_sha256":run.artifact_sha256},"limitations":json.loads(run.limitations_json),"assertions":[{"scientific_name":row.normalized_scientific_name,"authoritative_identifier_scheme":None,"authoritative_identifier":None,"statuses":json.loads(row.proposed_statuses_json),"effective_from":row.effective_date.isoformat() if row.effective_date else None,"notes":f"ingestion_run:{run.id}; ingestion_row:{row.id}; source_record:{row.source_record_identifier}"} for row in rows]}
  d1=EcologicalStatusGovernanceService(self.session)
  try:
   prepared=d1.prepare(payload,run.operator_user_id);candidate_ids=[item["id"] for item in prepared["candidates"]];d1.approve(prepared["id"],candidate_ids,run.operator_user_id,f"ingestion-run:{run.id}");applied=d1.apply(prepared["id"])
   results=[]
   for row in rows:
    row.apply_status="APPLIED";row.ecological_preparation_id=prepared["id"];row.last_error=None;assertion_ids=[item.id for item in self.session.query(EcologicalStatusAssertion).filter_by(preparation_id=prepared["id"]).all()];self.session.add(EcologicalStatusIngestionReview(ingestion_row_id=row.id,reviewer_user_id=row.reviewer_user_id or run.operator_user_id,disposition="APPLIED",review_reference=f"ingestion-run:{run.id}",dependency_fingerprint=_hash({"run":run.run_fingerprint,"row":row.row_fingerprint,"assertions":assertion_ids}),source_license_reference=source.license,resulting_assertion_ids_json=canonical_json(assertion_ids)));results.append({"row_id":row.id,"status":"APPLIED","preparation_id":prepared["id"]})
   remaining=self.session.query(EcologicalStatusIngestionRow).filter_by(ingestion_run_id=run.id,review_status="APPROVED",apply_status="NOT_APPLIED").count();run.workflow_status="APPLIED" if not remaining else "PARTIALLY_APPLIED";run.applied_at=datetime.now(timezone.utc);self.session.commit();return {"apply_status":run.workflow_status,"results":results,"assertion_ids":applied.get("assertion_ids",[]),"run":self.detail(run.id)}
  except Exception as exc:
   self.session.rollback();run=self._run(run_id)
   for row in self._rows(run.id,row_ids):
    if row.review_status=="APPROVED" and row.apply_status!="APPLIED":row.apply_status="FAILED";row.last_error=str(exc)
   run.workflow_status="FAILED";run.last_error=str(exc);self.session.commit();raise
 def retry(self,run_id,row_ids):
  for row in self._rows(run_id,row_ids):
   if row.apply_status=="FAILED":row.apply_status="NOT_APPLIED";row.last_error=None
  run=self._run(run_id);run.workflow_status="READY_FOR_REVIEW";run.last_error=None;self.session.commit();return self.apply(run_id,row_ids)
 def version_comparison(self,source_id,new_run_id):
  new=self._run(new_run_id);prior=self.session.query(EcologicalStatusIngestionRun).filter(EcologicalStatusIngestionRun.source_registration_id==source_id,EcologicalStatusIngestionRun.id!=new.id).order_by(EcologicalStatusIngestionRun.id.desc()).first()
  if not prior:return {"prior_run_id":None,"added":new.source_row_count,"removed":0,"removed_item_interpretation":"NONE"}
  old_names={row.normalized_scientific_name for row in self._rows(prior.id)};new_names={row.normalized_scientific_name for row in self._rows(new.id)};return {"prior_run_id":prior.id,"added_items":sorted(new_names-old_names),"removed_items":[{"scientific_name":name,"classification":"REVIEW_REQUIRED_FOR_STATUS_CHANGE"} for name in sorted(old_names-new_names)],"removed_item_interpretation":"No eradication, absence, or reversal is inferred."}
 def detail(self,id,include_rows=True):
  run=self._run(id);value={"id":run.id,"source_registration_id":run.source_registration_id,"jurisdiction_id":run.jurisdiction_id,"artifact":{"filename":run.original_filename,"media_type":run.media_type,"byte_size":run.byte_size,"sha256":run.artifact_sha256},"parser_version":run.parser_version,"normalized_content_fingerprint":run.normalized_content_fingerprint,"source_row_count":run.source_row_count,"workflow_status":run.workflow_status,"warnings":json.loads(run.warnings_json),"errors":json.loads(run.errors_json),"last_error":run.last_error,"created_at":run.created_at,"applied_at":run.applied_at}
  if include_rows:value["rows"]=[self.row_payload(row) for row in self._rows(run.id)]
  return value
 def row_payload(self,row):return {"id":row.id,"source_row_number":row.source_row_number,"source_record_identifier":row.source_record_identifier,"scientific_name":row.normalized_scientific_name,"common_name":row.common_name,"taxon_id":row.reconciled_taxon_id,"taxonomy_result":row.taxonomy_result,"jurisdiction_result":row.jurisdiction_result,"source_status":row.source_status,"semantic_result":row.semantic_result,"proposed_statuses":json.loads(row.proposed_statuses_json),"conflict_state":row.conflict_state,"preflight_classification":row.preflight_classification,"review_status":row.review_status,"apply_status":row.apply_status,"notes":row.notes,"last_error":row.last_error,"review_history":[{"disposition":item.disposition,"review_reference":item.review_reference,"dependency_fingerprint":item.dependency_fingerprint,"source_license_reference":item.source_license_reference,"resulting_assertion_ids":json.loads(item.resulting_assertion_ids_json),"created_at":item.created_at} for item in self.session.query(EcologicalStatusIngestionReview).filter_by(ingestion_row_id=row.id).order_by(EcologicalStatusIngestionReview.id).all()]}
 def _row(self,source,jurisdiction,raw,number,mapping):
  get=lambda key:raw.get(mapping.get(key)) if mapping.get(key) else None;name=str(get("scientific_name") or "").strip();identifier=str(get("authoritative_taxon_identifier") or "").strip() or None;taxon=self.session.query(Species).filter_by(authoritative_identifier=identifier).one_or_none() if identifier else self.session.query(Species).filter(Species.scientific_name.ilike(name)).one_or_none();taxon=taxon.accepted_taxon if taxon and taxon.accepted_taxon else taxon
  governed=taxon and self.session.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id,taxon_id=taxon.id,review_status="APPROVED").first();taxonomy="EXACT_GOVERNED_TAXON" if governed else "TAXON_NOT_GOVERNED" if not taxon or not governed else "UNRESOLVED"
  jurisdiction_value=str(get("jurisdiction") or "").strip().casefold();jurisdiction_match=jurisdiction_value in {jurisdiction.name.casefold(),(jurisdiction.country_code or "").casefold(),jurisdiction.slug.casefold()}
  if source.scope_type=="JURISDICTION_SPECIFIC":geo="EXACT_JURISDICTION_SCOPE" if source.jurisdiction_id==jurisdiction.id else "JURISDICTION_CONFLICT"
  elif source.scope_type=="REGIONAL":geo="EXACT_JURISDICTION_SCOPE" if jurisdiction_match else "REGIONAL_ONLY"
  elif source.scope_type=="GLOBAL":geo="EXACT_JURISDICTION_SCOPE" if jurisdiction_match else "GLOBAL_ONLY"
  else:geo="EXACT_JURISDICTION_SCOPE" if jurisdiction_match else "UNRESOLVED_GEOGRAPHY"
  source_status=str(get("source_status") or "").strip();semantic_map=json.loads(source.semantic_mapping_json);mapped=semantic_map.get(source_status);proposed=sorted(set(mapped if isinstance(mapped,list) else [mapped] if mapped else []));semantic="READY" if proposed and set(proposed).issubset(VALID_STATUSES) else "INVALID_STATUS" if proposed else "UNMAPPED_SOURCE_STATUS"
  projection=EcologicalStatusGovernanceService(self.session).projection(jurisdiction.id,taxon.id) if taxon else {"statuses":[]};conflict="CONFLICT_WITH_EXISTING_STATUS" if any(pair.issubset(set(proposed)|set(projection["statuses"])) for pair in CONFLICT_PAIRS) else "NONE"
  classification="READY"
  if taxonomy!="EXACT_GOVERNED_TAXON":classification=taxonomy
  elif geo!="EXACT_JURISDICTION_SCOPE":classification="JURISDICTION_MISMATCH"
  elif semantic!="READY":classification=semantic
  elif conflict!="NONE":classification=conflict
  return {"source_row_number":number,"source_record_identifier":get("source_record_identifier"),"raw_row":raw,"scientific_name":name,"common_name":get("common_name"),"submitted_taxon_identifier":identifier,"taxon_id":taxon.id if taxon else None,"taxonomy_result":taxonomy,"jurisdiction_result":geo,"source_status":source_status,"semantic_result":semantic,"proposed_statuses":proposed,"conflict_state":conflict,"preflight_classification":classification,"effective_date":get("effective_date"),"notes":get("notes")}
 def _source(self,id):
  row=self.session.get(EcologicalStatusSourceRegistration,id)
  if not row or row.workflow_status!="ACTIVE":raise ValueError("Ecological-status source is not ACTIVE")
  return row
 def _run(self,id):
  row=self.session.get(EcologicalStatusIngestionRun,id)
  if not row:raise ValueError("Ecological-status ingestion run does not exist")
  return row
 def _rows(self,run_id,ids=None):
  q=self.session.query(EcologicalStatusIngestionRow).filter_by(ingestion_run_id=run_id)
  if ids is not None:q=q.filter(EcologicalStatusIngestionRow.id.in_(ids))
  rows=q.order_by(EcologicalStatusIngestionRow.id).all()
  if ids is not None and len(rows)!=len(set(ids)):raise ValueError("Ingestion row selection is invalid")
  return rows
