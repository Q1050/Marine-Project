"""Bounded, idempotent Pterois multi-source validation. Never approves media or runs models."""
import json
from database import SessionLocal
from models import Region, Species, User
from platform_config import settings
from identification_corpus_service import (AcquisitionRunService, IdentificationCorpusPlanService,
 IdentificationCorpusService, LocalArtifactStore, MediaSourceGovernanceService, corpus_readiness_for_taxon)
from wikimedia_media_adapter import WikimediaCommonsAdapter

SOURCE={"registration_key":"WIKIMEDIA_COMMONS_MEDIA_V1","scientific_provider":"Wikimedia Commons","transport_interface":"MEDIAWIKI_API","documentation_reference":"https://www.mediawiki.org/wiki/API:Imageinfo","licensing_model":"ITEM_LEVEL_EXTMETADATA","attribution_requirements":"Preserve creator, source page, license name, and license URL","access_method":"CONTROLLED_API","taxonomic_scope":{"query_context_only":True},"geographic_scope":{"global_identification_media":True},"provider_version":"MediaWiki API","acquisition_configuration":{"maximum_candidates":10,"thumbnail_width":1280,"bounded_concurrency":1,"request_delay_seconds":0.25},"provenance":{"upstream":"Wikimedia Commons","interface":"official MediaWiki API"},"limitations":["Search context is not authoritative taxonomic identification.","Every asset requires human scientific review.","Share-alike and unknown rights fail closed."]}

def main(limit=10):
 session=SessionLocal()
 try:
  admin=session.query(User).filter_by(is_platform_admin=True).order_by(User.id).first()
  region=session.query(Region).filter_by(slug="caribbean").one();taxon=session.query(Species).filter_by(scientific_name="Pterois volitans").one()
  if not admin:raise RuntimeError("A real active platform administrator is required for governed source registration")
  governance=MediaSourceGovernanceService(session);source=governance.register(SOURCE,admin.id)
  if source.lifecycle_state=="READY_FOR_REVIEW":governance.transition(source,"APPROVED",admin.id,"Milestone 18 official-API and fail-closed license review")
  if source.lifecycle_state=="APPROVED":governance.transition(source,"ACTIVE",admin.id,"Milestone 18 bounded validation activation")
  plan_payload={"plan_key":"caribbean-marine-identification","version":"m18-v1","region_id":region.id,"taxonomic_groups":["fish","algae/seaweed","crustaceans","molluscs","cnidarians","echinoderms","other"],"preferred_providers":["GBIF","WIKIMEDIA_COMMONS"],"licensing_policy":{"eligible":["PUBLIC_DOMAIN","TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"],"fail_closed":True,"noncommercial":"REFERENCE_ONLY","share_alike":"REVIEW_REQUIRED"},"quality_policy":{"minimum_width":64,"minimum_height":64,"signature_validation":True},"duplicate_policy":{"exact_sha256":True,"perceptual_review_distance":6,"auto_merge_perceptual":False},"provenance":{"milestone":"18","regional_taxonomy_only":True},"limitations":["Production currently has one approved regional taxon; no taxa were fabricated."],"configuration":{"future_target_taxa":{"minimum":100,"maximum":300}},"taxa":[{"taxon_id":taxon.id,"taxonomic_group":"fish","desired_candidate_count":30,"minimum_usable_count":10,"preferred_providers":["GBIF","WIKIMEDIA_COMMONS"]}]}
  plan=IdentificationCorpusPlanService(session).create(plan_payload,admin.id)
  request={"provider":"WIKIMEDIA_COMMONS","scientific_name":taxon.scientific_name,"limit":limit,"plan_fingerprint":plan.fingerprint};runs=AcquisitionRunService(session);run=runs.prepare(source.id,taxon.id,request,admin.id)
  if run.workflow_state=="COMPLETED":return print(json.dumps({"status":"IDEMPOTENT_NO_OP","run_id":run.id,"readiness":corpus_readiness_for_taxon(session,taxon.id)},indent=2))
  claimed=runs.claim("milestone18-controlled-worker",run_id=run.id);adapter=WikimediaCommonsAdapter();manifest=adapter.acquire(None,taxon.scientific_name,limit=limit);service=IdentificationCorpusService(session,LocalArtifactStore(settings.artifact_directory));summary={"found":manifest.retrieved,"usable_license":0,"restricted_license":0,"acquired":0,"failures":0,"exact_duplicates":0,"likely_duplicates":0,"review_required":0,"excluded":0}
  for record in manifest.records:
   eligible=record["license"]["training_eligible"];summary["usable_license" if eligible else "restricted_license"]+=1;data=None
   if eligible:
    try:data,record["media_type"]=adapter.download(record["image_url"]);summary["acquired"]+=1
    except Exception:summary["failures"]+=1
   payload={**record,"media_source_id":source.id,"taxon_id":taxon.id,"license_classification":record["license"]["license_classification"]}
   asset=service.create_candidate(payload,admin.id,data=data)
   summary["exact_duplicates"]+=asset.duplicate_state=="EXACT_DUPLICATE";summary["likely_duplicates"]+=asset.duplicate_state=="LIKELY_DUPLICATE";summary["review_required"]+=asset.review_state in {"READY_FOR_REVIEW","REVIEW_REQUIRED","TAXONOMY_REVIEW_REQUIRED"};summary["excluded"]+=asset.review_state=="EXCLUDED"
  runs.complete(claimed,claimed.claim_token,{"provider":manifest.provider,"retrieved":manifest.retrieved,"end_of_records":manifest.end_of_records,"summary":summary,"warnings":list(manifest.warnings)});summary.update({"run_id":run.id,"plan_id":plan.id,"plan_state":plan.lifecycle_state,"readiness":corpus_readiness_for_taxon(session,taxon.id),"scientific_approval_count":0,"benchmark_started":False});print(json.dumps(summary,indent=2))
 finally:session.close()

if __name__=="__main__":main()
