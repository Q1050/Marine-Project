"""Governed visual-corpus services.  Media availability is not jurisdiction evidence."""
from __future__ import annotations
import hashlib, io, json, random, shutil, uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image
from sqlalchemy import func, or_
from jurisdiction_boundary_registry import canonical_json
from models import (ArtifactReference, IdentificationCorpus, IdentificationCorpusInclusion,
    IdentificationMediaAcquisitionRun, IdentificationMediaAsset, IdentificationMediaSource,
    IdentificationMediaReviewEvent, IdentificationBenchmarkRun, IdentificationCorpusPlan,
    IdentificationCorpusPlanTaxon, RegionalTaxonRegistry, Species)

SOURCE_STATES={"READY_FOR_REVIEW":{"APPROVED","REJECTED"},"APPROVED":{"ACTIVE","REJECTED"},"ACTIVE":{"DEACTIVATED","SUPERSEDED"},"DEACTIVATED":{"ACTIVE","SUPERSEDED"}}
TRAINING_LICENSES={"PUBLIC_DOMAIN","TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"}
TAXONOMIC_GROUPS={"fish","algae/seaweed","crustaceans","molluscs","cnidarians","echinoderms","other"}
SUPPORTED_TYPES={"image/jpeg":"JPEG","image/png":"PNG","image/webp":"WEBP"}
PERCEPTUAL_ALGORITHM="DHASH-64";PERCEPTUAL_VERSION="1";PERCEPTUAL_REVIEW_DISTANCE=6

def fingerprint(value): return hashlib.sha256(canonical_json(value).encode()).hexdigest()
def perceptual_hash(data):
 with Image.open(io.BytesIO(data)) as image:
  pixels=list(image.convert("L").resize((9,8),Image.Resampling.LANCZOS).getdata())
 value=sum((pixels[row*9+column]>pixels[row*9+column+1])<<(row*8+column) for row in range(8) for column in range(8))
 return f"{value:016x}"
def perceptual_distance(first,second):return (int(first,16)^int(second,16)).bit_count()

class LocalArtifactStore:
 def __init__(self,root):self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
 def _path(self,key):
  path=(self.root/key).resolve()
  if self.root not in path.parents:raise ValueError("Invalid artifact key")
  return path
 def put(self,data,logical_key):
  digest=hashlib.sha256(data).hexdigest();path=self._path(f"{logical_key}/{digest}");path.parent.mkdir(parents=True,exist_ok=True)
  if not path.exists():path.write_bytes(data)
  return {"logical_key":str(path.relative_to(self.root)).replace("\\","/"),"sha256":digest,"size_bytes":len(data)}
 def open(self,key):return self._path(key).open("rb")
 def exists(self,key):return self._path(key).is_file()
 def retire(self,key,retired_root="retired"):
  source=self._path(key);target=self._path(f"{retired_root}/{key}");target.parent.mkdir(parents=True,exist_ok=True);shutil.move(source,target);return str(target.relative_to(self.root)).replace("\\","/")

class MediaSourceGovernanceService:
 def __init__(self,session):self.session=session
 def register(self,payload,user_id):
  config={k:payload.get(k) for k in ("registration_key","scientific_provider","transport_interface","documentation_reference","licensing_model","attribution_requirements","access_method","taxonomic_scope","geographic_scope","provider_version","acquisition_configuration","provenance","limitations")};fp=fingerprint(config)
  existing=self.session.query(IdentificationMediaSource).filter_by(registration_key=payload["registration_key"],configuration_fingerprint=fp).one_or_none()
  if existing:return existing
  row=IdentificationMediaSource(registration_key=payload["registration_key"],scientific_provider=payload["scientific_provider"],transport_interface=payload.get("transport_interface"),documentation_reference=payload["documentation_reference"],licensing_model=payload["licensing_model"],attribution_requirements=payload["attribution_requirements"],access_method=payload["access_method"],taxonomic_scope_json=canonical_json(payload.get("taxonomic_scope") or {}),geographic_scope_json=canonical_json(payload.get("geographic_scope") or {}),provider_version=payload.get("provider_version"),acquisition_configuration_json=canonical_json(payload.get("acquisition_configuration") or {}),provenance_json=canonical_json(payload.get("provenance") or {}),limitations_json=canonical_json(payload.get("limitations") or []),configuration_fingerprint=fp,created_by_user_id=user_id)
  self.session.add(row);self.session.commit();return row
 def transition(self,row,target,user_id,reference):
  if target not in SOURCE_STATES.get(row.lifecycle_state,set()):raise ValueError("Invalid media-source lifecycle transition")
  now=datetime.now(timezone.utc);row.lifecycle_state=target;row.reviewed_by_user_id=user_id;row.approval_reference=reference
  if target=="APPROVED":row.approved_at=now
  elif target=="ACTIVE":row.activated_at=now
  elif target=="DEACTIVATED":row.deactivated_at=now
  self.session.commit();return row
 def payload(self,row):return {"id":row.id,"registration_key":row.registration_key,"scientific_provider":row.scientific_provider,"transport_interface":row.transport_interface,"documentation_reference":row.documentation_reference,"licensing_model":row.licensing_model,"attribution_requirements":row.attribution_requirements,"access_method":row.access_method,"provider_version":row.provider_version,"configuration_fingerprint":row.configuration_fingerprint,"lifecycle_state":row.lifecycle_state,"limitations":json.loads(row.limitations_json)}

