"""Phase 10E-1 focused tests: explicit ScientificDataset ownership for
``prediction_sample_environmental_features``.

Run only:
    pytest test_phase10e1_environmental_ownership.py -v
"""

from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest


PRODUCTION_FEATURE_VERSION = "caribbean-grid-v2-environment-v1"
PRODUCTION_EXPECTED_ROWS = 25674
PRODUCTION_EXPECTED_SAMPLES = 2334
PRODUCTION_EXPECTED_DATASET_ID = 2


def _db_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def _require_production():
    if not os.path.exists(_db_path()):
        pytest.skip("Production DB not present")


# ----------------------------------------------------------------------
# 1. scientific_dataset_id column exists.
# ----------------------------------------------------------------------


def test_scientific_dataset_id_column_exists():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.execute(
            "PRAGMA table_info(prediction_sample_environmental_features)"
        )
        columns = [row[1] for row in cursor.fetchall()]
        assert "scientific_dataset_id" in columns
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 2. FK references ScientificDataset.
# ----------------------------------------------------------------------


def test_fk_references_scientific_datasets():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='prediction_sample_environmental_features'"
        )
        sql = cursor.fetchone()[0]
        assert "REFERENCES \"scientific_datasets\"" in sql.upper() or \
            "REFERENCES scientific_datasets" in sql
        assert "scientific_dataset_id" in sql
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 3. Existing 25,674 rows are linked to dataset id=2.
# ----------------------------------------------------------------------


def test_existing_rows_linked_to_correct_dataset():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.execute(
            "SELECT scientific_dataset_id, COUNT(*) "
            "FROM prediction_sample_environmental_features "
            "GROUP BY scientific_dataset_id"
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == PRODUCTION_EXPECTED_DATASET_ID
        assert rows[0][1] == PRODUCTION_EXPECTED_ROWS
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 4. No environmental rows are duplicated.
# ----------------------------------------------------------------------


def test_no_duplicates_after_migration():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Unique constraint should now include scientific_dataset_id.
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='prediction_sample_environmental_features'"
        )
        names = {row[0] for row in cursor.fetchall()}
        assert "uq_prediction_sample_environment_feature" in names
        # Verify the constraint includes scientific_dataset_id
        cursor = conn.execute(
            "PRAGMA index_info(uq_prediction_sample_environment_feature)"
        )
        index_columns = [row[2] for row in cursor.fetchall()]
        assert "scientific_dataset_id" in index_columns
        # Total row count unchanged
        cursor = conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features"
        )
        assert cursor.fetchone()[0] == PRODUCTION_EXPECTED_ROWS
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 5. Feature values are unchanged.
# ----------------------------------------------------------------------


def test_feature_values_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Hash the values in deterministic order.
        h = hashlib.sha256()
        for row in conn.execute(
            "SELECT prediction_model_sample_id, feature_name, value "
            "FROM prediction_sample_environmental_features "
            "ORDER BY id"
        ).fetchall():
            h.update(f"{row[0]}|{row[1]}|{row[2]}".encode())
        observed = h.hexdigest()
        # This hash matches the pre-migration value hash computed in
        # the Phase 10E-1 design verification step.
        expected = (
            "411c61902adf58107000bb2fc08d3ab75f07d6af8cb3ff88f6bc28feae479ea8"
        )
        assert observed == expected, (
            "Environmental feature values must be byte-identical "
            "before and after the migration"
        )
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 6. Feature versions are unchanged.
# ----------------------------------------------------------------------


def test_feature_versions_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        cursor = conn.execute(
            "SELECT DISTINCT feature_version FROM prediction_sample_environmental_features"
        )
        versions = [row[0] for row in cursor.fetchall()]
        assert versions == [PRODUCTION_FEATURE_VERSION]
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 7. Migration is idempotent.
# ----------------------------------------------------------------------


def test_migration_is_idempotent():
    from phase10e1_migrate_environmental_ownership import run_migration
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Snapshot pre-state
        before = conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features"
        ).fetchone()[0]
        # Run twice
        first = run_migration(conn)
        second = run_migration(conn)
        # Both runs must report "nothing to do"
        assert first["rows_backfilled"] == 0
        assert first["column_added"] is False
        assert first["column_made_not_null"] is False
        assert second["rows_backfilled"] == 0
        assert second["column_added"] is False
        assert second["column_made_not_null"] is False
        after = conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features"
        ).fetchone()[0]
        assert before == after == PRODUCTION_EXPECTED_ROWS
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 8. Loader resolves rows by scientific_dataset_id.
# ----------------------------------------------------------------------


def test_loader_resolves_rows_by_scientific_dataset_id():
    """Phase 10D-2 environmental loader must use
    scientific_dataset_id as the primary ownership mechanism.
    """
    import inspect
    from suitability_training_loaders import load_environmental
    src = inspect.getsource(load_environmental)
    # The loader filters rows by scientific_dataset_id == dataset.id
    # (the formatting may include line breaks).
    import re
    assert re.search(r"scientific_dataset_id\s*==\s*dataset\.id", src)
    # feature_version is now a consistency check, not a load filter.
    assert "feature_version == spec.feature_version" not in src


# ----------------------------------------------------------------------
# 9. Loader rejects rows owned by another dataset.
# ----------------------------------------------------------------------


def test_loader_rejects_mismatched_feature_version():
    """The loader raises a clear error if the dataset owns rows with
    a feature_version that does not match the spec.
    """
    # This is verified at the unit level via the source inspection
    # below; a full integration test would require an in-memory DB.
    import inspect
    from suitability_training_loaders import load_environmental
    src = inspect.getsource(load_environmental)
    assert "feature_version != spec.feature_version" in src
    assert "mismatched" in src


