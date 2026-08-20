"""Phase 10E migration-chain closure test.

Validates the FULL Phase 10E migration sequence against an
isolated temporary SQLite database representing the closest
legitimate pre-10E schema.

The repository does not ship an explicit pre-Phase-10E migration
script. The Phase 10E migrations were the first to add these
columns and tables. The predecessor state therefore must be
constructed manually as the baseline.

The test:

1. Constructs the pre-10E schema manually (all tables that EXIST
   before Phase 10E, with the OLD schemas that lack Phase 10E
   columns / new tables).
2. Runs the Phase 10E migration sequence in dependency order.
3. Asserts each migration adds its expected schema additions.
4. Runs the SAME sequence a second time.
5. Asserts the second run is idempotent.
6. Asserts no duplicate rows in any of the new tables.
7. Asserts scientific values (rows, hashes, counts) are unchanged.

The pre-10E schema is constructed to be the closest legitimate
predecessor the repository supports. This is documented in the
test docstring.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile

import pytest


def _build_pre_10e_schema(conn: sqlite3.Connection) -> None:
    """Construct the closest legitimate pre-10E schema.

    This represents the state after Phase 10D-5 (dataset/artifact chain)
    but BEFORE Phase 10E-1. It contains the tables and columns that
    existed at that time, including the legacy unique constraint on
    ``prediction_sample_environmental_features``.
    """
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE regions (
        id INTEGER PRIMARY KEY, name TEXT, slug TEXT, status TEXT
    );
    CREATE TABLE jurisdictions (
        id INTEGER PRIMARY KEY, region_id INTEGER, name TEXT, slug TEXT,
        country_code TEXT, status TEXT, center_latitude REAL,
        center_longitude REAL, default_zoom REAL
    );
    CREATE TABLE species (
        id INTEGER PRIMARY KEY, scientific_name TEXT
    );
    CREATE TABLE species_programs (
        id INTEGER PRIMARY KEY, jurisdiction_id INTEGER,
        scientific_name TEXT, status TEXT
    );
    CREATE TABLE scientific_datasets (
        id INTEGER PRIMARY KEY, slug TEXT, name TEXT, dataset_type TEXT,
        status TEXT, description TEXT,
        species_id INTEGER, species_program_id INTEGER,
        geographic_scope_type TEXT, region_id INTEGER,
        jurisdiction_id INTEGER, source_name TEXT, source_type TEXT,
        source_reference TEXT, source_version TEXT,
        acquisition_manifest_json TEXT, retrieved_at DATETIME,
        record_count INTEGER, artifact_path TEXT, artifact_sha256 TEXT,
        notes TEXT, created_at DATETIME, updated_at DATETIME
    );
    CREATE TABLE scientific_dataset_deployments (
        id INTEGER PRIMARY KEY, scientific_dataset_id INTEGER,
        suitability_deployment_id INTEGER, role TEXT, notes TEXT,
        created_at DATETIME
    );
    CREATE TABLE suitability_deployments (
        id INTEGER PRIMARY KEY, species_program_id INTEGER,
        habitat_suitability_model_id INTEGER, model_version TEXT,
        status TEXT, artifact_hash TEXT, generated_at DATETIME,
        activated_at DATETIME, created_at DATETIME, updated_at DATETIME
        -- pre-10E-2: NO training_run_id column
    );
    -- pre-10E-1: prediction_sample_environmental_features WITHOUT
    -- scientific_dataset_id; legacy unique constraint.
    CREATE TABLE prediction_sample_environmental_features (
        id INTEGER PRIMARY KEY,
        prediction_model_sample_id INTEGER NOT NULL,
        feature_name VARCHAR NOT NULL,
        value FLOAT NOT NULL,
        source VARCHAR NOT NULL,
        sampling_method VARCHAR NOT NULL,
        is_missing BOOLEAN NOT NULL,
        metadata_json TEXT,
        feature_version VARCHAR NOT NULL,
        created_at DATETIME NOT NULL,
        CONSTRAINT uq_prediction_sample_environment_feature
            UNIQUE (prediction_model_sample_id, feature_name, feature_version)
    );
    CREATE TABLE prediction_model_samples (
        id INTEGER PRIMARY KEY, scientific_name TEXT, grid_cell_id TEXT,
        latitude REAL, longitude REAL, sample_type TEXT,
        generation_version TEXT
    );
    CREATE TABLE historical_occurrences (
        id INTEGER PRIMARY KEY, scientific_name TEXT, taxon_id INTEGER,
        latitude REAL, longitude REAL, event_date DATETIME,
        source TEXT, deduplication_key TEXT, dataset_id INTEGER
    );
    CREATE TABLE habitat_suitability_models (
        id INTEGER PRIMARY KEY
    );
    """)
    conn.commit()