class MediaQualityValidator:
 def __init__(self,configuration=None):self.configuration={"minimum_width":None,"minimum_height":None,"maximum_aspect_ratio":20,**(configuration or {})}
 def validate(self,data,declared_media_type):
  result={"configuration":self.configuration,"configuration_version":"media-quality-v1"}
  if not data:return "ZERO_BYTE",result
  try:
   with Image.open(io.BytesIO(data)) as image:
    image.verify();width,height=image.size;fmt=image.format
   result.update(width_px=width,height_px=height,format=fmt,aspect_ratio=max(width/height,height/width))
   if declared_media_type not in SUPPORTED_TYPES or SUPPORTED_TYPES[declared_media_type]!=fmt:return "UNSUPPORTED_FORMAT",result
   if result["aspect_ratio"]>self.configuration["maximum_aspect_ratio"]:return "EXTREME_ASPECT_RATIO",result
   if self.configuration["minimum_width"] and width<self.configuration["minimum_width"]:return "BELOW_CONFIGURED_RESOLUTION",result
   if self.configuration["minimum_height"] and height<self.configuration["minimum_height"]:return "BELOW_CONFIGURED_RESOLUTION",result
   return "VALID",result
  except Exception as exc:return "CORRUPT_OR_UNREADABLE",{**result,"error":type(exc).__name__}

