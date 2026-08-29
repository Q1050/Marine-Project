import hashlib, io, json, time
from PIL import Image
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base
from models import *
from identification_corpus_service import (AcquisitionRunService, IdentificationCorpusService,
 LocalArtifactStore, MediaQualityValidator, MediaSourceGovernanceService, fingerprint)
from milestone17_migrate_visual_corpus import migrate

def db():
 engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(engine);return sessionmaker(bind=engine)()
def seed(session,taxa=1):
 user=User(email="admin@fixture.invalid",display_name="Admin",password_hash="x",is_platform_admin=True);region=Region(name="Caribbean",slug="caribbean",status="ACTIVE");session.add_all([user,region]);session.flush();rows=[]
 for i in range(taxa):
  taxon=Species(scientific_name=f"Marine fixture {i}",taxonomic_rank="SPECIES",authoritative_identifier_scheme="WORMS_APHIA_ID",authoritative_identifier=str(900000+i),accepted_name_status="ACCEPTED",status="ACTIVE");session.add(taxon);session.flush();session.add(RegionalTaxonRegistry(region_id=region.id,taxon_id=taxon.id,registry_version="fixture",inclusion_basis="TEST",source_references_json="[]",review_status="APPROVED",provenance_json="{}",provenance_fingerprint=f"registry-{i}"));rows.append(taxon)
 session.commit();return user,region,rows
def source_payload():return {"registration_key":"fixture-media","scientific_provider":"Fixture Museum","transport_interface":"FIXTURE","documentation_reference":"https://example.invalid/docs","licensing_model":"ITEM_LEVEL","attribution_requirements":"Creator and source","access_method":"CONTROLLED_API","taxonomic_scope":{},"geographic_scope":{},"acquisition_configuration":{"page_size":10},"provenance":{"test":True},"limitations":["Fixture only"]}
def png(size=(64,64)):
 stream=io.BytesIO();Image.new("RGB",size,"red").save(stream,"PNG");return stream.getvalue()
def patterned_png(index):
 stream=io.BytesIO();image=Image.new("L",(64,64),255)
 for x in range(64):
  for y in range(64):image.putpixel((x,y),(x*(index+2)+y*(index+5))%256)
 image.convert("RGB").save(stream,"PNG");return stream.getvalue()
def active_source(session,user):
 service=MediaSourceGovernanceService(session);row=service.register(source_payload(),user.id);service.transition(row,"APPROVED",user.id,"fixture-review");service.transition(row,"ACTIVE",user.id,"fixture-activation");return row
def asset_payload(source,taxon,identifier="asset-1",**values):return {"media_source_id":source.id,"taxon_id":taxon.id,"provider_asset_identifier":identifier,"source_reference":f"https://example.invalid/{identifier}","creator":"Fixture creator","license_expression":"CC-BY-4.0","license_classification":"ATTRIBUTION_REQUIRED","attribution_text":"Fixture creator / Fixture Museum / CC-BY-4.0","media_type":"image/png","taxonomic_linkage":"EXACT_GOVERNED_TAXON",**values}

def test_source_governance_fingerprint_lifecycle_and_idempotency():
 session=db();user,_,_=seed(session);service=MediaSourceGovernanceService(session);first=service.register(source_payload(),user.id);second=service.register(source_payload(),user.id)
 assert first.id==second.id and len(first.configuration_fingerprint)==64
 with pytest.raises(ValueError):service.transition(first,"ACTIVE",user.id,"skip-review")
 service.transition(first,"APPROVED",user.id,"review");service.transition(first,"ACTIVE",user.id,"activate");assert first.lifecycle_state=="ACTIVE"

def test_quality_storage_exact_duplicate_license_and_public_separation(tmp_path):
 session=db();user,_,taxa=seed(session);source=active_source(session,user);store=LocalArtifactStore(tmp_path/"objects");service=IdentificationCorpusService(session,store);data=png()
 first=service.create_candidate(asset_payload(source,taxa[0]),user.id,data);duplicate=service.create_candidate(asset_payload(source,taxa[0],"asset-2"),user.id,data)
 assert first.quality_state=="VALID" and store.exists(first.artifact_reference.local_path if hasattr(first,"artifact_reference") else session.get(ArtifactReference,first.artifact_reference_id).local_path)
 assert first.duplicate_state=="DISTINCT" and duplicate.duplicate_state=="EXACT_DUPLICATE" and duplicate.exact_duplicate_of_id==first.id
 service.review(first,"APPROVED",user.id,"asset-review");assert first.review_state=="APPROVED"
 assert session.query(GovernedPublicMedia).count()==0
 blocked=service.create_candidate(asset_payload(source,taxa[0],"asset-3",license_classification="LICENSE_UNRESOLVED"),user.id,png((65,64)))
 assert blocked.review_state=="EXCLUDED"

def test_quality_validation_is_configured_not_universal():
 validator=MediaQualityValidator({"minimum_width":100,"minimum_height":100,"maximum_aspect_ratio":4})
 assert validator.validate(png((80,80)),"image/png")[0]=="BELOW_CONFIGURED_RESOLUTION"
 assert validator.validate(b"", "image/png")[0]=="ZERO_BYTE"
 assert validator.validate(b"not-an-image","image/png")[0]=="CORRUPT_OR_UNREADABLE"

