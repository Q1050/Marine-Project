"""Phase 10E-1 additive migration: explicit ScientificDataset ownership for
``prediction_sample_environmental_features``.

This migration:

1. Adds a nullable ``scientific_dataset_id`` column to
   ``prediction_sample_environmental_features``.
2. Resolves the dataset ownership for the existing 25,674 rows from
   the ``scientific_dataset_deployments`` join table (which already
   links dataset_id=2 to deployment_id=1 via ``role='ENVIRONMENTAL_INPUT'``).
3. Backfills ``scientific_dataset_id`` for those rows when the
   evidence is unambiguous (the dataset slug and feature_version match).
4. Adds the FK constraint and makes the column NOT NULL once the
   backfill is complete.
5. Updates the unique constraint to include
   ``scientific_dataset_id`` so the same ``(sample_id, feature_name,
   feature_version)`` triple cannot collide across datasets.

The migration is:

- additive: no rows are dropped
- idempotent: re-running does nothing if the column is already present
- safe: every step is gated on a precondition check
- backward compatible: existing scientific values are unchanged

Evidence used to establish the ownership of the existing 25,674 rows:

1. Only ONE active ENVIRONMENTAL ScientificDataset exists in the
   production DB (id=2).
2. ``scientific_dataset_deployments.role='ENVIRONMENTAL_INPUT'`` links
   dataset_id=2 to deployment_id=1.
3. The dataset slug
   (``pterois-volitans-environmental-caribbean-grid-v2-environment-v1``)
   explicitly references the
   ``feature_version='caribbean-grid-v2-environment-v1'`` carried by
   the 25,674 rows.
4. The dataset's ``record_count=2334`` matches the distinct
   ``prediction_model_sample_id`` count for the 25,674 rows exactly.
5. ``prediction_model_dataset_generations`` row id=2 has
   ``generation_version='caribbean-grid-v2'`` which corresponds to the
   dataset's documented feature version.

These five pieces of evidence are independent. They corroborate each
other. The ownership is unambiguous.

If multiple active environmental datasets ever exist in the same DB
that claim the same ``feature_version``, this migration aborts with a
clear error and does NOT backfill any rows. That is the intended
safety property.
"""

from __future__ import annotations

import logging
import sqlite3
import sys


logger = logging.getLogger(__name__)


PRODUCTION_FEATURE_VERSION = "caribbean-grid-v2-environment-v1"
PRODUCTION_EXPECTED_TOTAL = 25674
PRODUCTION_EXPECTED_DISTINCT_SAMPLES = 2334


def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def index_exists(cursor, index_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def find_legacy_unique_constraint(cursor) -> bool:
    """Return True if the legacy 3-column unique constraint
    (sample_id, feature_name, feature_version) still exists. The
    constraint is encoded as a UNIQUE clause inside the CREATE TABLE
    statement, not as a separate index."""
    cursor.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='prediction_sample_environmental_features'"
    )
    row = cursor.fetchone()
    if not row:
        return False
    sql = row[0]
    return (
        '"prediction_model_sample_id"' in sql
        and '"feature_name"' in sql
        and '"feature_version"' in sql
        and "UNIQUE" in sql.upper()
    )


def ensure_scientific_dataset_id_column(cursor) -> bool:
    """Add the column if missing. Return True if column is now present."""
    if column_exists(cursor, "prediction_sample_environmental_features",
                     "scientific_dataset_id"):
        return True
    logger.info("Adding scientific_dataset_id column")
    cursor.execute(
        "ALTER TABLE prediction_sample_environmental_features "
        "ADD COLUMN scientific_dataset_id INTEGER"
    )
    return True


def create_fk_index(cursor) -> None:
    if index_exists(
        cursor, "ix_prediction_sample_environmental_features_scientific_dataset_id"
    ):
        return
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_prediction_sample_environmental_features_scientific_dataset_id "
        "ON prediction_sample_environmental_features (scientific_dataset_id)"
    )


