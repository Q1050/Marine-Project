"""Retry only existing eligible, unacquired Commons candidates."""
import json
from database import SessionLocal
from models import IdentificationMediaAsset, IdentificationMediaSource, Species
from identification_corpus_service import IdentificationCorpusService, LocalArtifactStore, TRAINING_LICENSES
from platform_config import settings
from wikimedia_media_adapter import WikimediaCommonsAdapter

def main():
 session=SessionLocal()
 try:
  source=session.query(IdentificationMediaSource).filter_by(registration_key="WIKIMEDIA_COMMONS_MEDIA_V1").one();taxon=session.query(Species).filter_by(scientific_name="Pterois volitans").one();targets=session.query(IdentificationMediaAsset).filter_by(media_source_id=source.id,taxon_id=taxon.id,quality_state="NOT_ACQUIRED").filter(IdentificationMediaAsset.license_classification.in_(TRAINING_LICENSES)).all();adapter=WikimediaCommonsAdapter();manifest=adapter.acquire(None,taxon.scientific_name,limit=10);records={str(row["provider_asset_identifier"]):row for row in manifest.records};service=IdentificationCorpusService(session,LocalArtifactStore(settings.artifact_directory));results=[]
  for asset in targets:
   record=records.get(str(asset.provider_asset_identifier))
   if not record:
    service.retry_acquisition(asset,error="Candidate identity was not returned by the bounded provider query",response_metadata={"provider":"Wikimedia Commons","retrieved":manifest.retrieved});results.append({"asset_id":asset.id,"status":"FAILED","reason":asset.acquisition_last_error});continue
   try:
    data,media_type=adapter.download(record["image_url"]);service.retry_acquisition(asset,data=data,media_type=media_type,response_metadata={"provider":"Wikimedia Commons","source_reference":record["source_reference"],"media_type":media_type});results.append({"asset_id":asset.id,"status":"ACQUIRED","retry_count":asset.acquisition_retry_count})
   except Exception as exc:
    service.retry_acquisition(asset,error=str(exc),response_metadata={"provider":"Wikimedia Commons","source_reference":record["source_reference"]});results.append({"asset_id":asset.id,"status":"FAILED","retry_count":asset.acquisition_retry_count,"reason":asset.acquisition_last_error})
  print(json.dumps({"eligible_unacquired":len(targets),"results":results,"substitutions":0},indent=2))
 finally:session.close()
if __name__=="__main__":main()