def _seed_pre_10e_data(conn: sqlite3.Connection) -> None:
    """Seed a minimum but legitimate pre-10E dataset for the
    migrations to operate on."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO regions (id, name, slug, status) "
        "VALUES (1, 'r', 'r', 'ACTIVE')"
    )
    cursor.execute(
        "INSERT INTO jurisdictions (id, region_id, name, slug, country_code, "
        "status, center_latitude, center_longitude, default_zoom) "
        "VALUES (1, 1, 'j', 'j', 'XX', 'ACTIVE', 0, 0, 5)"
    )
    cursor.execute(
        "INSERT INTO species (id, scientific_name) VALUES (1, 'X')"
    )
    cursor.execute(
        "INSERT INTO species_programs (id, jurisdiction_id, "
        "scientific_name, status) VALUES (1, 1, 'X', 'ACTIVE')"
    )
    cursor.execute(
        "INSERT INTO scientific_datasets (id, slug, name, dataset_type, "
        "status, geographic_scope_type, region_id, jurisdiction_id, "
        "source_name, source_version, record_count, created_at) "
        "VALUES (1, 'caribbean-grid-v2-environment-v1', 'env', "
        "'ENVIRONMENTAL', 'ACTIVE', 'REGION', 1, NULL, 'TEST', 'v1', 5, "
        "CURRENT_TIMESTAMP)"
    )
    cursor.execute(
        "INSERT INTO scientific_datasets (id, slug, name, dataset_type, "
        "status, geographic_scope_type, region_id, jurisdiction_id, "
        "source_name, source_version, record_count, created_at) "
        "VALUES (2, 'caribbean-grid-v1-occurrence', 'occ', "
        "'OCCURRENCE', 'ACTIVE', 'JURISDICTION', 1, 1, 'TEST', 'v1', 3, "
        "CURRENT_TIMESTAMP)"
    )
    cursor.execute(
        "INSERT INTO prediction_model_samples (id, scientific_name, "
        "grid_cell_id, latitude, longitude, sample_type, generation_version) "
        "VALUES (1, 'X', '10:-100', 30.25, -49.75, 'PRESENCE', 'v1')"
    )
    cursor.execute(
        "INSERT INTO prediction_model_samples (id, scientific_name, "
        "grid_cell_id, latitude, longitude, sample_type, generation_version) "
        "VALUES (2, 'X', '10:-99', 30.25, -49.25, 'PRESENCE', 'v1')"
    )
    cursor.execute(
        "INSERT INTO prediction_sample_environmental_features ("
        "id, prediction_model_sample_id, feature_name, value, source, "
        "sampling_method, is_missing, feature_version, created_at) "
        "VALUES (1, 1, 'a', 1.0, 't', 'N', 0, "
        "'caribbean-grid-v2-environment-v1', CURRENT_TIMESTAMP)"
    )
    cursor.execute(
        "INSERT INTO prediction_sample_environmental_features ("
        "id, prediction_model_sample_id, feature_name, value, source, "
        "sampling_method, is_missing, feature_version, created_at) "
        "VALUES (2, 2, 'a', 2.0, 't', 'N', 0, "
        "'caribbean-grid-v2-environment-v1', CURRENT_TIMESTAMP)"
    )
    cursor.execute(
        "INSERT INTO habitat_suitability_models (id) VALUES (1)"
    )
    cursor.execute(
        "INSERT INTO suitability_deployments (id, species_program_id, "
        "habitat_suitability_model_id, model_version, status, "
        "artifact_hash, created_at) "
        "VALUES (1, 1, 1, 'v3', 'ACTIVE', NULL, CURRENT_TIMESTAMP)"
    )
    cursor.execute(
        "INSERT INTO scientific_dataset_deployments (id, "
        "scientific_dataset_id, suitability_deployment_id, role) "
        "VALUES (1, 1, 1, 'ENVIRONMENTAL_INPUT')"
    )
    conn.commit()


def _snapshot_scientific_values(conn: sqlite3.Connection) -> dict:
    """Return a snapshot of all scientific values that must remain
    unchanged after the migration chain."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, slug, dataset_type, record_count, source_version "
        "FROM scientific_datasets"
    )
    datasets = cursor.fetchall()
    cursor.execute(
        "SELECT id, prediction_model_sample_id, feature_name, value, "
        "feature_version FROM prediction_sample_environmental_features"
    )
    env_rows = cursor.fetchall()
    return {
        "datasets": datasets,
        "env_rows": env_rows,
    }


