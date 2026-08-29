import io,json
from PIL import Image
import pytest
from gbif_media_adapter import GBIFMediaAdapter,normalize_gbif_license
from identification_corpus_service import perceptual_hash,perceptual_distance,IdentificationBenchmarkService
from occurrence_batch_service import OccurrenceBatchService
from test_milestone17_visual_corpus import db,seed,active_source,png
from models import IdentificationCorpus,IdentificationCorpusInclusion,IdentificationMediaAsset,IdentificationMediaReviewEvent
from milestone17b_migrate_media_operations import migrate as migrate_17b

class Response:
 def __init__(self,payload=None,data=b"",headers=None,status=200):self.payload=payload;self.data=data;self.headers=headers or {};self.status_code=status
 def json(self):return self.payload
 def raise_for_status(self):
  if self.status_code>=400:raise __import__('requests').HTTPError(str(self.status_code))
 def iter_content(self,_):yield self.data
class HTTP:
 def __init__(self,responses):self.responses=list(responses);self.calls=[]
 def get(self,url,**kwargs):self.calls.append((url,kwargs));return self.responses.pop(0)

def occurrence(key,license="http://creativecommons.org/licenses/by/4.0/",taxon=2334438):return {"key":key,"taxonKey":taxon,"scientificName":"Pterois volitans (Linnaeus, 1758)","occurrenceID":f"occ-{key}","media":[{"type":"StillImage","identifier":f"https://images.test/{key}.jpg","references":f"https://records.test/{key}","creator":"Scientist","license":license,"format":"image/jpeg"}]}
def test_gbif_adapter_pagination_normalization_and_cap():
 http=HTTP([Response({"results":[occurrence(1)],"endOfRecords":False}),Response({"results":[occurrence(2)],"endOfRecords":True})]);adapter=GBIFMediaAdapter(http,delay_seconds=0)
 manifest=adapter.acquire(2334438,"Pterois volitans",limit=2,page_size=1);assert manifest.retrieved==2 and len(http.calls)==2 and manifest.records[0]["license"]["training_eligible"]
 with pytest.raises(ValueError):adapter.acquire(2334438,"Pterois volitans",26)
 assert normalize_gbif_license("mystery")["license_classification"]=="LICENSE_UNRESOLVED"
 assert normalize_gbif_license("http://creativecommons.org/licenses/by-nc/4.0/")["training_eligible"] is False
def test_adapter_download_enforces_size():
 adapter=GBIFMediaAdapter(HTTP([Response(data=b"123",headers={"content-type":"image/jpeg","content-length":"3"})]),max_bytes=4,delay_seconds=0);assert adapter.download("https://x")== (b"123","image/jpeg")
 adapter=GBIFMediaAdapter(HTTP([Response(data=b"12345",headers={"content-type":"image/jpeg"})]),max_bytes=4,delay_seconds=0)
 with pytest.raises(ValueError):adapter.download("https://x")
def test_perceptual_hash_is_deterministic_and_distance_based():
 first=perceptual_hash(png((64,64)));second=perceptual_hash(png((64,64)));assert first==second and perceptual_distance(first,second)==0
def test_benchmark_contract_requires_frozen_corpus():
 session=db();user,_,_=seed(session);corpus=IdentificationCorpus(corpus_key="c",version="v1",intended_purpose="benchmark",taxonomic_scope_json="{}",provenance_json="{}",limitations_json="[]",configuration_json="{}",fingerprint="f"*64,created_by_user_id=user.id);session.add(corpus);session.commit()
 with pytest.raises(ValueError):IdentificationBenchmarkService(session).prepare({"model_identity":"bioclip","model_version":"2","corpus_id":corpus.id,"split_name":"TEST","inference_configuration":{}},user.id)
def test_occurrence_batch_is_idempotent_and_blocked_items_are_not_claimed():
 session=db();user,region,taxa=seed(session);service=OccurrenceBatchService(session);payload=[{"jurisdiction_id":999,"taxon_id":taxa[0].id,"source_key":"OBIS"}];first=service.prepare(region.id,"b",payload,user.id);assert service.prepare(region.id,"b",payload,user.id).id==first.id;assert service.claim("worker") is None;assert service.summary(first.id)["workflow_states"]=={"BLOCKED":1}

def test_17b_migration_review_audit_taxonomy_gate_and_corpus_lifecycle(tmp_path):
 from sqlalchemy import create_engine
 from database import Base
 from identification_corpus_service import IdentificationCorpusService,LocalArtifactStore
 from test_milestone17_visual_corpus import asset_payload
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);assert migrate_17b(engine)["tables_created"]==[];assert migrate_17b(engine)["tables_created"]==[]
 session=db();user,_,taxa=seed(session);source=active_source(session,user);service=IdentificationCorpusService(session,LocalArtifactStore(tmp_path));asset=service.create_candidate(asset_payload(source,taxa[0],taxonomic_linkage="BROADER_TAXON"),user.id,png())
 with pytest.raises(ValueError):service.review(asset,"APPROVED",user.id,"blocked taxonomy")
 asset.taxonomic_linkage="EXACT_GOVERNED_TAXON";service.review(asset,"APPROVED",user.id,"scientific review");assert session.query(IdentificationMediaReviewEvent).filter_by(media_asset_id=asset.id).count()==1
 corpus=service.create_corpus({"corpus_key":"pilot","version":"v1","intended_purpose":"REFERENCE","taxonomic_scope":{"taxon_ids":[taxa[0].id]},"configuration":{},"provenance":{},"limitations":["small"]},user.id);assignments=service.include_assets(corpus.id,[asset.id],user.id,split_recommended=False);assert assignments[0]["split"]=="REFERENCE"
 service.transition_corpus(corpus,"READY_FOR_REVIEW",user.id,"review");service.transition_corpus(corpus,"APPROVED",user.id,"approve");service.transition_corpus(corpus,"FROZEN",user.id,"freeze");assert service.training_readiness(corpus.id)["state"]=="BENCHMARK_READY"