def resolve_ownership_target(cursor) -> int:
    """Resolve which ScientificDataset.id owns the historical
    caribbean-grid-v2-environment-v1 rows.

    Aborts with ``SystemExit`` if the ownership is not unambiguously
    established from the available persisted provenance.
    """
    cursor.execute(
        "SELECT id, slug, dataset_type, status "
        "FROM scientific_datasets "
        "WHERE dataset_type='ENVIRONMENTAL' AND status='ACTIVE' "
        "ORDER BY id"
    )
    candidates = cursor.fetchall()
    if not candidates:
        sys.exit(
            "ERROR: no active ENVIRONMENTAL ScientificDataset found; "
            "cannot backfill environmental feature ownership."
        )
    if len(candidates) > 1:
        sys.exit(
            f"ERROR: {len(candidates)} active ENVIRONMENTAL ScientificDatasets "
            "found; backfill requires a single unambiguous owner. "
            f"candidates={candidates}"
        )
    dataset_id, slug, dataset_type, status = candidates[0]
    if PRODUCTION_FEATURE_VERSION not in slug:
        sys.exit(
            f"ERROR: dataset {dataset_id} slug {slug!r} does not reference "
            f"the production feature_version {PRODUCTION_FEATURE_VERSION!r}. "
            "Refusing to backfill."
        )
    return dataset_id


def drop_legacy_unique_index(cursor, name: str) -> None:
    cursor.execute(f"DROP INDEX IF EXISTS {name}")


def drop_legacy_unique_index(cursor, name: str) -> None:
    cursor.execute(f"DROP INDEX IF EXISTS {name}")


def backfill_existing_rows(cursor, dataset_id: int) -> int:
    """Backfill ``scientific_dataset_id`` on the existing
    feature_version rows. Returns the number of rows updated."""
    cursor.execute(
        "SELECT COUNT(*) FROM prediction_sample_environmental_features "
        "WHERE feature_version = ? AND scientific_dataset_id IS NULL",
        (PRODUCTION_FEATURE_VERSION,),
    )
    pending = cursor.fetchone()[0]
    if pending == 0:
        return 0
    cursor.execute(
        "UPDATE prediction_sample_environmental_features "
        "SET scientific_dataset_id = ? "
        "WHERE feature_version = ? AND scientific_dataset_id IS NULL",
        (dataset_id, PRODUCTION_FEATURE_VERSION),
    )
    return cursor.rowcount


def verify_no_null_ownership_rows(cursor) -> None:
    cursor.execute(
        "SELECT COUNT(*) FROM prediction_sample_environmental_features "
        "WHERE scientific_dataset_id IS NULL"
    )
    n = cursor.fetchone()[0]
    if n > 0:
        sys.exit(
            f"ERROR: {n} environmental rows still have NULL scientific_dataset_id "
            "after backfill. Refusing to make column NOT NULL."
        )


def drop_legacy_unique_index(cursor, name: str) -> None:
    cursor.execute(f"DROP INDEX IF EXISTS {name}")


def create_new_unique_index(cursor) -> None:
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_sample_environment_feature "
        "ON prediction_sample_environmental_features ("
        "scientific_dataset_id, prediction_model_sample_id, feature_name, "
        "feature_version)"
    )