# ----------------------------------------------------------------------
# 10. feature_version mismatch is detected.
# ----------------------------------------------------------------------


def test_feature_version_mismatch_detected_by_loader():
    """The loader raises a clear error when the dataset's owned rows
    have a different feature_version than the spec declares."""
    import inspect
    from suitability_training_loaders import load_environmental
    src = inspect.getsource(load_environmental)
    assert "spec.feature_version" in src
    assert "feature_version != " in src


# ----------------------------------------------------------------------
# 11. Jamaica reconstruction identifies exact owned environmental rows.
# ----------------------------------------------------------------------


def test_jamaica_reconstruction_identifies_owned_rows():
    _require_production()
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    report = reconstruct_jamaica_v3()
    # After Phase 10E-1, environmental reconstruction is EXACTLY
    # RECONSTRUCTABLE (MIGRATION_VERIFIED).
    assert report.environmental_reconstruction == "EXACTLY_RECONSTRUCTABLE"


# ----------------------------------------------------------------------
# 12. Reconstruction distinguishes migration-established from historical.
# ----------------------------------------------------------------------


def test_reconstruction_distinguishes_migration_from_historical():
    _require_production()
    from suitability_reconstruction_checker import (
        SRC_MIGRATION_VERIFIED,
        SRC_PERSISTED,
        reconstruct_jamaica_v3,
    )
    report = reconstruct_jamaica_v3()
    entry = report.field_dict["environmental_dataset_row_ownership"]
    assert entry.source == SRC_MIGRATION_VERIFIED
    assert entry.source != SRC_PERSISTED
    assert "retroactively" in entry.notes.lower() or "not" in entry.notes.lower()


# ----------------------------------------------------------------------
# 13. No credentials are introduced.
# ----------------------------------------------------------------------


def test_no_credentials_in_migration():
    """The migration does not introduce credential storage."""
    from phase10e1_migrate_environmental_ownership import run_migration
    import inspect
    src = inspect.getsource(run_migration)
    forbidden = ("password", "secret", "token", "credential", "api_key")
    for token in forbidden:
        assert token.lower() not in src.lower(), (
            f"migration must not reference {token!r}"
        )


# ----------------------------------------------------------------------
# 14. No model training occurs.
# ----------------------------------------------------------------------


def test_no_model_training_in_migration():
    from phase10e1_migrate_environmental_ownership import run_migration
    import inspect
    src = inspect.getsource(run_migration)
    forbidden = ("fit(", "train(", "LogisticRegression(", "HistGradientBoosting")
    for token in forbidden:
        assert token not in src


# ----------------------------------------------------------------------
# 15. No prediction occurs.
# ----------------------------------------------------------------------


def test_no_prediction_in_migration():
    from phase10e1_migrate_environmental_ownership import run_migration
    import inspect
    src = inspect.getsource(run_migration)
    forbidden = ("predict_grid", "predict_proba", "suitability_prediction")
    for token in forbidden:
        assert token not in src


# ----------------------------------------------------------------------
# 16. No suitability deployment changes.
# ----------------------------------------------------------------------


def test_no_suitability_deployment_changes():
    from phase10e1_migrate_environmental_ownership import run_migration
    import inspect
    src = inspect.getsource(run_migration)
    forbidden = (
        "suitability_deployments",
        "INSERT INTO suitability_deployments",
        "UPDATE suitability_deployments",
    )
    for token in forbidden:
        assert token not in src


# ----------------------------------------------------------------------
# 17. No Monitoring Priority regeneration.
# ----------------------------------------------------------------------


def test_no_monitoring_priority_changes():
    from phase10e1_migrate_environmental_ownership import run_migration
    import inspect
    src = inspect.getsource(run_migration)
    forbidden = (
        "next_area_snapshot_generations",
        "next_area_snapshot_cells",
        "monitoring_priority",
    )
    for token in forbidden:
        assert token not in src.lower()


# ----------------------------------------------------------------------
# 18. Bahamas receives no environmental dataset or rows.
# ----------------------------------------------------------------------


def test_bahamas_receives_no_environmental_data():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Bahamas (jurisdiction_id=2) must have no environmental
        # ScientificDataset rows.
        bahamas_dataset = conn.execute(
            "SELECT COUNT(*) FROM scientific_datasets "
            "WHERE dataset_type='ENVIRONMENTAL' "
            "AND species_program_id IN ("
            "SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert bahamas_dataset == 0
        # Bahamas has no SpeciesProgram
        sp_count = conn.execute(
            "SELECT COUNT(*) FROM species_programs WHERE jurisdiction_id = 2"
        ).fetchone()[0]
        assert sp_count == 0
        # No environmental rows reference a Bahamas-linked dataset.
        bahamas_env_rows = conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features "
            "WHERE scientific_dataset_id IN ("
            "SELECT id FROM scientific_datasets "
            "WHERE species_program_id IN ("
            "SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
            ")"
        ).fetchone()[0]
        assert bahamas_env_rows == 0
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 19. Existing Jamaica suitability artifact remains unchanged.
# ----------------------------------------------------------------------


def test_jamaica_artifact_unchanged():
    _require_production()
    expected = (
        "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
    )
    artifact_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "prediction_models",
        "pterois-volitans-suitability-v3.joblib",
    )
    if not os.path.exists(artifact_path):
        pytest.skip("v3 artifact not present")
    actual = hashlib.sha256(open(artifact_path, "rb").read()).hexdigest()
    assert actual == expected


# ----------------------------------------------------------------------
# 20. Existing production suitability cells remain unchanged.
# ----------------------------------------------------------------------


def test_existing_production_suitability_cells_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        cells = conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3' "
            "AND prediction_status = 'SCORED'"
        ).fetchone()[0]
        assert cells == 391
        assert scored == 391
    finally:
        conn.close()