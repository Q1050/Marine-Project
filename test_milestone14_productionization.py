from pathlib import Path
import hashlib, sqlite3
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from milestone14_migrate_production import migrate
from migration_manager import run_migrations
from models import Jurisdiction, Region, ScientificDomainEvent
from platform_config import Settings
from production_operations import EventWorker, InMemoryRateLimiter, restore_backup


def temp_engine(tmp_path):
    bind=create_engine(f"sqlite:///{tmp_path/'test.db'}",connect_args={"check_same_thread":False});Base.metadata.create_all(bind);return bind


def test_migration_is_additive_and_idempotent(tmp_path):
    bind=temp_engine(tmp_path)
    assert migrate(bind)==[]


def test_fresh_install_creates_no_scientific_or_observation_rows(tmp_path):
    bind=create_engine(f"sqlite:///{tmp_path/'fresh.db'}")
    first=run_migrations(bind,initialize=True);second=run_migrations(bind,initialize=True)
    assert first["applied"] and second["applied"]==[]
    with bind.connect() as c:
        for table in ("observations","ecological_status_assertions","governed_occurrence_evidence","anomaly_assessments","anomaly_configurations","scientific_reviewer_grants"):
            assert c.exec_driver_sql(f"select count(*) from {table}").scalar()==0
    assert migrate(bind)==[]


def test_environment_fails_closed_for_pilot_secret(tmp_path):
    value=Settings("PILOT",f"sqlite:///{tmp_path/'x.db'}",("https://pilot.example",),tmp_path,tmp_path,tmp_path,"INFO",None,False,False,30,100,10,10,3,14,False)
    assert "AUTH_SECRET is required for PILOT/PRODUCTION" in value.validate()


def test_rate_limiter_is_bounded():
    limiter=InMemoryRateLimiter();assert limiter.allow("x",2);assert limiter.allow("x",2);assert not limiter.allow("x",2)


def test_competing_worker_claim_and_automation_firewall(tmp_path):
    bind=temp_engine(tmp_path);Session=sessionmaker(bind=bind)
    with Session() as db:
        region=Region(name="Demo",slug="demo",status="ACTIVE");db.add(region);db.flush();jurisdiction=Jurisdiction(region_id=region.id,name="Demo",slug="demo",country_code="DX",status="ACTIVE",center_latitude=0,center_longitude=0,default_zoom=4);db.add(jurisdiction);db.flush();event=ScientificDomainEvent(event_type="OBSERVATION_EXPERT_VERIFIED",jurisdiction_id=jurisdiction.id,event_fingerprint="a"*64,payload_json="{}",processing_state="PENDING");db.add(event);db.commit();event_id=event.id
    first=Session();second=Session()
    try:
        claimed=EventWorker(first,"one").claim_one(event_id);assert claimed.worker_id=="one"
        assert EventWorker(second,"two").claim_one(event_id) is None
    finally:first.close();second.close()
    with Session() as db:
        row=db.get(ScientificDomainEvent,event_id);row.processing_state="RETRYABLE";row.worker_id=None;row.claimed_at=None;db.commit()
        result=EventWorker(db,"manual").process_one(event_id)
        assert result.processing_state=="SKIPPED";assert result.error_category=="AUTOMATION_DISABLED"


def test_restore_refuses_bad_hash_and_preserves_state(tmp_path):
    source=tmp_path/"backup.db";target=tmp_path/"target.db"
    with sqlite3.connect(source) as db:db.execute("create table evidence(id integer primary key, value text)");db.execute("insert into evidence(value) values ('governed')")
    target.write_bytes(b"old")
    with pytest.raises(ValueError):restore_backup(source,target,"0"*64)
    digest=hashlib.sha256(source.read_bytes()).hexdigest();result=restore_backup(source,target,digest)
    with sqlite3.connect(target) as db:assert db.execute("select value from evidence").fetchone()[0]=="governed"
    assert result["preserved_previous"]