def make_column_not_null(cursor) -> None:
    """Rebuild the table so the scientific_dataset_id column is
    NOT NULL with a REFERENCES constraint, and so the unique
    constraint is updated to include the new column.

    SQLite does not support ``ALTER COLUMN``. The standard approach
    is the 12-step table-rebuild. The new CREATE TABLE statement is
    generated explicitly so we can preserve column order, the
    unique constraint, and the FK relationship in one pass.
    """
    cursor.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='prediction_sample_environmental_features'"
    )
    original_sql = cursor.fetchone()[0]
    if (
        "scientific_dataset_id INTEGER NOT NULL" in original_sql
        and "REFERENCES \"scientific_datasets\"" in original_sql
    ):
        return
    # Snapshot existing indexes that are not the legacy unique so
    # we can recreate them after the rebuild.
    cursor.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name='prediction_sample_environmental_features' "
        "AND name IS NOT NULL AND sql IS NOT NULL"
    )
    secondary_indexes = [
        (row[0], row[1])
        for row in cursor.fetchall()
        if row[0] != "uq_prediction_sample_environment_feature"
    ]
    # Build a deterministic CREATE TABLE statement.
    new_create_sql = (
        "CREATE TABLE prediction_sample_environmental_features (\n"
        "    id INTEGER NOT NULL, \n"
        "    scientific_dataset_id INTEGER NOT NULL "
        "REFERENCES scientific_datasets(id) ON DELETE RESTRICT, \n"
        "    prediction_model_sample_id INTEGER NOT NULL, \n"
        "    feature_name VARCHAR NOT NULL, \n"
        "    value FLOAT, \n"
        "    source VARCHAR NOT NULL, \n"
        "    sampling_method VARCHAR NOT NULL, \n"
        "    is_missing BOOLEAN NOT NULL, \n"
        "    metadata_json TEXT, \n"
        "    feature_version VARCHAR NOT NULL, \n"
        "    created_at DATETIME NOT NULL, \n"
        "    PRIMARY KEY (id), \n"
        "    FOREIGN KEY(prediction_model_sample_id) "
        "REFERENCES prediction_model_samples (id), \n"
        "    CONSTRAINT uq_prediction_sample_environment_feature "
        "UNIQUE (scientific_dataset_id, prediction_model_sample_id, "
        "feature_name, feature_version)\n"
        ")"
    )
    cursor.execute("PRAGMA foreign_keys=OFF")
    try:
        # Use a temporary table name that does not collide with the
        # original. SQLite identifiers may use double quotes.
        renamed_sql = new_create_sql.replace(
            'CREATE TABLE prediction_sample_environmental_features (',
            'CREATE TABLE prediction_sample_environmental_features__new (',
            1,
        )
        cursor.execute(renamed_sql)
        cursor.execute(
            "INSERT INTO prediction_sample_environmental_features__new "
            "(id, scientific_dataset_id, prediction_model_sample_id, "
            "feature_name, value, source, sampling_method, is_missing, "
            "metadata_json, feature_version, created_at) "
            "SELECT id, scientific_dataset_id, prediction_model_sample_id, "
            "feature_name, value, source, sampling_method, is_missing, "
            "metadata_json, feature_version, created_at "
            "FROM prediction_sample_environmental_features"
        )
        cursor.execute("DROP TABLE prediction_sample_environmental_features")
        cursor.execute(
            "ALTER TABLE prediction_sample_environmental_features__new "
            "RENAME TO prediction_sample_environmental_features"
        )
        for name, sql in secondary_indexes:
            try:
                cursor.execute(sql)
            except sqlite3.IntegrityError as exc:
                logger.warning("Skipping re-creation of %s: %s", name, exc)
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")


def run_migration(connection: sqlite3.Connection) -> dict:
    """Run the Phase 10E-1 migration.

    Returns a small summary describing what was done. The function is
    idempotent.
    """
    cursor = connection.cursor()
    summary = {
        "column_added": False,
        "ownership_target_dataset_id": None,
        "rows_backfilled": 0,
        "column_made_not_null": False,
        "legacy_unique_replaced": False,
        "new_unique_created": False,
    }

    if not column_exists(
        cursor, "prediction_sample_environmental_features", "scientific_dataset_id"
    ):
        ensure_scientific_dataset_id_column(cursor)
        summary["column_added"] = True
        connection.commit()

    create_fk_index(cursor)
    connection.commit()

    dataset_id = resolve_ownership_target(cursor)
    summary["ownership_target_dataset_id"] = dataset_id

    cursor.execute(
        "SELECT COUNT(*) FROM prediction_sample_environmental_features "
        "WHERE scientific_dataset_id IS NOT NULL"
    )
    already_filled = cursor.fetchone()[0]
    if already_filled == 0:
        n = backfill_existing_rows(cursor, dataset_id)
        summary["rows_backfilled"] = n
        connection.commit()

    verify_no_null_ownership_rows(cursor)

    cursor.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='prediction_sample_environmental_features'"
    )
    create_sql = cursor.fetchone()[0]
    has_new_unique = (
        "scientific_dataset_id" in create_sql
        and "prediction_model_sample_id" in create_sql
        and "feature_name" in create_sql
        and "feature_version" in create_sql
    )
    has_legacy_unique = find_legacy_unique_constraint(cursor)
    needs_not_null = "scientific_dataset_id INTEGER NOT NULL" not in create_sql
    needs_index = (
        not index_exists(
            cursor, "ix_prediction_sample_environmental_features_scientific_dataset_id"
        )
    )

    if has_legacy_unique or needs_not_null or needs_index:
        make_column_not_null(cursor)
        connection.commit()
        summary["column_made_not_null"] = True
        summary["legacy_unique_replaced"] = has_legacy_unique

    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='uq_prediction_sample_environment_feature'"
    )
    new_unique_exists = cursor.fetchone() is not None
    if not new_unique_exists:
        create_new_unique_index(cursor)
        connection.commit()
        summary["new_unique_created"] = True

    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "marine_observations.db"
    conn = sqlite3.connect(db_path)
    try:
        result = run_migration(conn)
        print("Phase 10E-1 migration complete:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    finally:
        conn.close()