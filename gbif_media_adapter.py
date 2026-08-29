"""Bounded GBIF occurrence-media adapter with item-level license handling."""
from __future__ import annotations
import hashlib,time
from dataclasses import dataclass
from datetime import datetime
import requests

GBIF_API="https://api.gbif.org/v1"
LICENSES={
 "http://creativecommons.org/publicdomain/zero/1.0/":"TRAINING_ALLOWED","https://creativecommons.org/publicdomain/zero/1.0/":"TRAINING_ALLOWED",
 "http://creativecommons.org/licenses/by/4.0/":"ATTRIBUTION_REQUIRED","https://creativecommons.org/licenses/by/4.0/":"ATTRIBUTION_REQUIRED",
 "http://creativecommons.org/licenses/by-nc/4.0/":"NONCOMMERCIAL_RESTRICTION","https://creativecommons.org/licenses/by-nc/4.0/":"NONCOMMERCIAL_RESTRICTION",
 "http://creativecommons.org/licenses/by-sa/4.0/":"DERIVATIVES_RESTRICTED","https://creativecommons.org/licenses/by-sa/4.0/":"DERIVATIVES_RESTRICTED",
}
def normalize_gbif_license(value):
 raw=(value or "").strip();classification=LICENSES.get(raw,"LICENSE_UNRESOLVED")
 return {"raw_license":raw or None,"license_classification":classification,"training_eligible":classification in {"TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"},"attribution_required":classification=="ATTRIBUTION_REQUIRED","public_visibility_eligible":None,"limitations":[] if classification in {"TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"} else ["Not eligible for this training pilot without separate review."]}

def parse_event_date(value):
 if not value:return None
 try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
 except (TypeError,ValueError):return None

@dataclass(frozen=True)
class GBIFMediaManifest:
 query:dict;retrieved:int;end_of_records:bool;provider_version:str;records:tuple

class GBIFMediaAdapter:
 def __init__(self,session=None,timeout=25,max_bytes=15_000_000,delay_seconds=.2,retries=3):self.http=session or requests.Session();self.timeout=timeout;self.max_bytes=max_bytes;self.delay=delay_seconds;self.retries=retries
 def _get(self,url,**kwargs):
  last=None
  for attempt in range(self.retries):
   try:
    response=self.http.get(url,timeout=self.timeout,headers={"User-Agent":"MarineMonitoringVisualCorpus/17B"},**kwargs)
    if response.status_code in {429,500,502,503,504}:raise requests.HTTPError(f"provider status {response.status_code}")
    response.raise_for_status();return response
   except requests.RequestException as exc:last=exc;time.sleep(self.delay*(2**attempt))
  raise RuntimeError(f"GBIF request failed: {last}")
 def acquire(self,taxon_key,scientific_name,limit=25,page_size=10):
  if not 1<=limit<=25:raise ValueError("Controlled GBIF pilot limit must be 1-25")
  records=[];offset=0;end=False
  while len(records)<limit and not end:
   size=min(page_size,limit-len(records));payload=self._get(f"{GBIF_API}/occurrence/search",params={"taxon_key":taxon_key,"media_type":"StillImage","limit":size,"offset":offset}).json();end=bool(payload.get("endOfRecords"));offset+=len(payload.get("results",[]))
   for occurrence in payload.get("results",[]):
    if occurrence.get("taxonKey")!=taxon_key:continue
    for media in occurrence.get("media") or []:
     if media.get("type")!="StillImage" or not media.get("identifier"):continue
     license_info=normalize_gbif_license(media.get("license"));identifier=media["identifier"]
     records.append({"provider_asset_identifier":hashlib.sha256(identifier.encode()).hexdigest(),"provider_occurrence_id":str(occurrence.get("key")),"source_event_identifier":occurrence.get("eventID") or occurrence.get("occurrenceID") or str(occurrence.get("key")),"specimen_identifier":occurrence.get("catalogNumber"),"source_reference":media.get("references") or f"https://www.gbif.org/occurrence/{occurrence.get('key')}","image_url":identifier,"creator":media.get("creator") or occurrence.get("recordedBy"),"license_expression":media.get("license") or "UNRESOLVED","attribution_text":f"{media.get('creator') or occurrence.get('recordedBy') or 'Creator unavailable'}; {occurrence.get('publishingOrgKey') or occurrence.get('institutionCode') or 'GBIF data publisher'}; {media.get('license') or 'license unresolved'}","license":license_info,"media_type":media.get("format") if str(media.get("format") or "").startswith("image/") else "image/jpeg","provider_taxon_key":occurrence.get("taxonKey"),"provider_scientific_name":occurrence.get("scientificName"),"taxonomic_linkage":"EXACT_GOVERNED_TAXON","locality":occurrence.get("locality"),"event_date":parse_event_date(occurrence.get("eventDate")),"life_stage":occurrence.get("lifeStage"),"biological_context":"PRESERVED_SPECIMEN" if occurrence.get("basisOfRecord")=="PRESERVED_SPECIMEN" else "IN_SITU_OBSERVATION","source_metadata":{"gbif_key":occurrence.get("key"),"dataset_key":occurrence.get("datasetKey"),"publishing_org_key":occurrence.get("publishingOrgKey"),"basis_of_record":occurrence.get("basisOfRecord"),"country_code":occurrence.get("countryCode")}});break
    if len(records)>=limit:break
   time.sleep(self.delay)
  return GBIFMediaManifest({"taxon_key":taxon_key,"scientific_name":scientific_name,"limit":limit,"page_size":page_size},len(records),end,"GBIF_API_V1",tuple(records))
 def download(self,url):
  response=self._get(url,stream=True);content_type=response.headers.get("content-type","").split(";")[0].lower();declared=int(response.headers.get("content-length") or 0)
  if declared>self.max_bytes:raise ValueError("Image exceeds configured size limit")
  chunks=[];total=0
  for chunk in response.iter_content(65536):
   total+=len(chunk)
   if total>self.max_bytes:raise ValueError("Image exceeds configured size limit")
   chunks.append(chunk)
  return b"".join(chunks),content_type
