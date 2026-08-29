"""Additive/idempotent boundary provenance and lifecycle migration."""
import sqlite3


ADDITIONS = {
    "provider_boundary_identifier": "VARCHAR(128)", "crs": "VARCHAR(64)",
    "source_artifact_reference": "VARCHAR(512)", "source_artifact_sha256": "VARCHAR(64)",
    "acquisition_metadata_json": "TEXT", "limitations_json": "TEXT",
    "activated_at": "DATETIME", "superseded_at": "DATETIME",
    "predecessor_boundary_id": "INTEGER REFERENCES jurisdiction_boundaries(id) ON DELETE RESTRICT",
}


def run_migration(connection: sqlite3.Connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(jurisdiction_boundaries)")}
    summary = {"columns_added": 0, "active_rows_backfilled": 0, "partial_unique_index_created": False}
    with connection:
        for name, definition in ADDITIONS.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE jurisdiction_boundaries ADD COLUMN {name} {definition}")
                summary["columns_added"] += 1
        cursor = connection.execute(
            "UPDATE jurisdiction_boundaries SET activated_at=created_at, crs=COALESCE(crs,'EPSG:4326') "
            "WHERE status='ACTIVE' AND activated_at IS NULL"
        )
        summary["active_rows_backfilled"] = cursor.rowcount
        existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_active_boundary_per_type'"
        ).fetchone() is not None
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_boundary_per_type "
            "ON jurisdiction_boundaries(jurisdiction_id,boundary_type) WHERE status='ACTIVE'"
        )
        summary["partial_unique_index_created"] = not existed
        for column in ("source_artifact_sha256", "predecessor_boundary_id"):
            connection.execute(f"CREATE INDEX IF NOT EXISTS ix_jurisdiction_boundaries_{column} ON jurisdiction_boundaries({column})")
    return summary
