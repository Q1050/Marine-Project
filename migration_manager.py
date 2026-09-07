"""Deterministic deployment migration ledger and runner."""
from datetime import datetime, timezone
import hashlib
from sqlalchemy import inspect, text
from database import engine
from database import Base
import models  # register all schema with Base
from milestone14_migrate_production import VERSION, migrate
from milestone15_migrate_postgresql import VERSION as VERSION_15, migrate as migrate_15
from milestone17_migrate_visual_corpus import VERSION as VERSION_16, migrate as migrate_16
from milestone17b_migrate_media_operations import VERSION as VERSION_17, migrate as migrate_17
from milestone18_migrate_multisource_corpus import VERSION as VERSION_18, migrate as migrate_18
from milestone19_migrate_media_retry import VERSION as VERSION_19, migrate as migrate_19
from milestone19_migrate_taxonomy_resolution import VERSION as VERSION_20, migrate as migrate_20

MIGRATIONS=((VERSION,migrate),(VERSION_15,migrate_15),(VERSION_16,migrate_16),(VERSION_17,migrate_17),(VERSION_18,migrate_18),(VERSION_19,migrate_19),(VERSION_20,migrate_20))


def _ledger(bind):
    with bind.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(128) PRIMARY KEY, checksum VARCHAR(64) NOT NULL, applied_at TIMESTAMP NOT NULL)"))


def current_versions(bind=engine):
    if "schema_migrations" not in inspect(bind).get_table_names(): return []
    with bind.begin() as c:return [r[0] for r in c.execute(text("SELECT version FROM schema_migrations ORDER BY version"))]


def run_migrations(bind=engine, initialize=False):
    if initialize: Base.metadata.create_all(bind=bind)
    _ledger(bind); applied=[]; existing=set(current_versions(bind))
    for version, fn in MIGRATIONS:
        checksum=hashlib.sha256(version.encode()).hexdigest()
        if version in existing:continue
        changes=fn(bind)
        with bind.begin() as c:c.execute(text("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (:v,:c,:t)"),{"v":version,"c":checksum,"t":datetime.now(timezone.utc)})
        applied.append({"version":version,"changes":changes})
    return {"applied":applied,"current":current_versions(bind)}

if __name__=="__main__":print(run_migrations(initialize=True))
