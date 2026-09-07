import pytest
from sqlalchemy import create_engine
from database import Base
from models import IdentificationBenchmarkRun, IdentificationCorpus, IdentificationMediaReviewEvent
from identification_corpus_service import IdentificationCorpusPlanService, IdentificationCorpusService, IdentificationBenchmarkService, LocalArtifactStore, corpus_readiness_for_taxon
from milestone18_migrate_multisource_corpus import migrate
from test_milestone17_visual_corpus import active_source, asset_payload, db, png, seed, source_payload
from wikimedia_media_adapter import WikimediaCommonsAdapter, normalize_commons_license

class Response:
 def __init__(self,payload=None,data=b"",headers=None,status=200):self.payload=payload;self.data=data;self.headers=headers or {};self.status_code=status
 def json(self):return self.payload
 def raise_for_status(self):
  if self.status_code>=400:raise __import__('requests').HTTPError(str(self.status_code))
 def iter_content(self,_):yield self.data
class HTTP:
 def __init__(self,responses):self.responses=list(responses)
 def get(self,*_args,**_kwargs):return self.responses.pop(0)

def test_commons_normalization_is_conservative_and_preserves_metadata():
 assert normalize_commons_license("CC BY 4.0")["training_eligible"]
 assert normalize_commons_license("CC BY-SA 4.0")["license_classification"]=="SHARE_ALIKE"
 assert not normalize_commons_license("CC BY-NC 4.0")["training_eligible"]
 payload={"query":{"pages":[{"pageid":7,"title":"File:Lionfish.jpg","imageinfo":[{"url":"https://upload/x.jpg","thumburl":"https://upload/thumb.jpg","descriptionurl":"https://commons/wiki/File:X","mime":"image/jpeg","width":2000,"height":1000,"sha1":"abc","extmetadata":{"Artist":{"value":"<b>A. Scientist</b>"},"LicenseShortName":{"value":"CC BY 4.0"},"LicenseUrl":{"value":"https://creativecommons.org/licenses/by/4.0/"}}}]}]}}
 manifest=WikimediaCommonsAdapter(HTTP([Response(payload)]),delay_seconds=0).acquire(None,"Pterois volitans",1)
 record=manifest.records[0];assert record["creator"]=="A. Scientist" and record["taxonomic_linkage"]=="REVIEW_REQUIRED" and record["source_metadata"]["canonical_title"]=="File:Lionfish.jpg"

def test_plan_accepts_only_governed_taxa_and_is_idempotent():
 session=db();user,region,taxa=seed(session);payload={"plan_key":"caribbean-identification","version":"v1","region_id":region.id,"taxonomic_groups":["fish","other"],"preferred_providers":["GBIF","WIKIMEDIA_COMMONS"],"licensing_policy":{"fail_closed":True},"quality_policy":{"minimum_width":64},"duplicate_policy":{"perceptual_review":True},"provenance":{"milestone":"18"},"limitations":["One governed taxon"],"configuration":{},"taxa":[{"taxon_id":taxa[0].id,"taxonomic_group":"fish","desired_candidate_count":30,"minimum_usable_count":10}]}
 service=IdentificationCorpusPlanService(session);first=service.create(payload,user.id);assert service.create(payload,user.id).id==first.id and service.payload(first)["taxa"][0]["desired_candidate_count"]==30
 bad=dict(payload);bad["version"]="v2";bad["taxa"]=[{"taxon_id":999,"taxonomic_group":"fish"}]
 with pytest.raises(ValueError):service.create(bad,user.id)

def test_cross_provider_duplicate_and_review_dispositions(tmp_path):
 session=db();user,_,taxa=seed(session);first_source=active_source(session,user);payload=source_payload();payload["registration_key"]="commons";payload["scientific_provider"]="Wikimedia Commons"
 from identification_corpus_service import MediaSourceGovernanceService
 governance=MediaSourceGovernanceService(session);second_source=governance.register(payload,user.id);governance.transition(second_source,"APPROVED",user.id,"review");governance.transition(second_source,"ACTIVE",user.id,"activate")
 service=IdentificationCorpusService(session,LocalArtifactStore(tmp_path));first=service.create_candidate(asset_payload(first_source,taxa[0],"gbif"),user.id,png());second=service.create_candidate(asset_payload(second_source,taxa[0],"commons"),user.id,png())
 assert second.duplicate_state=="EXACT_DUPLICATE" and second.exact_duplicate_of_id==first.id
 service.review(first,"NEEDS_REVIEW",user.id,"needs context");assert first.review_state=="REVIEW_REQUIRED"
 service.review(first,"TAXONOMY_REVIEW_REQUIRED",user.id,"identity check");assert first.review_state=="TAXONOMY_REVIEW_REQUIRED" and session.query(IdentificationMediaReviewEvent).filter_by(media_asset_id=first.id).count()==2

def test_readiness_and_benchmark_immutability():
 session=db();user,_,taxa=seed(session);assert corpus_readiness_for_taxon(session,taxa[0].id)=="NO_MEDIA_SOURCE";active_source(session,user);assert corpus_readiness_for_taxon(session,taxa[0].id)=="ACQUISITION_READY"
 corpus=IdentificationCorpus(corpus_key="benchmark",version="v1",intended_purpose="BENCHMARK",taxonomic_scope_json="{}",lifecycle_state="FROZEN",provenance_json="{}",limitations_json="[]",configuration_json="{}",fingerprint="b"*64,created_by_user_id=user.id);session.add(corpus);session.commit();service=IdentificationBenchmarkService(session)
 with pytest.raises(ValueError):service.prepare({"model_identity":"pretrained-bioclip","model_version":"unchanged","corpus_id":corpus.id,"split_name":"TEST","inference_configuration":{}},user.id)
 row=IdentificationBenchmarkRun(model_identity="pretrained-bioclip",model_version="unchanged",corpus_id=corpus.id,split_name="TEST",inference_configuration_json="{}",metrics_json="{}",run_fingerprint="c"*64,workflow_state="COMPLETED",created_by_user_id=user.id);session.add(row);session.commit();row.metrics_json='{"changed":true}'
 with pytest.raises(ValueError):session.commit()

def test_migration_idempotent_and_admin_routes_are_protected():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);assert migrate(engine)["tables_created"]==[];assert migrate(engine)["tables_created"]==[]
 from api import app
 paths={route.path:route for route in app.routes if hasattr(route,"dependant")}
 for path in ("/admin/identification-corpus/plans","/admin/identification-corpus/plans/{plan_id}/transition","/admin/identification-corpus/taxa/{taxon_id}/readiness"):
  assert "require_platform_admin" in {d.call.__name__ for d in paths[path].dependant.dependencies}
