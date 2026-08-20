"""Phase 10E-2 additive migration: TrainingRun provenance model.

This migration introduces a durable TrainingRun record and links it
to ScientificDataset snapshots. The migration is:

- additive (no rows deleted)
- idempotent (running twice is a no-op)
- SQLite-safe (uses standard SQL features only)
- PostgreSQL-friendly (no SQLite-specific syntax in the new tables)

Tables introduced:

1. ``training_runs``
   - The durable run record.
   - Status lifecycle: BUILDING / COMPLETED / FAILED.
   - Provenance origin: NATIVE / LEGACY_RECONSTRUCTED.
   - Configuration is persisted as an immutable JSON snapshot.
   - Validation metrics are persisted as JSON.
   - artifact_path / artifact_sha256 are nullable until COMPLETED.

2. ``training_run_datasets``
   - Many-to-many between training_runs and scientific_datasets with
     an explicit role (TRAINING_OCCURRENCES / ENVIRONMENTAL_INPUT /
     VALIDATION_INPUT / etc.) reusing the Phase 10C vocabulary.

3. ``suitability_deployments.training_run_id``
   - Nullable FK on the existing suitability_deployments table so
     future deployments can reference the run that produced them.
   - Existing Jamaica v3 deployment remains valid with NULL
     (or can be backfilled with a LEGACY_RECONSTRUCTED row via a
     separate explicit call).

The legacy Jamaica v3 deployment is NOT auto-backfilled by this
migration. The companion ``phase10e2_backfill_legacy_training_run``
script performs that step explicitly so the migration remains
declarative and idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
import sys


logger = logging.getLogger(__name__)


PROVENANCE_ORIGIN_NATIVE = "NATIVE"
PROVENANCE_ORIGIN_LEGACY_RECONSTRUCTED = "LEGACY_RECONSTRUCTED"

STATUS_BUILDING = "BUILDING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

ROLE_TRAINING_OCCURRENCES = "TRAINING_OCCURRENCES"
ROLE_ENVIRONMENTAL_INPUT = "ENVIRONMENTAL_INPUT"
ROLE_VALIDATION_INPUT = "VALIDATION_INPUT"


def table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def index_exists(cursor, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def ensure_training_runs_table(cursor) -> bool:
    """Create the ``training_runs`` table if missing.

    Returns True if the table is now present.
    """
    if table_exists(cursor, "training_runs"):
        return True
    cursor.execute(
        "CREATE TABLE training_runs ("
        "    id INTEGER NOT NULL PRIMARY KEY, "
        "    species_program_id INTEGER NOT NULL "
        "REFERENCES species_programs(id), "
        "    model_version VARCHAR NOT NULL, "
        "    status VARCHAR NOT NULL "
        "DEFAULT 'BUILDING', "
        "    provenance_origin VARCHAR NOT NULL "
        "DEFAULT 'NATIVE', "
        "    started_at DATETIME NOT NULL, "
        "    completed_at DATETIME, "
        "    random_seed INTEGER, "
        "    selected_candidate VARCHAR, "
        "    artifact_path VARCHAR, "
        "    artifact_sha256 VARCHAR(64), "
        "    training_sample_count INTEGER, "
        "    presence_count INTEGER, "
        "    background_count INTEGER, "
        "    validation_metrics_json TEXT, "
        "    configuration_json TEXT NOT NULL, "
        "    warnings_json TEXT, "
        "    failure_reason TEXT, "
        "    created_at DATETIME NOT NULL, "
        "    updated_at DATETIME NOT NULL"
        ")"
    )
    cursor.execute(
        "CREATE INDEX ix_training_runs_species_program_id "
        "ON training_runs (species_program_id)"
    )
    cursor.execute(
        "CREATE INDEX ix_training_runs_model_version "
        "ON training_runs (model_version)"
    )
    cursor.execute(
        "CREATE INDEX ix_training_runs_status "
        "ON training_runs (status)"
    )
    return True


def ensure_training_run_datasets_table(cursor) -> bool:
    """Create the ``training_run_datasets`` link table."""
    if table_exists(cursor, "training_run_datasets"):
        return True
    cursor.execute(
        "CREATE TABLE training_run_datasets ("
        "    id INTEGER NOT NULL PRIMARY KEY, "
        "    training_run_id INTEGER NOT NULL "
        "REFERENCES training_runs(id), "
        "    scientific_dataset_id INTEGER NOT NULL "
        "REFERENCES scientific_datasets(id), "
        "    role VARCHAR(64) NOT NULL, "
        "    created_at DATETIME NOT NULL, "
        "    UNIQUE (training_run_id, scientific_dataset_id, role)"
        ")"
    )
    cursor.execute(
        "CREATE INDEX ix_training_run_datasets_training_run_id "
        "ON training_run_datasets (training_run_id)"
    )
    cursor.execute(
        "CREATE INDEX ix_training_run_datasets_scientific_dataset_id "
        "ON training_run_datasets (scientific_dataset_id)"
    )
    return True


def ensure_deployment_training_run_id(cursor) -> bool:
    """Add ``training_run_id`` to ``suitability_deployments`` if missing."""
    if column_exists(
        cursor, "suitability_deployments", "training_run_id"
    ):
        return False
    cursor.execute(
        "ALTER TABLE suitability_deployments "
        "ADD COLUMN training_run_id INTEGER "
        "REFERENCES training_runs(id)"
    )
    cursor.execute(
        "CREATE INDEX ix_suitability_deployments_training_run_id "
        "ON suitability_deployments (training_run_id)"
    )
    return True


def run_migration(connection: sqlite3.Connection) -> dict:
    cursor = connection.cursor()
    summary = {
        "training_runs_created": False,
        "training_run_datasets_created": False,
        "deployment_training_run_id_added": False,
    }
    if not table_exists(cursor, "training_runs"):
        ensure_training_runs_table(cursor)
        summary["training_runs_created"] = True
        connection.commit()
    if not table_exists(cursor, "training_run_datasets"):
        ensure_training_run_datasets_table(cursor)
        summary["training_run_datasets_created"] = True
        connection.commit()
    if column_exists(cursor, "suitability_deployments", "training_run_id"):
        added_now = False
    else:
        added_now = ensure_deployment_training_run_id(cursor)
        summary["deployment_training_run_id_added"] = added_now
        if added_now:
            connection.commit()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    conn = sqlite3.connect(db_path)
    try:
        result = run_migration(conn)
        print("Phase 10E-2 migration complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()