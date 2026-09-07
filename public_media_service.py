"""Governed public media; observation evidence is private unless explicitly governed."""
from datetime import datetime,timezone
import json
from models import GovernedPublicMedia, IdentificationMediaAsset, IdentificationMediaSource

PUBLIC_REFERENCE_LICENSES = {"PUBLIC_DOMAIN", "ATTRIBUTION_REQUIRED"}
PUBLIC_REFERENCE_TAXONOMY = {"EXACT_GOVERNED_TAXON", "SYNONYM_TO_GOVERNED_TAXON"}

class PublicMediaService:
 def __init__(self,session):self.session=session
 def create(self,payload):
  if not payload.get("remote_url") and not payload.get("artifact_reference_id"):raise ValueError("Controlled media reference required")
  row=GovernedPublicMedia(**payload,lifecycle_state="READY_FOR_REVIEW",public_visibility="PRIVATE",is_primary=False);self.session.add(row);self.session.commit();return row
 def review(self,row,user_id,decision):
  if decision not in {"APPROVED","REJECTED"} or row.lifecycle_state!="READY_FOR_REVIEW":raise ValueError("Invalid media review transition")
  row.lifecycle_state=decision;row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);self.session.commit();return row
 def publish(self,row,primary=False):
  if row.lifecycle_state not in {"APPROVED","PUBLIC"}:raise ValueError("Only approved media may be public")
  if primary and not row.taxon_id:raise ValueError("Primary media requires a taxon")
  if primary:
   self.session.query(GovernedPublicMedia).filter_by(taxon_id=row.taxon_id,is_primary=True).update({"is_primary":False})
  row.lifecycle_state="PUBLIC";row.public_visibility="PUBLIC_APPROVED";row.is_primary=primary;self.session.commit();return row
 def reject(self,row,user_id):return self.review(row,user_id,"REJECTED")
 def public_for_taxon(self,taxon_id):return self.session.query(GovernedPublicMedia).filter_by(taxon_id=taxon_id,lifecycle_state="PUBLIC",public_visibility="PUBLIC_APPROVED").order_by(GovernedPublicMedia.is_primary.desc(),GovernedPublicMedia.id).all()
 def safe(self,row):return {"id":row.id,"media_type":row.media_type,"url":row.remote_url if row.remote_url and row.remote_url.startswith(("https://","http://")) else None,"creator":row.creator,"source_provider":row.source_provider,"source_reference":row.source_reference,"license":row.license,"attribution_text":row.attribution_text,"is_primary":row.is_primary,"limitations":__import__('json').loads(row.limitations_json)}
 def approved_reference_for_taxon(self,taxon_id):
  return self.session.query(IdentificationMediaAsset).filter(
   IdentificationMediaAsset.taxon_id==taxon_id,
   IdentificationMediaAsset.review_state=="APPROVED",
   IdentificationMediaAsset.license_classification.in_(PUBLIC_REFERENCE_LICENSES),
   IdentificationMediaAsset.quality_state=="VALID",
   IdentificationMediaAsset.duplicate_state.in_({"UNIQUE","DISTINCT"}),
   IdentificationMediaAsset.taxonomic_linkage.in_(PUBLIC_REFERENCE_TAXONOMY),
   IdentificationMediaAsset.artifact_reference_id.isnot(None),
   IdentificationMediaAsset.media_type.like("image/%"),
  ).order_by(IdentificationMediaAsset.id).all()
 def reference_is_public_eligible(self,row):
  return bool(row and row.review_state=="APPROVED" and row.license_classification in PUBLIC_REFERENCE_LICENSES and row.quality_state=="VALID" and row.duplicate_state in {"UNIQUE","DISTINCT"} and row.taxonomic_linkage in PUBLIC_REFERENCE_TAXONOMY and row.artifact_reference_id and row.media_type.startswith("image/"))
 def safe_reference(self,row):
  source=self.session.get(IdentificationMediaSource,row.media_source_id)
  metadata=json.loads(row.source_metadata_json or "{}")
  return {"id":row.id,"media_type":row.media_type,"url":f"/species/{row.taxon_id}/reference-media/{row.id}/content","creator":row.creator,"source_provider":source.scientific_provider if source else None,"source_reference":row.source_reference,"license":row.license_expression,"license_url":metadata.get("license_url") or (row.license_expression if row.license_expression.startswith(("https://","http://")) else None),"attribution_text":row.attribution_text,"life_stage":row.life_stage or None,"biological_context":row.biological_context or None}