class IdentificationCorpusService:
 def __init__(self,session,store=None):self.session=session;self.store=store
 def create_corpus(self,payload,user_id):
  config={"corpus_key":payload["corpus_key"],"version":payload["version"],"intended_purpose":payload["intended_purpose"],"taxonomic_scope":payload.get("taxonomic_scope") or {},"configuration":payload.get("configuration") or {},"provenance":payload.get("provenance") or {},"limitations":payload.get("limitations") or []};fp=fingerprint(config)
  existing=self.session.query(IdentificationCorpus).filter_by(fingerprint=fp).one_or_none()
  if existing:return existing
  row=IdentificationCorpus(corpus_key=payload["corpus_key"],version=payload["version"],intended_purpose=payload["intended_purpose"],taxonomic_scope_json=canonical_json(config["taxonomic_scope"]),provenance_json=canonical_json(config["provenance"]),limitations_json=canonical_json(config["limitations"]),configuration_json=canonical_json(config["configuration"]),fingerprint=fp,created_by_user_id=user_id)
  self.session.add(row);self.session.commit();return row
 def include_assets(self,corpus_id,asset_ids,user_id,seed="visual-corpus-v1",split_recommended=True):
  corpus=self.session.get(IdentificationCorpus,corpus_id)
  if not corpus or corpus.lifecycle_state!="DRAFT":raise ValueError("Only a draft corpus may be changed")
  assets=self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.id.in_(asset_ids)).all()
  if len(assets)!=len(set(asset_ids)):raise ValueError("One or more assets do not exist")
  blocked=[a.id for a in assets if a.review_state!="APPROVED" or a.license_classification not in TRAINING_LICENSES or a.quality_state!="VALID" or a.duplicate_state not in {"UNIQUE","DISTINCT"}]
  if blocked:raise ValueError(f"Assets are not corpus eligible: {blocked}")
  assignments=self.deterministic_split(asset_ids,seed) if split_recommended else [{"asset_id":a.id,"group_key":a.perceptual_group or f"asset:{a.id}","split":"REFERENCE"} for a in assets]
  for item in assignments:
   identity={"corpus_id":corpus_id,"media_asset_id":item["asset_id"],"split":item["split"],"group":item["group_key"],"split_version":seed};fp=fingerprint(identity)
   if not self.session.query(IdentificationCorpusInclusion).filter_by(corpus_id=corpus_id,media_asset_id=item["asset_id"]).first():self.session.add(IdentificationCorpusInclusion(corpus_id=corpus_id,media_asset_id=item["asset_id"],split_name=item["split"],split_group_key=item["group_key"],split_version=seed,inclusion_fingerprint=fp,created_by_user_id=user_id))
  self.session.commit();return assignments
 def corpus_payload(self,corpus):
  return {"id":corpus.id,"corpus_key":corpus.corpus_key,"version":corpus.version,"intended_purpose":corpus.intended_purpose,"lifecycle_state":corpus.lifecycle_state,"fingerprint":corpus.fingerprint,"approved_at":corpus.approved_at,"created_at":corpus.created_at,"limitations":json.loads(corpus.limitations_json)}
 def create_candidate(self,payload,user_id,data=None,quality_configuration=None):
  source=self.session.get(IdentificationMediaSource,payload["media_source_id"]);taxon=self.session.get(Species,payload["taxon_id"])
  if not source or source.lifecycle_state!="ACTIVE":raise ValueError("Active governed media source required")
  if not taxon:raise ValueError("Governed taxon required")
  if not self.session.query(RegionalTaxonRegistry).filter_by(taxon_id=taxon.id,review_status="APPROVED").first():raise ValueError("Taxon is not regionally governed")
  existing=self.session.query(IdentificationMediaAsset).filter_by(media_source_id=source.id,provider_asset_identifier=payload["provider_asset_identifier"]).one_or_none()
  if existing:return existing
  digest=hashlib.sha256(data).hexdigest() if data is not None else payload.get("sha256");artifact=None;quality="NOT_ACQUIRED";meta={}
  if data is not None:
   quality,meta=MediaQualityValidator(quality_configuration).validate(data,payload["media_type"])
   stored=self.store.put(data,f"identification/{taxon.id}") if self.store else None
   if stored:
    artifact=self.session.query(ArtifactReference).filter_by(sha256=stored["sha256"]).one_or_none()
    if not artifact:artifact=ArtifactReference(local_path=stored["logical_key"],sha256=stored["sha256"],media_type=payload["media_type"],artifact_type="IDENTIFICATION_MEDIA",size_bytes=stored["size_bytes"],provider=source.scientific_provider,source_reference=payload["source_reference"]);self.session.add(artifact);self.session.flush()
  duplicate=self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.sha256==digest).first() if digest else None
  phash=perceptual_hash(data) if data and quality=="VALID" else None;likely=None;distance=None
  if phash and not duplicate:
   for candidate in self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.perceptual_hash.is_not(None)).all():
    current=perceptual_distance(phash,candidate.perceptual_hash)
    if distance is None or current<distance:distance=current;likely=candidate
   if distance is not None and distance<=PERCEPTUAL_REVIEW_DISTANCE:likely=likely
   else:likely=None
  license_class=payload.get("license_classification","LICENSE_UNRESOLVED")
  review="EXCLUDED" if license_class not in TRAINING_LICENSES or quality not in {"VALID","NOT_ACQUIRED"} else "READY_FOR_REVIEW"
  identity={"source":source.id,"provider_asset_identifier":payload["provider_asset_identifier"],"taxon_id":taxon.id,"sha256":digest,"source_event_identifier":payload.get("source_event_identifier"),"specimen_identifier":payload.get("specimen_identifier")}
  duplicate_state="EXACT_DUPLICATE" if duplicate else "LIKELY_DUPLICATE" if likely else "DISTINCT"
  meta.update({"perceptual_algorithm":PERCEPTUAL_ALGORITHM,"perceptual_version":PERCEPTUAL_VERSION,"nearest_perceptual_distance":distance,"review_threshold":PERCEPTUAL_REVIEW_DISTANCE})
  row=IdentificationMediaAsset(stable_asset_key=f"{source.registration_key}:{payload['provider_asset_identifier']}",taxon_id=taxon.id,media_source_id=source.id,provider_asset_identifier=payload["provider_asset_identifier"],source_reference=payload["source_reference"],creator=payload.get("creator"),license_expression=payload.get("license_expression","UNRESOLVED"),license_classification=license_class,attribution_text=payload.get("attribution_text") or "Attribution unresolved",media_type=payload["media_type"],artifact_reference_id=artifact.id if artifact else None,sha256=digest,width_px=meta.get("width_px"),height_px=meta.get("height_px"),size_bytes=len(data) if data is not None else payload.get("size_bytes"),acquired_at=datetime.now(timezone.utc) if data is not None else None,source_metadata_json=canonical_json(payload.get("source_metadata") or {}),life_stage=payload.get("life_stage"),sex=payload.get("sex"),view_orientation=payload.get("view_orientation"),biological_context=payload.get("biological_context"),locality=payload.get("locality"),event_date=payload.get("event_date"),source_event_identifier=payload.get("source_event_identifier"),specimen_identifier=payload.get("specimen_identifier"),taxonomic_linkage=payload.get("taxonomic_linkage","EXACT_GOVERNED_TAXON"),taxonomic_confidence_source=payload.get("taxonomic_confidence_source"),quality_state=quality,quality_metadata_json=canonical_json(meta),exact_duplicate_of_id=duplicate.id if duplicate else None,perceptual_hash=phash,perceptual_hash_algorithm=f"{PERCEPTUAL_ALGORITHM}:{PERCEPTUAL_VERSION}",perceptual_group=f"phash:{likely.perceptual_hash}" if likely else (f"phash:{phash}" if phash else None),duplicate_state=duplicate_state,review_state=review,exclusion_reason="License or quality blocks training review" if review=="EXCLUDED" else None,provenance_fingerprint=fingerprint(identity))
  self.session.add(row);self.session.commit();return row
 def retry_acquisition(self,row,data=None,media_type=None,error=None,response_metadata=None,quality_configuration=None):
  if row.review_state=="APPROVED":raise ValueError("Approved assets cannot be replaced by acquisition retry")
  row.acquisition_retry_count=(row.acquisition_retry_count or 0)+1;row.acquisition_response_json=canonical_json(response_metadata or {})
  if error or data is None:
   row.acquisition_last_error=str(error or "No media bytes returned");self.session.commit();return row
  quality,meta=MediaQualityValidator(quality_configuration).validate(data,media_type or row.media_type)
  if quality!="VALID":
   row.quality_state=quality;row.quality_metadata_json=canonical_json(meta);row.acquisition_last_error=f"Technical validation failed: {quality}";self.session.commit();return row
  digest=hashlib.sha256(data).hexdigest();duplicate=self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.id!=row.id,IdentificationMediaAsset.sha256==digest).first();phash=perceptual_hash(data);likely=None;distance=None
  if not duplicate:
   for candidate in self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.id!=row.id,IdentificationMediaAsset.perceptual_hash.is_not(None)).all():
    current=perceptual_distance(phash,candidate.perceptual_hash)
    if distance is None or current<distance:distance=current;likely=candidate
   if distance is None or distance>PERCEPTUAL_REVIEW_DISTANCE:likely=None
  source=self.session.get(IdentificationMediaSource,row.media_source_id);stored=self.store.put(data,f"identification/{row.taxon_id}") if self.store else None
  if stored:
   artifact=self.session.query(ArtifactReference).filter_by(sha256=stored["sha256"]).one_or_none()
   if not artifact:artifact=ArtifactReference(local_path=stored["logical_key"],sha256=stored["sha256"],media_type=media_type or row.media_type,artifact_type="IDENTIFICATION_MEDIA",size_bytes=stored["size_bytes"],provider=source.scientific_provider,source_reference=row.source_reference);self.session.add(artifact);self.session.flush()
   row.artifact_reference_id=artifact.id
  row.media_type=media_type or row.media_type;row.sha256=digest;row.width_px=meta.get("width_px");row.height_px=meta.get("height_px");row.size_bytes=len(data);row.acquired_at=datetime.now(timezone.utc);row.quality_state="VALID";meta.update({"perceptual_algorithm":PERCEPTUAL_ALGORITHM,"perceptual_version":PERCEPTUAL_VERSION,"nearest_perceptual_distance":distance,"review_threshold":PERCEPTUAL_REVIEW_DISTANCE});row.quality_metadata_json=canonical_json(meta);row.perceptual_hash=phash;row.perceptual_hash_algorithm=f"{PERCEPTUAL_ALGORITHM}:{PERCEPTUAL_VERSION}";row.exact_duplicate_of_id=duplicate.id if duplicate else None;row.duplicate_state="EXACT_DUPLICATE" if duplicate else "LIKELY_DUPLICATE" if likely else "DISTINCT";row.perceptual_group=f"phash:{likely.perceptual_hash}" if likely else f"phash:{phash}";row.acquisition_last_error=None
  if row.license_classification in TRAINING_LICENSES:row.review_state="READY_FOR_REVIEW";row.exclusion_reason=None
  self.session.commit();return row
 def review(self,row,decision,user_id,reference):
  if row.review_state not in {"READY_FOR_REVIEW","REVIEW_REQUIRED"}:raise ValueError("Asset is not reviewable")
  if decision=="APPROVED":
   if row.license_classification not in TRAINING_LICENSES:raise ValueError("License is not explicitly training eligible")
   if row.taxonomic_linkage not in {"EXACT_GOVERNED_TAXON","SYNONYM_TO_GOVERNED_TAXON"}:raise ValueError("Taxonomic linkage blocks approval")
   if row.quality_state!="VALID" or row.duplicate_state not in {"UNIQUE","DISTINCT"}:raise ValueError("Quality/duplicate state blocks approval")
  elif decision not in {"EXCLUDED","TAXONOMY_REVIEW_REQUIRED","DUPLICATE","NEEDS_REVIEW"}:raise ValueError("Unsupported review decision")
  prior=row.review_state
  if decision=="DUPLICATE":row.review_state="EXCLUDED";row.duplicate_state="CONFIRMED_DUPLICATE";row.exclusion_reason=reference
  elif decision=="TAXONOMY_REVIEW_REQUIRED":row.review_state="TAXONOMY_REVIEW_REQUIRED"
  elif decision=="NEEDS_REVIEW":row.review_state="REVIEW_REQUIRED"
  else:row.review_state=decision;row.exclusion_reason=reference if decision=="EXCLUDED" else None
  row.reviewed_by_user_id=user_id;row.review_reference=reference;row.reviewed_at=datetime.now(timezone.utc)
  self.session.add(IdentificationMediaReviewEvent(media_asset_id=row.id,reviewer_user_id=user_id,action=decision,prior_review_state=prior,current_review_state=row.review_state,reason=reference,license_state=row.license_classification,duplicate_state=row.duplicate_state,quality_state=row.quality_state));self.session.commit();return row
 def transition_corpus(self,corpus,target,user_id,reference):
  allowed={"DRAFT":{"READY_FOR_REVIEW","REJECTED"},"READY_FOR_REVIEW":{"APPROVED","REJECTED"},"APPROVED":{"FROZEN","SUPERSEDED"},"FROZEN":{"SUPERSEDED"}}
  if target not in allowed.get(corpus.lifecycle_state,set()):raise ValueError("Invalid corpus lifecycle transition")
  if target in {"APPROVED","FROZEN"}:
   included=self.session.query(IdentificationCorpusInclusion).filter_by(corpus_id=corpus.id,inclusion_state="APPROVED").count()
   if not included:raise ValueError("Corpus has no approved inclusions")
  corpus.lifecycle_state=target;corpus.reviewed_by_user_id=user_id;corpus.approval_reference=reference
  if target=="APPROVED":corpus.approved_at=datetime.now(timezone.utc)
  if target=="SUPERSEDED":corpus.superseded_at=datetime.now(timezone.utc)
  self.session.commit();return corpus
 def training_readiness(self,corpus_id):
  corpus=self.session.get(IdentificationCorpus,corpus_id);manifest=self.export_manifest(corpus_id);assets=manifest["assets"]
  if corpus.lifecycle_state not in {"APPROVED","FROZEN"}:return {"state":"TRAINING_REVIEW_REQUIRED","reasons":["Corpus is not approved/frozen."]}
  if not assets:return {"state":"NOT_READY","reasons":["No approved training-eligible assets."]}
  splits={a["split"] for a in assets}
  if not {"VALIDATION","TEST"}&splits:return {"state":"BENCHMARK_READY","reasons":["Reference corpus exists but independent evaluation split is unavailable."]}
  return {"state":"TRAINING_READY" if corpus.lifecycle_state=="FROZEN" else "TRAINING_REVIEW_REQUIRED","reasons":["Governed labels, licenses, and grouped splits are available."]}
 def coverage(self,region_id,page=1,page_size=100,search=None):
  taxa=self.session.query(Species).join(RegionalTaxonRegistry,RegionalTaxonRegistry.taxon_id==Species.id).filter(RegionalTaxonRegistry.region_id==region_id,RegionalTaxonRegistry.review_status=="APPROVED",RegionalTaxonRegistry.superseded_at.is_(None))
  if search:taxa=taxa.filter(func.lower(Species.scientific_name).like(f"%{search.casefold()}%"))
  total=taxa.count();taxa=taxa.order_by(Species.scientific_name).offset((page-1)*page_size).limit(page_size).all();ids=[t.id for t in taxa]
  assets=self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.taxon_id.in_(ids or [-1])).all();by=defaultdict(list)
  for a in assets:by[a.taxon_id].append(a)
  items=[]
  for taxon in taxa:
   rows=by[taxon.id];approved=[r for r in rows if r.review_state=="APPROVED"]
   eligible=[r for r in approved if r.license_classification in TRAINING_LICENSES and r.quality_state=="VALID" and r.duplicate_state in {"UNIQUE","DISTINCT"}]
   if not rows:state="NO_MEDIA";reason="No governed identification-media candidates."
   elif any(r.license_classification not in TRAINING_LICENSES for r in rows) and not eligible:state="LICENSE_BLOCKED";reason="No explicitly training-eligible licensed assets."
   elif not approved:state="REVIEW_REQUIRED";reason="Candidates require governed review."
   else:state="READY_FOR_CORPUS_PREPARATION";reason="Approved eligible assets exist; diversity still requires corpus review."
   items.append({"taxon_id":taxon.id,"scientific_name":taxon.scientific_name,"state":state,"reason":reason,"candidate_assets":len(rows),"approved_assets":len(approved),"training_eligible":len(eligible),"excluded":sum(r.review_state=="EXCLUDED" for r in rows),"duplicates":sum(r.duplicate_state not in {"UNIQUE","DISTINCT"} for r in rows),"unique_providers":len({r.media_source_id for r in rows}),"unique_events_or_specimens":len({r.source_event_identifier or r.specimen_identifier for r in rows if r.source_event_identifier or r.specimen_identifier}),"life_stages":dict(Counter(r.life_stage or "UNKNOWN" for r in rows)),"quality":dict(Counter(r.quality_state for r in rows))})
  return {"region_id":region_id,"page":page,"page_size":page_size,"total":total,"items":items,"semantics":"Regional identification support does not establish jurisdiction presence or ecology."}
 def review_progress(self,region_id,taxon_id=None):
  query=self.session.query(IdentificationMediaAsset,Species,IdentificationMediaSource).join(Species,Species.id==IdentificationMediaAsset.taxon_id).join(IdentificationMediaSource,IdentificationMediaSource.id==IdentificationMediaAsset.media_source_id).join(RegionalTaxonRegistry,RegionalTaxonRegistry.taxon_id==Species.id).filter(RegionalTaxonRegistry.region_id==region_id,RegionalTaxonRegistry.review_status=="APPROVED",RegionalTaxonRegistry.superseded_at.is_(None))
  if taxon_id:query=query.filter(IdentificationMediaAsset.taxon_id==taxon_id)
  grouped=defaultdict(list)
  for asset,taxon,source in query.all():grouped[(taxon.id,taxon.scientific_name)].append((asset,source))
  items=[]
  for (identifier,name),rows in sorted(grouped.items(),key=lambda item:item[0][1]):
   assets=[row[0] for row in rows];approved=[a for a in assets if a.review_state=="APPROVED"];events={a.source_event_identifier or a.specimen_identifier or f"asset:{a.id}" for a in approved};localities={a.locality for a in approved if a.locality};dates={a.event_date.date().isoformat() for a in approved if a.event_date};eligible=[a for a in assets if a.license_classification in TRAINING_LICENSES]
   items.append({"taxon_id":identifier,"scientific_name":name,"readiness":corpus_readiness_for_taxon(self.session,identifier),"candidates":len(assets),"license_eligible":len(eligible),"human_approved":len(approved),"excluded":sum(a.review_state=="EXCLUDED" for a in assets),"needs_review":sum(a.review_state in {"READY_FOR_REVIEW","REVIEW_REQUIRED","TAXONOMY_REVIEW_REQUIRED"} for a in assets),"unique_providers":len({source.id for _,source in rows}),"provider_distribution":dict(Counter(source.scientific_provider for _,source in rows)),"independent_approved_events":len(events),"duplicate_groups":len({a.perceptual_group for a in assets if a.perceptual_group}),"locality_diversity":len(localities),"date_diversity":len(dates),"contexts":dict(Counter(a.biological_context or "UNKNOWN" for a in approved)),"life_stages":dict(Counter(a.life_stage or "UNKNOWN" for a in approved))})
  return {"region_id":region_id,"items":items,"semantics":"Human approval and source independence are categorical evidence; no readiness percentage is calculated."}
 def deterministic_split(self,asset_ids,seed="visual-corpus-v1",ratios=(0.7,0.15,0.15)):
  assets=self.session.query(IdentificationMediaAsset).filter(IdentificationMediaAsset.id.in_(asset_ids)).all();groups=defaultdict(list)
  for a in assets:groups[(f"event:{a.source_event_identifier}" if a.source_event_identifier else None) or (f"specimen:{a.specimen_identifier}" if a.specimen_identifier else None) or a.perceptual_group or (f"sha:{a.sha256}" if a.sha256 else None) or f"asset:{a.id}"].append(a)
  result=[]
  for key in sorted(groups):
   value=int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:16],16)/16**16;split="TRAIN" if value<ratios[0] else "VALIDATION" if value<sum(ratios[:2]) else "TEST"
   result.extend({"asset_id":a.id,"group_key":key,"split":split} for a in groups[key])
  return result
 def export_manifest(self,corpus_id):
  corpus=self.session.get(IdentificationCorpus,corpus_id);rows=self.session.query(IdentificationCorpusInclusion,IdentificationMediaAsset,Species).join(IdentificationMediaAsset,IdentificationMediaAsset.id==IdentificationCorpusInclusion.media_asset_id).join(Species,Species.id==IdentificationMediaAsset.taxon_id).filter(IdentificationCorpusInclusion.corpus_id==corpus_id,IdentificationCorpusInclusion.inclusion_state=="APPROVED").all()
  assets=[]
  for inclusion,asset,taxon in rows:
   if asset.review_state!="APPROVED" or asset.license_classification not in TRAINING_LICENSES:continue
   assets.append({"asset_key":asset.stable_asset_key,"taxon_id":taxon.id,"scientific_name":taxon.scientific_name,"split":inclusion.split_name,"source_reference":asset.source_reference,"provider_asset_identifier":asset.provider_asset_identifier,"sha256":asset.sha256,"license":asset.license_expression,"license_classification":asset.license_classification,"creator":asset.creator,"attribution":asset.attribution_text,"biological_metadata":{"life_stage":asset.life_stage,"sex":asset.sex,"view_orientation":asset.view_orientation,"context":asset.biological_context},"source_event_identifier":asset.source_event_identifier,"specimen_identifier":asset.specimen_identifier})
  manifest={"corpus_key":corpus.corpus_key,"corpus_version":corpus.version,"corpus_fingerprint":corpus.fingerprint,"assets":sorted(assets,key=lambda x:x["asset_key"]),"semantics":"Governed identification labels; not jurisdiction occurrence evidence."};manifest["export_fingerprint"]=fingerprint(manifest);return manifest

