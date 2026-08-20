"""Phase 10E-3 additive migration: configuration_sha256 column.

Adds a nullable ``configuration_sha256`` column to the
``training_runs`` table so future native runs can carry a
deterministic integrity anchor for their persisted configuration
snapshot.

The migration is:

- additive (no rows deleted)
- idempotent (running twice is a no-op)
- SQLite-safe (uses standard SQL features only)
- PostgreSQL-friendly (no SQLite-specific syntax)

The column is intentionally nullable because the legacy
Jamaica v3 TrainingRun's configuration_sha256 is computed and
populated by the companion ``phase10e3_backfill_legacy_sha256``
script, NOT by this migration. The migration itself is
declarative.
"""

from __future__ import annotations

import logging
import sqlite3
import sys


logger = logging.getLogger(__name__)


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def index_exists(cursor, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def ensure_configuration_sha256_column(cursor) -> bool:
    """Add the column if missing. Return True if column is now present."""
    if column_exists(cursor, "training_runs", "configuration_sha256"):
        return False
    cursor.execute(
        "ALTER TABLE training_runs "
        "ADD COLUMN configuration_sha256 VARCHAR(64)"
    )
    if not index_exists(cursor, "ix_training_runs_configuration_sha256"):
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS "
            "ix_training_runs_configuration_sha256 "
            "ON training_runs (configuration_sha256)"
        )
    return True


def run_migration(connection: sqlite3.Connection) -> dict:
    cursor = connection.cursor()
    summary = {"configuration_sha256_added": False}
    if not column_exists(cursor, "training_runs", "configuration_sha256"):
        ensure_configuration_sha256_column(cursor)
        summary["configuration_sha256_added"] = True
        connection.commit()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    conn = sqlite3.connect(db_path)
    try:
        result = run_migration(conn)
        print("Phase 10E-3 migration complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()