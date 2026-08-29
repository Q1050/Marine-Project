"""Additive and idempotent external-pilot readiness schema."""
from sqlalchemy import inspect, text
from database import engine
from models import PilotFeedback, ReporterAccessToken, ReporterAdditionalInformation

TABLES=(ReporterAccessToken.__table__,ReporterAdditionalInformation.__table__,PilotFeedback.__table__)
COLUMNS={"delivery_attempts":"INTEGER NOT NULL DEFAULT 0","last_delivery_error":"TEXT","last_attempted_at":"DATETIME","delivered_at":"DATETIME"}
def migrate(bind=engine):
    created=[];existing=set(inspect(bind).get_table_names())
    for table in TABLES:
        if table.name not in existing:table.create(bind=bind,checkfirst=True);created.append(table.name)
    names={c["name"] for c in inspect(bind).get_columns("observation_notification_events")}
    with bind.begin() as connection:
        for name,definition in COLUMNS.items():
            if name not in names:connection.execute(text(f"ALTER TABLE observation_notification_events ADD COLUMN {name} {definition}"));created.append(f"observation_notification_events.{name}")
    return created
if __name__=="__main__":print({"created":migrate()})
