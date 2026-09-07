import sys, threading
import pytest
from sqlalchemy import create_engine
from database import Base
from lazy_bioclip_service import LazyMarineObservationService
from milestone19_migrate_media_retry import migrate
from identification_corpus_service import IdentificationCorpusService, LocalArtifactStore
from test_milestone17_visual_corpus import active_source, asset_payload, db, png, seed

def test_bioclip_is_lazy_and_thread_safe():
 calls=[]
 class Fixture:
  def __init__(self):calls.append("loaded")
  def analyze(self,value):return value
 service=LazyMarineObservationService(Fixture);assert not service.is_loaded and calls==[]
 results=[];threads=[threading.Thread(target=lambda:results.append(service.analyze("ok"))) for _ in range(4)]
 [thread.start() for thread in threads];[thread.join() for thread in threads]
 assert results==["ok"]*4 and calls==["loaded"] and service.is_loaded

def test_api_import_does_not_import_real_bioclip_stack(monkeypatch):
 sys.modules.pop("api",None);sys.modules.pop("marine_observation_service",None)
 import api
 assert not api.service.is_loaded and "marine_observation_service" not in sys.modules

def test_failed_retry_state_and_successful_retry_are_durable(tmp_path):
 session=db();user,_,taxa=seed(session);source=active_source(session,user);service=IdentificationCorpusService(session,LocalArtifactStore(tmp_path));asset=service.create_candidate(asset_payload(source,taxa[0]),user.id,data=None)
 service.retry_acquisition(asset,error="HTTP 503",response_metadata={"status":503});assert asset.acquisition_retry_count==1 and asset.acquisition_last_error=="HTTP 503"
 service.retry_acquisition(asset,data=png(),media_type="image/png",response_metadata={"status":200});assert asset.acquisition_retry_count==2 and asset.acquisition_last_error is None and asset.quality_state=="VALID" and asset.sha256

def test_migration_is_idempotent():
 engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);assert migrate(engine)["columns_added"]==[];assert migrate(engine)["columns_added"]==[]