def test_split_groups_prevent_leakage_and_export_is_reproducible(tmp_path):
 session=db();user,_,taxa=seed(session);source=active_source(session,user);service=IdentificationCorpusService(session,LocalArtifactStore(tmp_path));assets=[]
 for index in range(3):
  row=service.create_candidate(asset_payload(source,taxa[0],f"a-{index}",source_event_identifier="event-1" if index<2 else "event-2"),user.id,patterned_png(index));service.review(row,"APPROVED",user.id,"review");assets.append(row)
 split=service.deterministic_split([a.id for a in assets],seed="fixed");assert split==service.deterministic_split([a.id for a in assets],seed="fixed")
 assert len({x["split"] for x in split if x["group_key"]=="event:event-1"})==1
 config={"seed":"fixed"};corpus=IdentificationCorpus(corpus_key="fixture",version="v1",intended_purpose="IDENTIFICATION_MODEL_DEVELOPMENT",taxonomic_scope_json="{}",provenance_json="{}",limitations_json="[]",configuration_json=json.dumps(config),fingerprint=fingerprint(config),created_by_user_id=user.id);session.add(corpus);session.flush()
 for value in split:session.add(IdentificationCorpusInclusion(corpus_id=corpus.id,media_asset_id=value["asset_id"],split_name=value["split"],split_group_key=value["group_key"],split_version="v1",inclusion_fingerprint=fingerprint({"corpus":corpus.id,**value}),created_by_user_id=user.id))
 session.commit();first=service.export_manifest(corpus.id);second=service.export_manifest(corpus.id);assert first==second and len(first["assets"])==3 and len(first["export_fingerprint"])==64

def test_acquisition_claim_retry_recovery_and_idempotency():
 session=db();user,_,taxa=seed(session);source=active_source(session,user);service=AcquisitionRunService(session);first=service.prepare(source.id,taxa[0].id,{"limit":5},user.id);assert service.prepare(source.id,taxa[0].id,{"limit":5},user.id).id==first.id
 claimed=service.claim("worker-a");assert claimed.id==first.id and service.claim("worker-b") is None;token=claimed.claim_token;service.fail(claimed,token,"transient");retried=service.claim("worker-b");service.complete(retried,retried.claim_token,{"assets":0});assert retried.workflow_state=="COMPLETED" and retried.retry_count==1

def test_migration_idempotency_and_authorization():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);assert migrate(engine)["tables_created"]==[];assert migrate(engine)["tables_created"]==[]
 from api import app
 paths={route.path:route for route in app.routes if hasattr(route,"dependant")}
 for path in ("/admin/identification-corpus/media-sources","/admin/regions/{region_id}/identification-corpus/coverage","/admin/identification-corpus/acquisition-runs","/admin/identification-corpus/assets","/admin/identification-corpus/assets/{asset_id}/content","/admin/identification-corpus/corpora","/admin/identification-corpus/benchmarks","/admin/occurrence-acquisition-batches"):
  assert "require_platform_admin" in {d.call.__name__ for d in paths[path].dependant.dependencies}

def test_100k_metadata_scale_aggregation_and_indexes():
 session=db();user,region,taxa=seed(session,1000);source=active_source(session,user);table=IdentificationMediaAsset.__table__;records=[]
 for taxon in taxa:
  for index in range(100):
   key=f"{taxon.id}:{index}";records.append({"stable_asset_key":key,"taxon_id":taxon.id,"media_source_id":source.id,"provider_asset_identifier":key,"source_reference":"test://asset","license_expression":"CC-BY-4.0","license_classification":"ATTRIBUTION_REQUIRED","attribution_text":"Fixture","media_type":"image/jpeg","sha256":hashlib.sha256(key.encode()).hexdigest(),"taxonomic_linkage":"EXACT_GOVERNED_TAXON","quality_state":"VALID","quality_metadata_json":"{}","duplicate_state":"UNIQUE","review_state":"APPROVED","provenance_fingerprint":hashlib.sha256(f"p:{key}".encode()).hexdigest()})
 started=time.perf_counter();session.execute(table.insert(),records);session.commit();insert_seconds=time.perf_counter()-started;queries=[0]
 event.listen(session.get_bind(),"before_cursor_execute",lambda *_:queries.__setitem__(0,queries[0]+1));started=time.perf_counter();result=IdentificationCorpusService(session).coverage(region.id,page=1,page_size=100);query_seconds=time.perf_counter()-started
 assert result["total"]==1000 and len(result["items"])==100 and sum(x["training_eligible"] for x in result["items"])==10000
 assert queries[0]<8 and insert_seconds<15 and query_seconds<5

def test_visual_corpus_firewall():
 session=db();user,_,taxa=seed(session);before={m:session.query(m).count() for m in (EcologicalStatusAssertion,GovernedOccurrenceEvidence,SpeciesJurisdictionStatus,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalyConfiguration)};source=active_source(session,user);AcquisitionRunService(session).prepare(source.id,taxa[0].id,{"limit":3},user.id);assert before=={m:session.query(m).count() for m in before}
