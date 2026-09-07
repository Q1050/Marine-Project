"""Bounded Wikimedia Commons adapter using the official MediaWiki API."""
from __future__ import annotations
import hashlib, html, re, time
import requests
from media_provider_contract import MediaProviderManifest

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

def _plain(value):
    raw = value.get("value") if isinstance(value, dict) else value
    return html.unescape(re.sub(r"<[^>]+>", " ", str(raw or ""))).strip()

def normalize_commons_license(name, url=None):
    label = _plain(name).upper().replace("CREATIVE COMMONS", "CC")
    if "CC0" in label or "PUBLIC DOMAIN" in label:
        classification = "PUBLIC_DOMAIN"
    elif "CC BY-NC" in label:
        classification = "NONCOMMERCIAL_RESTRICTION"
    elif "CC BY-ND" in label:
        classification = "NO_DERIVATIVES"
    elif "CC BY-SA" in label:
        classification = "SHARE_ALIKE"
    elif re.search(r"\bCC BY(?: |$)", label):
        classification = "ATTRIBUTION_REQUIRED"
    else:
        classification = "UNKNOWN"
    return {"raw_license": _plain(name) or None, "license_url": _plain(url) or None,
            "license_classification": classification,
            "training_eligible": classification in {"PUBLIC_DOMAIN", "ATTRIBUTION_REQUIRED"},
            "limitations": [] if classification in {"PUBLIC_DOMAIN", "ATTRIBUTION_REQUIRED"} else ["License requires separate governed review or blocks corpus use."]}

class WikimediaCommonsAdapter:
    def __init__(self, session=None, timeout=25, max_bytes=15_000_000, delay_seconds=.25, retries=3):
        self.http=session or requests.Session(); self.timeout=timeout; self.max_bytes=max_bytes; self.delay=delay_seconds; self.retries=retries
    def _get(self, url, **kwargs):
        last=None
        for attempt in range(self.retries):
            try:
                response=self.http.get(url, timeout=self.timeout, headers={"User-Agent":"MarineMonitoringVisualCorpus/18 (scientific prototype)"}, **kwargs)
                if response.status_code in {429,500,502,503,504}:
                    wait=float(response.headers.get("Retry-After") or self.delay*(2**attempt)); time.sleep(min(wait,30)); continue
                response.raise_for_status(); return response
            except requests.RequestException as exc:
                last=exc; time.sleep(self.delay*(2**attempt))
        raise RuntimeError(f"Wikimedia request failed: {last or 'retry limit exceeded'}")
    def acquire(self, provider_taxon_id, scientific_name, limit=10, page_size=10):
        if not 1 <= limit <= 25: raise ValueError("Controlled Wikimedia limit must be 1-25")
        params={"action":"query","format":"json","formatversion":2,"generator":"search","gsrsearch":f'"{scientific_name}" filetype:bitmap',"gsrnamespace":6,"gsrlimit":min(limit,page_size),"prop":"imageinfo","iiprop":"url|size|mime|sha1|extmetadata","iiurlwidth":1280}
        payload=self._get(COMMONS_API,params=params).json(); records=[]
        for page in payload.get("query",{}).get("pages",[]):
            info=(page.get("imageinfo") or [{}])[0]; meta=info.get("extmetadata") or {}; mime=info.get("mime")
            if mime not in {"image/jpeg","image/png","image/webp"}: continue
            license_info=normalize_commons_license(meta.get("LicenseShortName"),meta.get("LicenseUrl")); title=page.get("title") or str(page.get("pageid"))
            records.append({"provider_asset_identifier":str(page.get("pageid") or hashlib.sha256(title.encode()).hexdigest()),"source_reference":info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{title.replace(' ','_')}","image_url":info.get("thumburl") or info.get("url"),"original_file_url":info.get("url"),"thumbnail_url":info.get("thumburl"),"creator":_plain(meta.get("Artist")) or None,"license_expression":license_info["raw_license"] or "UNRESOLVED","attribution_text":_plain(meta.get("Credit")) or _plain(meta.get("Attribution")) or f"{_plain(meta.get('Artist')) or 'Creator unavailable'}; {license_info['raw_license'] or 'license unresolved'}","license":license_info,"media_type":mime,"width_px":info.get("width"),"height_px":info.get("height"),"taxonomic_linkage":"REVIEW_REQUIRED","taxonomic_confidence_source":"Commons search context; requires explicit scientific review","biological_context":None,"source_metadata":{"commons_page_id":page.get("pageid"),"canonical_title":title,"sha1":info.get("sha1"),"license_url":license_info.get("license_url"),"retrieved_via":"MediaWiki imageinfo/extmetadata","query_taxon":scientific_name}})
            if len(records)>=limit: break
        return MediaProviderManifest("Wikimedia Commons",{"scientific_name":scientific_name,"limit":limit},len(records),not bool(payload.get("continue")),"MediaWiki API",tuple(records))
    def download(self,url):
        response=self._get(url,stream=True); media_type=response.headers.get("content-type","").split(";")[0].lower(); declared=int(response.headers.get("content-length") or 0)
        if media_type not in {"image/jpeg","image/png","image/webp"}: raise ValueError("Unsupported image media type")
        if declared>self.max_bytes: raise ValueError("Image exceeds configured size limit")
        chunks=[]; total=0
        for chunk in response.iter_content(65536):
            total+=len(chunk)
            if total>self.max_bytes: raise ValueError("Image exceeds configured size limit")
            chunks.append(chunk)
        return b"".join(chunks),media_type
