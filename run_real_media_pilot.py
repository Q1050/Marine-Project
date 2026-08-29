"""Run the bounded, review-first GBIF identification-media pilot."""
from __future__ import annotations
import argparse,json
from datetime import datetime
from database import SessionLocal,IS_POSTGRESQL
from gbif_media_adapter import GBIFMediaAdapter
from identification_corpus_service import AcquisitionRunService,IdentificationCorpusService,LocalArtifactStore,MediaSourceGovernanceService
from models import RegionalTaxonRegistry,Species,User
from platform_config import settings

SOURCE={"registration_key":"GBIF_OCCURRENCE_MEDIA_V1","scientific_provider":"Global Biodiversity Information Facility (GBIF)","transport_interface":"GBIF API v1 occurrence/search","documentation_reference":"https://techdocs.gbif.org/en/openapi/","licensing_model":"Item-level Creative Commons media license; CC0/CC BY eligible for training review; all others fail closed","attribution_requirements":"Retain creator, publisher/dataset provenance, occurrence reference, and item license","access_method":"HTTPS JSON API and bounded media download","taxonomic_scope":{"provider":"GBIF","query":"exact governed taxon key"},"geographic_scope":{"scope":"GLOBAL_IDENTIFICATION_REFERENCE","jurisdiction_evidence":False},"provider_version":"GBIF_API_V1","acquisition_configuration":{"maximum_candidates":25,"default_candidates":15,"page_size":10,"timeout_seconds":25,"maximum_image_bytes":15000000,"minimum_dimensions":[224,224],"maximum_aspect_ratio":6},"provenance":{"terms":"https://www.gbif.org/terms/data-user","citation":"https://www.gbif.org/citation-guidelines"},"limitations":["Occurrence identification is provider-supplied and remains subject to governed taxonomic review.","Media license is evaluated item by item.","Identification media is not jurisdiction occurrence or ecological evidence."]}

def json_safe(value):
 if isinstance(value,datetime):return value.isoformat()
 if isinstance(value,dict):return {k:json_safe(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
 return value

def run(limit=15):
 if not IS_POSTGRESQL:raise RuntimeError("The controlled production pilot requires the authoritative PostgreSQL DATABASE_URL")
 db=SessionLocal()
 try:
  admin=db.query(User).filter_by(is_platform_admin=True,status="ACTIVE").order_by(User.id).first()
  taxon=db.query(Species).filter_by(scientific_name="Pterois volitans").one()
  if not admin:raise RuntimeError("An active platform administrator is required")
  if not db.query(RegionalTaxonRegistry).filter_by(taxon_id=taxon.id,review_status="APPROVED").first():raise RuntimeError("Pterois volitans is not an approved regional taxon")
  governance=MediaSourceGovernanceService(db);source=governance.register(SOURCE,admin.id)
  if source.lifecycle_state=="READY_FOR_REVIEW":governance.transition(source,"APPROVED",admin.id,"Milestone 17B source review: GBIF item-level licensing and API terms")
  if source.lifecycle_state=="APPROVED":governance.transition(source,"ACTIVE",admin.id,"Milestone 17B bounded production pilot activation")
  request={"taxon_key":2334438,"scientific_name":"Pterois volitans","limit":limit,"page_size":10};runs=AcquisitionRunService(db);acquisition=runs.prepare(source.id,taxon.id,request,admin.id)
  if acquisition.workflow_state=="COMPLETED":return {"source_id":source.id,"run_id":acquisition.id,"state":"ALREADY_COMPLETED","manifest":json.loads(acquisition.provider_manifest_json)}
  claimed=runs.claim("manual-milestone17b-pilot",run_id=acquisition.id)
  if not claimed or claimed.id!=acquisition.id:raise RuntimeError("Pilot run could not be claimed safely")
  adapter=GBIFMediaAdapter();manifest=adapter.acquire(2334438,"Pterois volitans",limit=limit,page_size=10);service=IdentificationCorpusService(db,LocalArtifactStore(settings.artifact_directory));outcomes=[]
  for record in manifest.records:
   license_info=record.pop("license");payload={**record,"media_source_id":source.id,"taxon_id":taxon.id,"license_classification":license_info["license_classification"],"taxonomic_confidence_source":"GBIF taxonKey 2334438 exact match"};data=None;error=None
   if license_info["training_eligible"]:
    try:data,actual_type=adapter.download(payload.pop("image_url"));payload["media_type"]=actual_type or payload["media_type"]
    except Exception as exc:error=f"{type(exc).__name__}: {exc}"
   else:payload.pop("image_url",None)
   if error:outcomes.append({"provider_asset_identifier":payload["provider_asset_identifier"],"state":"DOWNLOAD_FAILED","error":error});continue
   asset=service.create_candidate(payload,admin.id,data=data,quality_configuration={"minimum_width":224,"minimum_height":224,"maximum_aspect_ratio":6});outcomes.append({"asset_id":asset.id,"state":asset.review_state,"license":asset.license_classification,"quality":asset.quality_state,"duplicate":asset.duplicate_state,"taxonomic_linkage":asset.taxonomic_linkage})
  report={"query":manifest.query,"retrieved":manifest.retrieved,"end_of_records":manifest.end_of_records,"provider_version":manifest.provider_version,"outcomes":outcomes,"review_required":sum(x.get("state")=="READY_FOR_REVIEW" for x in outcomes),"excluded":sum(x.get("state")=="EXCLUDED" for x in outcomes),"failed":sum(x.get("state")=="DOWNLOAD_FAILED" for x in outcomes)}
  runs.complete(claimed,claimed.claim_token,json_safe(report));return {"source_id":source.id,"run_id":claimed.id,"state":"COMPLETED","manifest":report}
 except Exception:
  db.rollback();raise
 finally:db.close()

if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("--limit",type=int,default=15,choices=range(1,26));args=parser.parse_args();print(json.dumps(json_safe(run(args.limit)),indent=2))