class IdentificationBenchmarkService:
 def __init__(self,session):self.session=session
 def prepare(self,payload,user_id):
  corpus=self.session.get(IdentificationCorpus,payload["corpus_id"])
  if not corpus or corpus.lifecycle_state!="FROZEN":raise ValueError("Benchmark requires a frozen corpus")
  gate=self.quality_gate(corpus.id)
  if gate["state"]!="BENCHMARK_READY":raise ValueError(f"PRETRAINED_BENCHMARK_NOT_JUSTIFIED: {', '.join(gate['reasons'])}")
  dependency={k:payload.get(k) for k in ("model_identity","model_hash","model_version","corpus_id","split_name","inference_configuration")};fp=fingerprint(dependency)
  row=self.session.query(IdentificationBenchmarkRun).filter_by(run_fingerprint=fp).one_or_none()
  if row:return row
  row=IdentificationBenchmarkRun(model_identity=payload["model_identity"],model_hash=payload.get("model_hash"),model_version=payload["model_version"],corpus_id=corpus.id,split_name=payload["split_name"],inference_configuration_json=canonical_json(payload.get("inference_configuration") or {}),run_fingerprint=fp,created_by_user_id=user_id);self.session.add(row);self.session.commit();return row
 def quality_gate(self,corpus_id):
  corpus=self.session.get(IdentificationCorpus,corpus_id)
  if not corpus or corpus.lifecycle_state!="FROZEN":return {"state":"REVIEW_REQUIRED","reasons":["Corpus is not frozen."]}
  rows=self.session.query(IdentificationCorpusInclusion,IdentificationMediaAsset).join(IdentificationMediaAsset,IdentificationMediaAsset.id==IdentificationCorpusInclusion.media_asset_id).filter(IdentificationCorpusInclusion.corpus_id==corpus_id,IdentificationCorpusInclusion.inclusion_state=="APPROVED").all();reasons=[]
  if not rows:reasons.append("No reviewed benchmark assets.")
  if any(asset.review_state!="APPROVED" for _,asset in rows):reasons.append("Corpus includes media without human approval.")
  if any(asset.quality_state!="VALID" or asset.license_classification not in TRAINING_LICENSES for _,asset in rows):reasons.append("Corpus includes technically or legally blocked media.")
  groups=defaultdict(set)
  for inclusion,asset in rows:groups[asset.taxon_id].add(inclusion.split_group_key or asset.source_event_identifier or asset.specimen_identifier or asset.perceptual_group or f"asset:{asset.id}")
  if any(not values for values in groups.values()):reasons.append("Independent source grouping is unavailable.")
  return {"state":"BENCHMARK_READY" if not reasons else "PRETRAINED_BENCHMARK_NOT_JUSTIFIED","reasons":reasons,"taxa":len(groups),"assets":len(rows),"independent_groups":sum(len(values) for values in groups.values())}
 def complete(self,row,metrics,taxon_results=None,confusion=None,rejection_behavior=None):
  if row.workflow_state!="PREPARED":raise ValueError("Only a prepared benchmark may complete")
  row.metrics_json=canonical_json(metrics);row.taxon_results_json=canonical_json(taxon_results or {});row.confusion_json=canonical_json(confusion or {});row.rejection_behavior_json=canonical_json(rejection_behavior or {});row.workflow_state="COMPLETED";row.completed_at=datetime.now(timezone.utc);self.session.commit();return row

