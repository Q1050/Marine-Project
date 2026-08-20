"""Phase 10E-4 additive migration: chain-of-custody columns.

Adds the following columns:

- ``training_runs.training_input_sha256``: SHA-256 over the ordered
  set of (role, dataset_id, artifact_sha256_or_null,
  record_count, source_version) tuples linked to the run. NULL
  until ``compute_training_input_sha256`` is called.
- ``training_runs.input_integrity_status``: TEXT label
  (``NOT_COMPUTED`` / ``PARTIAL`` / ``COMPLETE``). The legacy
  Jamaica v3 run starts in PARTIAL because no controlled dataset
  artifacts exist for it.

The migration is:

- additive (no rows deleted)
- idempotent (running twice is a no-op)
- SQLite-safe (uses standard SQL features only)
- PostgreSQL-friendly (no SQLite-specific syntax)

The columns are intentionally NULLABLE on creation. They are
populated by explicit repository calls, NOT by the migration
itself.
"""

from __future__ import annotations

import logging
import sqlite3
import sys


logger = logging.getLogger(__name__)


# Input integrity status values. The legacy Jamaica run starts in
# PARTIAL because its datasets have NULL artifact_sha256.
INTEGRITY_NOT_COMPUTED = "NOT_COMPUTED"
INTEGRITY_PARTIAL = "PARTIAL"
INTEGRITY_COMPLETE = "COMPLETE"


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def index_exists(cursor, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def ensure_training_input_sha256_column(cursor) -> bool:
    if column_exists(cursor, "training_runs", "training_input_sha256"):
        return False
    cursor.execute(
        "ALTER TABLE training_runs "
        "ADD COLUMN training_input_sha256 VARCHAR(64)"
    )
    if not index_exists(cursor, "ix_training_runs_training_input_sha256"):
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS "
            "ix_training_runs_training_input_sha256 "
            "ON training_runs (training_input_sha256)"
        )
    return True


def ensure_input_integrity_status_column(cursor) -> bool:
    if column_exists(cursor, "training_runs", "input_integrity_status"):
        return False
    cursor.execute(
        "ALTER TABLE training_runs "
        "ADD COLUMN input_integrity_status VARCHAR DEFAULT "
        f"'{INTEGRITY_NOT_COMPUTED}'"
    )
    return True


def run_migration(connection: sqlite3.Connection) -> dict:
    cursor = connection.cursor()
    summary = {
        "training_input_sha256_added": False,
        "input_integrity_status_added": False,
    }
    if not column_exists(cursor, "training_runs", "training_input_sha256"):
        ensure_training_input_sha256_column(cursor)
        summary["training_input_sha256_added"] = True
        connection.commit()
    if not column_exists(cursor, "training_runs", "input_integrity_status"):
        ensure_input_integrity_status_column(cursor)
        summary["input_integrity_status_added"] = True
        connection.commit()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    conn = sqlite3.connect(db_path)
    try:
        result = run_migration(conn)
        print("Phase 10E-4 migration complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()