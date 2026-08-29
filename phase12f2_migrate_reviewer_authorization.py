"""Additive, idempotent Phase 12F-2 operational authorization migration."""
from sqlalchemy import inspect
from database import engine
from models import ObservationNotificationEvent, ObservationReviewerGrant


def migrate(bind=engine):
    existing = set(inspect(bind).get_table_names())
    created = []
    for table in (ObservationReviewerGrant.__table__, ObservationNotificationEvent.__table__):
        if table.name not in existing:
            table.create(bind=bind, checkfirst=True)
            created.append(table.name)
    return created


if __name__ == "__main__":
    print({"created": migrate()})