class IdentificationCorpusPlanService:
 def __init__(self,session):self.session=session
 def create(self,payload,user_id):
  groups=set(payload.get("taxonomic_groups") or [])
  if not groups or not groups<=TAXONOMIC_GROUPS:raise ValueError("Plan contains unsupported taxonomic groups")
  region_id=payload["region_id"]
  governed={r.taxon_id for r in self.session.query(RegionalTaxonRegistry).filter_by(region_id=region_id,review_status="APPROVED").filter(RegionalTaxonRegistry.superseded_at.is_(None)).all()}
  requested={int(item["taxon_id"]) for item in payload.get("taxa") or []}
  if not requested<=governed:raise ValueError("A plan may contain only currently governed regional taxa")
  config={k:payload.get(k) for k in ("plan_key","version","region_id","taxonomic_groups","preferred_providers","licensing_policy","quality_policy","duplicate_policy","provenance","limitations","configuration","taxa")};fp=fingerprint(config)
  existing=self.session.query(IdentificationCorpusPlan).filter_by(fingerprint=fp).one_or_none()
  if existing:return existing
  row=IdentificationCorpusPlan(plan_key=payload["plan_key"],version=payload["version"],region_id=region_id,taxonomic_groups_json=canonical_json(sorted(groups)),preferred_providers_json=canonical_json(payload.get("preferred_providers") or []),licensing_policy_json=canonical_json(payload.get("licensing_policy") or {}),quality_policy_json=canonical_json(payload.get("quality_policy") or {}),duplicate_policy_json=canonical_json(payload.get("duplicate_policy") or {}),provenance_json=canonical_json(payload.get("provenance") or {}),limitations_json=canonical_json(payload.get("limitations") or []),configuration_json=canonical_json(payload.get("configuration") or {}),fingerprint=fp,created_by_user_id=user_id);self.session.add(row);self.session.flush()
  for item in payload.get("taxa") or []:
   if item["taxonomic_group"] not in TAXONOMIC_GROUPS:raise ValueError("Unsupported taxonomic group")
   desired=int(item.get("desired_candidate_count",30));minimum=int(item.get("minimum_usable_count",10))
   if minimum<1 or desired<minimum:raise ValueError("Candidate targets must be positive and desired >= minimum")
   self.session.add(IdentificationCorpusPlanTaxon(plan_id=row.id,taxon_id=item["taxon_id"],taxonomic_group=item["taxonomic_group"],desired_candidate_count=desired,minimum_usable_count=minimum,preferred_providers_json=canonical_json(item.get("preferred_providers") or payload.get("preferred_providers") or [])))
  self.session.commit();return row
 def transition(self,row,target,user_id,reference):
  allowed={"DRAFT":{"READY_FOR_REVIEW"},"READY_FOR_REVIEW":{"APPROVED","REJECTED"},"APPROVED":{"ACTIVE","SUPERSEDED"},"ACTIVE":{"SUPERSEDED"}}
  if target not in allowed.get(row.lifecycle_state,set()):raise ValueError("Invalid corpus-plan lifecycle transition")
  now=datetime.now(timezone.utc);row.lifecycle_state=target;row.reviewed_by_user_id=user_id;row.approval_reference=reference
  if target=="APPROVED":row.approved_at=now
  elif target=="ACTIVE":row.activated_at=now
  elif target=="SUPERSEDED":row.superseded_at=now
  self.session.commit();return row
 def payload(self,row):
  taxa=self.session.query(IdentificationCorpusPlanTaxon).filter_by(plan_id=row.id).order_by(IdentificationCorpusPlanTaxon.id).all()
  return {"id":row.id,"plan_key":row.plan_key,"version":row.version,"region_id":row.region_id,"lifecycle_state":row.lifecycle_state,"taxonomic_groups":json.loads(row.taxonomic_groups_json),"preferred_providers":json.loads(row.preferred_providers_json),"licensing_policy":json.loads(row.licensing_policy_json),"quality_policy":json.loads(row.quality_policy_json),"duplicate_policy":json.loads(row.duplicate_policy_json),"provenance":json.loads(row.provenance_json),"limitations":json.loads(row.limitations_json),"fingerprint":row.fingerprint,"taxa":[{"taxon_id":t.taxon_id,"taxonomic_group":t.taxonomic_group,"desired_candidate_count":t.desired_candidate_count,"minimum_usable_count":t.minimum_usable_count,"preferred_providers":json.loads(t.preferred_providers_json),"readiness_state":corpus_readiness_for_taxon(self.session,t.taxon_id)} for t in taxa]}

