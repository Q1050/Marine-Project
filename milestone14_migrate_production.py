"""Additive/idempotent Milestone 14 operational schema migration."""
from sqlalchemy import inspect, text
from database import engine
from models import BackupRecord, PlatformAuditEvent

VERSION = "014-production-operations-v1"


def migrate(bind=engine):
    changes=[]
    existing=set(inspect(bind).get_table_names())
    for table in (PlatformAuditEvent.__table__, BackupRecord.__table__):
        if table.name not in existing:
            table.create(bind=bind, checkfirst=True); changes.append(table.name)
    additions={
        "users":{"organization_name":"VARCHAR(256)","job_title":"VARCHAR(256)"},
        "pilot_feedback":{"state":"VARCHAR(24) NOT NULL DEFAULT 'OPEN'","admin_disposition":"TEXT","reviewed_by_user_id":"INTEGER REFERENCES users(id)","reviewed_at":"DATETIME"},
        "scientific_domain_events":{"worker_id":"VARCHAR(128)","claimed_at":"DATETIME","next_attempt_at":"DATETIME","error_category":"VARCHAR(48)"},
    }
    with bind.begin() as connection:
        for table, columns in additions.items():
            names={c["name"] for c in inspect(bind).get_columns(table)}
            for name, definition in columns.items():
                if name not in names:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"));changes.append(f"{table}.{name}")
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_scientific_domain_events_worker_id ON scientific_domain_events(worker_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_scientific_domain_events_next_attempt_at ON scientific_domain_events(next_attempt_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_pilot_feedback_state ON pilot_feedback(state)"))
    return changes

if __name__ == "__main__": print({"version":VERSION,"changes":migrate()})