def _hash(values: dict) -> str:
    h = hashlib.sha256()
    for dataset in values["datasets"]:
        h.update(repr(dataset).encode())
    for row in values["env_rows"]:
        h.update(repr(row).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Test.
# ---------------------------------------------------------------------------


def test_phase10e_migration_chain_idempotent():
    """Run the full Phase 10E migration sequence against a
    pre-10E baseline, then run it again. Verify idempotency."""
    tmpdir = tempfile.mkdtemp(prefix="phase10e_chain_")
    try:
        db_path = os.path.join(tmpdir, "fixture.db")

        # Step 1: construct the pre-10E baseline.
        conn = sqlite3.connect(db_path)
        _build_pre_10e_schema(conn)
        _seed_pre_10e_data(conn)
        conn.close()

        # Snapshot before any migration.
        conn = sqlite3.connect(db_path)
        before = _snapshot_scientific_values(conn)
        before_hash = _hash(before)
        before_dataset_count = len(before["datasets"])
        before_env_row_count = len(before["env_rows"])
        conn.close()

        # Step 2: run the migration sequence.
        from phase10e1_migrate_environmental_ownership import (
            run_migration as run_10e1,
        )
        from phase10e2_migrate_training_run import (
            run_migration as run_10e2,
        )
        from phase10e3_migrate_configuration_sha256 import (
            run_migration as run_10e3,
        )
        from phase10e4_migrate_chain_of_custody import (
            run_migration as run_10e4,
        )

        # First run of the full sequence.
        results1 = {}
        for label, fn in (
            ("10e-1", run_10e1),
            ("10e-2", run_10e2),
            ("10e-3", run_10e3),
            ("10e-4", run_10e4),
        ):
            conn = sqlite3.connect(db_path)
            try:
                results1[label] = fn(conn)
            finally:
                conn.close()

        # Step 3: verify each migration added what it should on the
        # first pass.
        assert results1["10e-1"]["column_added"] is True
        assert results1["10e-1"]["rows_backfilled"] == 2
        assert results1["10e-1"]["column_made_not_null"] is True
        assert results1["10e-1"]["new_unique_created"] is True
        assert results1["10e-2"]["training_runs_created"] is True
        assert results1["10e-2"]["training_run_datasets_created"] is True
        assert results1["10e-2"]["deployment_training_run_id_added"] is True
        assert results1["10e-3"]["configuration_sha256_added"] is True
        assert results1["10e-4"]["training_input_sha256_added"] is True
        assert results1["10e-4"]["input_integrity_status_added"] is True

        # Step 4: verify scientific values are preserved.
        conn = sqlite3.connect(db_path)
        after_first = _snapshot_scientific_values(conn)
        first_hash = _hash(after_first)
        conn.close()
        assert first_hash == before_hash
        assert len(after_first["datasets"]) == before_dataset_count
        assert len(after_first["env_rows"]) == before_env_row_count

        # Step 5: run the migration sequence a second time.
        results2 = {}
        for label, fn in (
            ("10e-1", run_10e1),
            ("10e-2", run_10e2),
            ("10e-3", run_10e3),
            ("10e-4", run_10e4),
        ):
            conn = sqlite3.connect(db_path)
            try:
                results2[label] = fn(conn)
            finally:
                conn.close()

        # Step 6: verify idempotency: second run adds NOTHING.
        assert results2["10e-1"]["column_added"] is False
        assert results2["10e-1"]["rows_backfilled"] == 0
        assert results2["10e-1"]["column_made_not_null"] is False
        assert results2["10e-1"]["new_unique_created"] is False
        assert results2["10e-2"]["training_runs_created"] is False
        assert results2["10e-2"]["training_run_datasets_created"] is False
        assert results2["10e-2"]["deployment_training_run_id_added"] is False
        assert results2["10e-3"]["configuration_sha256_added"] is False
        assert results2["10e-4"]["training_input_sha256_added"] is False
        assert results2["10e-4"]["input_integrity_status_added"] is False

        # Step 7: verify scientific values are STILL preserved.
        conn = sqlite3.connect(db_path)
        after_second = _snapshot_scientific_values(conn)
        second_hash = _hash(after_second)
        conn.close()
        assert second_hash == before_hash
        assert second_hash == first_hash
        assert len(after_second["datasets"]) == before_dataset_count
        assert len(after_second["env_rows"]) == before_env_row_count

        # Step 8: verify no duplicates were created by either run.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT id FROM scientific_datasets)"
        )
        ds_count = cursor.fetchone()[0]
        assert ds_count == before_dataset_count
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT prediction_model_sample_id, "
            "feature_name, feature_version FROM "
            "prediction_sample_environmental_features)"
        )
        env_count = cursor.fetchone()[0]
        assert env_count == before_env_row_count
        cursor.execute(
            "SELECT COUNT(*) FROM training_runs"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT COUNT(*) FROM training_run_datasets"
        )
        assert cursor.fetchone()[0] == 0
        conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)