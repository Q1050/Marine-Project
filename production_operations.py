"""Pilot operations: readiness, audit, durable worker, backup and diagnostics."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib, json, os, sqlite3, subprocess, threading, uuid
from sqlalchemy.engine import make_url
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session
from database import engine
from early_warning_operations import EarlyWarningOperations
from migration_manager import MIGRATIONS, current_versions
from models import BackupRecord, PlatformAuditEvent, ScientificDomainEvent
from platform_config import settings


def utcnow(): return datetime.now(timezone.utc)


def audit(db:Session, operation_type:str, actor_id=None, target_type=None, target_id=None, jurisdiction_id=None, summary=None, correlation_id=None):
    row=PlatformAuditEvent(actor_user_id=actor_id,operation_type=operation_type,target_type=target_type,target_id=str(target_id) if target_id is not None else None,jurisdiction_id=jurisdiction_id,summary_json=json.dumps(summary or {},sort_keys=True,separators=(",",":")),correlation_id=correlation_id)
    db.add(row);db.flush();return row


def readiness_report():
    checks={}; errors=[]
    config_errors=settings.validate();checks["configuration"]={"ok":not config_errors,"detail":config_errors or "valid"}
    try:
        with engine.connect() as c:c.execute(text("SELECT 1"))
        pool=engine.pool
        checks["database"]={"ok":True,"backend":database_backend(),"pool":{"size":pool.size() if hasattr(pool,"size") else None,"checked_out":pool.checkedout() if hasattr(pool,"checkedout") else None}}
    except Exception as exc:checks["database"]={"ok":False,"detail":type(exc).__name__};errors.append("database")
    expected={v for v,_ in MIGRATIONS};current=set(current_versions());checks["migrations"]={"ok":expected<=current,"current":sorted(current),"pending":sorted(expected-current)}
    for name,path in (("uploads",settings.upload_directory),("artifacts",settings.artifact_directory),("backups",settings.backup_directory)):
        try:path.mkdir(parents=True,exist_ok=True);probe=path/f".write-test-{uuid.uuid4().hex}";probe.write_text("ok");probe.unlink();checks[name]={"ok":True}
        except OSError as exc:checks[name]={"ok":False,"detail":type(exc).__name__};errors.append(name)
    checks["scientific_worker"]={"ok":True,"enabled":settings.event_worker_enabled,"automatic_evaluation_global_gate":settings.automatic_scientific_evaluation_enabled}
    ready=not config_errors and not errors and checks["migrations"]["ok"]
    return {"status":"ready" if ready else "not_ready","environment":settings.environment,"demo":settings.demo,"database_backend":database_backend(),"checks":checks}


class EventWorker:
    def __init__(self,db:Session,worker_id=None):self.db=db;self.worker_id=worker_id or f"worker-{uuid.uuid4().hex[:12]}"
    def recover_abandoned(self,minutes=10):
        cutoff=utcnow()-timedelta(minutes=minutes)
        count=self.db.query(ScientificDomainEvent).filter(ScientificDomainEvent.processing_state=="PROCESSING",ScientificDomainEvent.claimed_at<cutoff).update({"processing_state":"RETRYABLE","worker_id":None,"claimed_at":None,"last_error":"Worker claim expired after restart.","error_category":"ABANDONED_CLAIM"},synchronize_session=False);self.db.commit();return count
    def claim_one(self,event_id=None):
        now=utcnow();eligible=["PENDING","RETRYABLE"]
        query=self.db.query(ScientificDomainEvent.id).filter(ScientificDomainEvent.processing_state.in_(eligible),ScientificDomainEvent.attempts<settings.max_event_attempts).filter((ScientificDomainEvent.next_attempt_at.is_(None))|(ScientificDomainEvent.next_attempt_at<=now))
        if event_id is not None:query=query.filter(ScientificDomainEvent.id==event_id)
        if self.db.get_bind().dialect.name=="postgresql":query=query.with_for_update(skip_locked=True)
        candidate=query.order_by(ScientificDomainEvent.created_at,ScientificDomainEvent.id).first()
        if not candidate:return None
        changed=self.db.query(ScientificDomainEvent).filter(ScientificDomainEvent.id==candidate[0],ScientificDomainEvent.processing_state.in_(eligible)).update({"processing_state":"PROCESSING","worker_id":self.worker_id,"claimed_at":now},synchronize_session=False)
        self.db.commit()
        return self.db.get(ScientificDomainEvent,candidate[0]) if changed==1 else None
    def process_one(self,event_id=None,actor_id=None):
        row=self.claim_one(event_id)
        if not row:return None
        try:
            # Global gate is additional to the reviewed per-configuration gate.
            if row.event_type.startswith("OBSERVATION_") and not settings.automatic_scientific_evaluation_enabled:
                row.processing_state="SKIPPED";row.attempts+=1;row.last_attempted_at=utcnow();row.processed_at=utcnow();row.last_error="Global automatic scientific evaluation gate is disabled.";row.error_category="AUTOMATION_DISABLED"
            else:
                EarlyWarningOperations(self.db).process(row)
                if row.processing_state=="RETRYABLE":
                    row.error_category="RETRYABLE_INFRASTRUCTURE";row.next_attempt_at=utcnow()+timedelta(seconds=min(300,30*(2**max(0,row.attempts-1))))
                    if row.attempts>=settings.max_event_attempts:row.processing_state="FAILED";row.error_category="RETRY_LIMIT_EXCEEDED"
            row.worker_id=None;row.claimed_at=None
            audit(self.db,"SCIENTIFIC_EVENT_PROCESSED",actor_id,"ScientificDomainEvent",row.id,row.jurisdiction_id,{"state":row.processing_state,"attempts":row.attempts})
            self.db.commit();return row
        except Exception as exc:
            self.db.rollback();row=self.db.get(ScientificDomainEvent,row.id);row.attempts+=1;row.processing_state="FAILED";row.last_error=f"{type(exc).__name__}: controlled processing failure";row.error_category="INTERNAL_FAILURE";row.worker_id=None;row.claimed_at=None;self.db.commit();return row


def _sqlite_path():
    prefix="sqlite:///"
    if not settings.database_url.startswith(prefix):raise ValueError("Managed backup currently supports SQLite only")
    return Path(settings.database_url[len(prefix):]).resolve()

def database_backend():return make_url(settings.database_url).get_backend_name()

def safe_database_identity():
    url=make_url(settings.database_url);return f"{url.get_backend_name()}://{url.host or 'local'}:{url.port or 5432}/{url.database or ''}"

def _postgres_command(program,destination):
    url=make_url(settings.database_url);env=os.environ.copy()
    if url.password:env["PGPASSWORD"]=url.password
    command=[program,"--host",url.host or "localhost","--port",str(url.port or 5432),"--username",url.username or "postgres","--dbname",url.database]
    if program=="pg_dump":command.extend(["--format=custom","--no-owner","--no-privileges","--file",str(destination)])
    return command,env


def create_backup(db:Session|None=None,actor_id=None):
    backend=database_backend();settings.backup_directory.mkdir(parents=True,exist_ok=True)
    identity=f"marine-backup-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}";dest=settings.backup_directory/f"{identity}{'.db' if backend=='sqlite' else '.dump'}"
    if backend=="sqlite":
        source=_sqlite_path()
        with sqlite3.connect(source) as src,sqlite3.connect(dest) as out:src.backup(out)
        with sqlite3.connect(dest) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0]!="ok":dest.unlink(missing_ok=True);raise RuntimeError("Backup integrity check failed")
        source_fp=hashlib.sha256(source.read_bytes()).hexdigest()
    elif backend=="postgresql":
        command,env=_postgres_command("pg_dump",dest)
        try:subprocess.run(command,env=env,check=True,capture_output=True,text=True,timeout=1800)
        except (OSError,subprocess.SubprocessError) as exc:dest.unlink(missing_ok=True);raise RuntimeError(f"PostgreSQL backup failed: {type(exc).__name__}") from None
        source_fp=hashlib.sha256(safe_database_identity().encode()).hexdigest()
    else:raise ValueError("Unsupported database backend")
    digest=hashlib.sha256(dest.read_bytes()).hexdigest();version=(current_versions() or [None])[-1]
    if db and "backup_records" in inspect(db.get_bind()).get_table_names():
        row=BackupRecord(backup_identity=identity,filename=dest.name,sha256=digest,byte_size=dest.stat().st_size,source_database_fingerprint=source_fp,migration_version=version,created_by_user_id=actor_id);db.add(row);audit(db,"BACKUP_CREATED",actor_id,"BackupRecord",identity,summary={"sha256":digest,"byte_size":dest.stat().st_size});db.commit()
    enforce_backup_retention()
    return {"backup_identity":identity,"filename":dest.name,"sha256":digest,"byte_size":dest.stat().st_size,"created_at":utcnow(),"migration_version":version}


def enforce_backup_retention():
    files=sorted(settings.backup_directory.glob("marine-backup-*.*"),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in files[max(1,settings.backup_retention_count):]:path.unlink()


def restore_backup(backup:Path,target:Path,expected_sha256:str):
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=expected_sha256:raise ValueError("Backup SHA-256 mismatch; restore refused")
    with sqlite3.connect(backup) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("Backup integrity check failed")
    preserved=target.with_name(f"{target.name}.pre-restore-{utcnow().strftime('%Y%m%dT%H%M%SZ')}")
    if target.exists():target.replace(preserved)
    target.write_bytes(backup.read_bytes())
    return {"restored":str(target),"preserved_previous":str(preserved) if preserved.exists() else None}


class InMemoryRateLimiter:
    """Single-process pilot limiter; use shared storage when horizontally scaled."""
    def __init__(self):self.data=defaultdict(deque);self.lock=threading.Lock()
    def allow(self,key,limit,window=60):
        now=datetime.now().timestamp()
        with self.lock:
            q=self.data[key]
            while q and q[0]<=now-window:q.popleft()
            if len(q)>=limit:return False
            q.append(now);return True

rate_limiter=InMemoryRateLimiter()
