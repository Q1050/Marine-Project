"""Generic governed OBIS v3 occurrence adapter with complete pagination."""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import requests
from shapely.geometry import box,shape
from jurisdiction_boundary_registry import canonical_json
from occurrence_evidence_service import OccurrenceSourceAdapter,OccurrenceSourceContract,SourceAcquisition

OBIS_OCCURRENCE_API="https://api.obis.org/v3/occurrence"

def _safe(value):return None if value is None or str(value).strip()=="" else value

class OBISOccurrenceAdapter(OccurrenceSourceAdapter):
 def __init__(self,registration,http=None,artifact_root="artifacts/occurrence/obis"):
  if registration.workflow_status!="ACTIVE":raise ValueError("Occurrence source registration is not ACTIVE")
  self.registration=registration;self.http=http or requests;self.artifact_root=Path(artifact_root);config=json.loads(registration.configuration_json);self.page_size=int(config.get("page_size",1000));self.api_url=config.get("api_url",OBIS_OCCURRENCE_API)
  self.contract=OccurrenceSourceContract(registration.source_registration_id,registration.scientific_provider,registration.transport_interface,registration.provider_dataset_id or "RECORD_LEVEL_DATASETS",registration.provider_dataset_version,registration.documentation_reference,registration.license,registration.reuse_conditions,json.loads(registration.geographic_scope_json).get("description","Provider query constrained by governed boundary"),tuple(json.loads(registration.limitations_json)))
 def acquire(self,jurisdiction,taxon,boundary):
  if not taxon.authoritative_identifier:raise ValueError("Taxon lacks an authoritative identifier")
  governed_geometry=shape(json.loads(boundary.geometry_json))
  # OBIS exposes occurrence search over GET; a high-resolution marine boundary can
  # exceed practical URL limits. Query its deterministic envelope, then let the
  # existing governed pipeline reconcile every point against the exact boundary.
  query_geometry=box(*governed_geometry.bounds).wkt
  params={"taxonid":taxon.authoritative_identifier,"geometry":query_geometry,"size":self.page_size,"offset":0}
  pages=[];raw=[];reported_total=None;offset=0
  while reported_total is None or offset<reported_total:
   page_params={**params,"offset":offset};response=self.http.get(self.api_url,params=page_params,timeout=90);response.raise_for_status();payload=response.json();results=payload.get("results") or []
   if reported_total is None:reported_total=int(payload.get("total") or 0)
   pages.append({"offset":offset,"records":len(results),"total":payload.get("total")})
   raw.extend(results)
   if not results:break
   offset+=len(results)
  if reported_total is None or len(raw)!=reported_total:raise RuntimeError(f"Incomplete OBIS acquisition: reported={reported_total}, retrieved={len(raw)}")
  seen=set();normalized=[];duplicates=malformed=0
  for record in raw:
   if not isinstance(record,dict):malformed+=1;continue
   stable=str(record.get("id") or record.get("occurrenceID") or "")
   if stable and stable in seen:duplicates+=1;continue
   if stable:seen.add(stable)
   normalized.append(self._normalize(record))
  acquired=datetime.now(timezone.utc);diagnostics={"pages_retrieved":len(pages),"pages":pages,"provider_reported_count":reported_total,"actual_records_retrieved":len(raw),"records_normalized":len(normalized),"malformed_records":malformed,"excluded_records":malformed,"duplicate_records":duplicates,"complete":True}
  artifact={"source_registration_id":self.registration.id,"source_configuration_fingerprint":self.registration.configuration_fingerprint,"request":{"taxon_id":taxon.authoritative_identifier,"jurisdiction_id":jurisdiction.id,"boundary_id":boundary.id,"boundary_geometry_hash":boundary.geometry_hash,"provider_query_geometry_method":"GOVERNED_BOUNDARY_ENVELOPE","parameters":params},"provider_response_metadata":diagnostics,"normalized_records":normalized,"acquired_at":acquired.isoformat(),"limitations":[*json.loads(self.registration.limitations_json),"Provider query uses the governed boundary envelope; exact boundary reconciliation occurs during candidate preparation."],"review_state":"CONTROLLED_PREPARATION_INPUT"}
  encoded=canonical_json(artifact).encode();digest=hashlib.sha256(encoded).hexdigest();self.artifact_root.mkdir(parents=True,exist_ok=True);path=self.artifact_root/f"{jurisdiction.slug}-{taxon.id}-{digest[:16]}.json";path.write_bytes(encoded)
  return SourceAcquisition(tuple(normalized),{"endpoint":self.api_url,"taxonid":str(taxon.authoritative_identifier),"boundary_id":boundary.id,"provider_query_geometry_method":"GOVERNED_BOUNDARY_ENVELOPE","page_size":self.page_size,"diagnostics":diagnostics},{"boundary_id":boundary.id,"geometry_hash":boundary.geometry_hash,"geometry_type":governed_geometry.geom_type,"provider_query_bounds":list(governed_geometry.bounds)},str(path),digest,acquired.isoformat())
 def _normalize(self,row):
  provider=self._underlying_provider(row)
  return {"provider_occurrence_id":_safe(row.get("id")),"upstream_occurrence_id":_safe(row.get("occurrenceID")),"event_id":_safe(row.get("eventID")),"catalog_specimen_id":_safe(row.get("catalogNumber") or row.get("materialSampleID")),"observation_reference":_safe(row.get("references") or row.get("occurrenceID")),"scientific_name":_safe(row.get("scientificName") or row.get("acceptedNameUsage")),"authoritative_identifier":str(row.get("AphiaID") or row.get("taxonID") or "") or None,"latitude":row.get("decimalLatitude"),"longitude":row.get("decimalLongitude"),"event_date":_safe(row.get("eventDate")),"basis_of_record":_safe(row.get("basisOfRecord")),"occurrence_status":_safe(row.get("occurrenceStatus")),"coordinate_uncertainty_m":row.get("coordinateUncertaintyInMeters"),"depth_m":row.get("minimumDepthInMeters") if row.get("minimumDepthInMeters") is not None else row.get("maximumDepthInMeters"),"locality":_safe(row.get("locality")),"original_record_reference":_safe(row.get("references") or row.get("occurrenceID")),"source_metadata":{"transport_interface":"OBIS","obis_dataset_id":_safe(row.get("dataset_id") or row.get("datasetID")),"dataset_name":_safe(row.get("datasetName")),"scientific_provider":provider,"provider_identity_status":"REPORTED" if provider else "UNDERLYING_PROVIDER_UNRESOLVED","institution_code":_safe(row.get("institutionCode")),"collection_code":_safe(row.get("collectionCode")),"node_id":_safe(row.get("node_id")),"license":_safe(row.get("license")),"original_source_fields":{key:row.get(key) for key in ("recordedBy","identifiedBy","type","scientificNameID","acceptedNameUsageID") if row.get(key) is not None}}}
 @staticmethod
 def _underlying_provider(row):return _safe(row.get("institutionCode") or row.get("institutionID") or row.get("ownerInstitutionCode") or row.get("datasetName"))