def corpus_readiness_for_taxon(session,taxon_id):
 sources=session.query(IdentificationMediaSource).filter_by(lifecycle_state="ACTIVE").count();runs=session.query(IdentificationMediaAcquisitionRun).filter_by(taxon_id=taxon_id).all();assets=session.query(IdentificationMediaAsset).filter_by(taxon_id=taxon_id).all()
 if not sources:return "NO_MEDIA_SOURCE"
 if any(r.workflow_state in {"PENDING","CLAIMED"} for r in runs):return "ACQUISITION_IN_PROGRESS"
 if not assets:return "ACQUISITION_READY"
 if any(a.review_state in {"READY_FOR_REVIEW","REVIEW_REQUIRED","TAXONOMY_REVIEW_REQUIRED"} for a in assets):return "REVIEW_REQUIRED"
 approved=[a for a in assets if a.review_state=="APPROVED"]
 if not approved:return "INSUFFICIENT_REVIEWED_MEDIA"
 corpora=session.query(IdentificationCorpus).join(IdentificationCorpusInclusion).join(IdentificationMediaAsset).filter(IdentificationMediaAsset.taxon_id==taxon_id,IdentificationCorpus.lifecycle_state=="FROZEN").all()
 if not corpora:return "INSUFFICIENT_REVIEWED_MEDIA"
 if session.query(IdentificationBenchmarkRun).filter(IdentificationBenchmarkRun.corpus_id.in_([c.id for c in corpora]),IdentificationBenchmarkRun.workflow_state=="COMPLETED").first():return "BENCHMARKED"
 return "BENCHMARK_READY"

