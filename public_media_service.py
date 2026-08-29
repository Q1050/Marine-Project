"""Governed public media; observation evidence is private unless explicitly governed."""
from datetime import datetime,timezone
from models import GovernedPublicMedia

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
