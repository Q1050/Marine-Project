"""Provider-neutral taxonomy acquisition contracts and WoRMS REST adapter."""
from __future__ import annotations
import abc, hashlib, json, urllib.parse, urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from jurisdiction_boundary_registry import canonical_json

@dataclass(frozen=True)
class TaxonomyRecord:
    provider:str; identifier_scheme:str; identifier:str; scientific_name:str
    accepted_scientific_name:str|None; authorship:str|None; rank:str; status:str
    accepted_identifier:str|None; parent_identifier:str|None; parent_name:str|None
    classification:tuple[dict,...]; provider_version:str; provider_reference:str

class TaxonomyProvider(abc.ABC):
    @abc.abstractmethod
    def resolve_name(self, scientific_name:str): ...
    @abc.abstractmethod
    def fetch_taxon(self, identifier:str): ...
    @abc.abstractmethod
    def fetch_classification(self, identifier:str): ...

class WoRMSTaxonomyProvider(TaxonomyProvider):
    BASE="https://www.marinespecies.org/rest"
    PROVIDER="World Register of Marine Species (WoRMS)"
    VERSION="live-rest-v1"
    def _get(self,path):
        request=urllib.request.Request(self.BASE+path,headers={"Accept":"application/json","User-Agent":"MarineMonitoringTaxonomy/1.0"})
        with urllib.request.urlopen(request,timeout=60) as response: return json.loads(response.read())
    def resolve_name(self,scientific_name):
        if "/" in scientific_name or scientific_name.strip().count(" ") != 1: raise ValueError("Ambiguous or non-species identity requires explicit taxonomic review")
        records=self._get("/AphiaRecordsByName/"+urllib.parse.quote(scientific_name,safe="")+"?like=false&marine_only=true&offset=1")
        exact=[row for row in records or [] if row.get("scientificname")==scientific_name]
        if len(exact)!=1: raise ValueError("WoRMS exact-name resolution was not unique")
        return str(exact[0]["AphiaID"])
    def fetch_taxon(self,identifier): return self._get(f"/AphiaRecordByAphiaID/{int(identifier)}")
    def fetch_classification(self,identifier): return self._get(f"/AphiaClassificationByAphiaID/{int(identifier)}")
    @staticmethod
    def _flatten(node):
        values=[]
        while node:
            values.append({"aphia_id":str(node.get("AphiaID")),"rank":node.get("rank"),"scientific_name":node.get("scientificname")})
            node=node.get("child")
        return tuple(values)
    def acquire(self,scientific_name):
        identifier=self.resolve_name(scientific_name); raw_record=self.fetch_taxon(identifier); raw_classification=self.fetch_classification(identifier)
        accepted=str(raw_record.get("valid_AphiaID") or raw_record["AphiaID"])
        status="ACCEPTED" if raw_record.get("status","").lower()=="accepted" else "SYNONYM"
        record=TaxonomyRecord(self.PROVIDER,"WORMS_APHIA_ID",str(raw_record["AphiaID"]),raw_record["scientificname"],raw_record.get("valid_name"),raw_record.get("authority"),str(raw_record.get("rank") or "UNRANKED").upper(),status,accepted,str(raw_record.get("parentNameUsageID")) if raw_record.get("parentNameUsageID") else None,raw_record.get("parentNameUsage"),self._flatten(raw_classification),self.VERSION,f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={raw_record['AphiaID']}")
        raw={"request":{"scientific_name":scientific_name,"aphia_id":identifier},"provider":self.PROVIDER,"provider_version":self.VERSION,"provider_reference":record.provider_reference,"provider_response":{"record":raw_record,"classification":raw_classification}}
        content_fingerprint=hashlib.sha256(canonical_json(raw).encode()).hexdigest()
        directory=Path("artifacts/taxonomy/worms"); directory.mkdir(parents=True,exist_ok=True)
        slug=scientific_name.lower().replace(" ","-"); path=directory/f"{slug}-{identifier}-{content_fingerprint[:12]}.json"
        if not path.exists():
            envelope={**raw,"retrieved_at":datetime.now(timezone.utc).isoformat(),"canonical_content_fingerprint":content_fingerprint}
            path.write_text(json.dumps(envelope,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        artifact_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        return record,path,artifact_sha,content_fingerprint

__all__=["TaxonomyProvider","TaxonomyRecord","WoRMSTaxonomyProvider"]