class AcquisitionRunService:
 def __init__(self,session):self.session=session
 def prepare(self,source_id,taxon_id,request,user_id):
  fp=fingerprint({"source_id":source_id,"taxon_id":taxon_id,"request":request});row=self.session.query(IdentificationMediaAcquisitionRun).filter_by(run_fingerprint=fp).one_or_none()
  if row:return row
  row=IdentificationMediaAcquisitionRun(media_source_id=source_id,taxon_id=taxon_id,run_fingerprint=fp,request_json=canonical_json(request),created_by_user_id=user_id);self.session.add(row);self.session.commit();return row
 def claim(self,worker,lease_minutes=15,run_id=None):
  now=datetime.now(timezone.utc);query=self.session.query(IdentificationMediaAcquisitionRun).filter(or_(IdentificationMediaAcquisitionRun.workflow_state.in_(["PENDING","FAILED"]),IdentificationMediaAcquisitionRun.lease_expires_at<now)).order_by(IdentificationMediaAcquisitionRun.id)
  if run_id is not None:query=query.filter(IdentificationMediaAcquisitionRun.id==run_id)
  if self.session.bind.dialect.name=="postgresql":query=query.with_for_update(skip_locked=True)
  row=query.first()
  if not row:return None
  row.workflow_state="CLAIMED";row.claim_token=uuid.uuid4().hex;row.claimed_by=worker;row.claimed_at=now;row.lease_expires_at=now+timedelta(minutes=lease_minutes);self.session.commit();return row
 def complete(self,row,token,manifest):
  if row.workflow_state!="CLAIMED" or row.claim_token!=token:raise ValueError("Claim token mismatch")
  row.workflow_state="COMPLETED";row.provider_manifest_json=canonical_json(manifest);row.completed_at=datetime.now(timezone.utc);row.lease_expires_at=None;self.session.commit();return row
 def fail(self,row,token,error):
  if row.claim_token!=token:raise ValueError("Claim token mismatch")
  row.workflow_state="FAILED";row.retry_count+=1;row.last_error=error;row.claim_token=None;row.lease_expires_at=None;self.session.commit();return row
