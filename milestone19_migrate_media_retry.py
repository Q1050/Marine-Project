"""Add item-level acquisition retry diagnostics without changing scientific state."""
from sqlalchemy import inspect, text

VERSION="019-media-acquisition-retry-v1"
TABLE="identification_media_assets"
COLUMNS={"acquisition_retry_count":"INTEGER NOT NULL DEFAULT 0","acquisition_last_error":"TEXT","acquisition_response_json":"TEXT NOT NULL DEFAULT '{}'"}

def migrate(bind):
    existing={column["name"] for column in inspect(bind).get_columns(TABLE)};added=[]
    for name,definition in COLUMNS.items():
        if name not in existing:
            with bind.begin() as connection:connection.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {definition}"))
            added.append(name)
    return {"columns_added":added}
