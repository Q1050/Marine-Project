"""Phase 10D-5 focused tests for the Jamaica v3 reconstruction checker.

Run only:
    pytest test_phase10d5_reconstruction_checker.py -v

These tests verify:
- the checker resolves the production deployment
- artifact SHA matches the expected production SHA
- field-by-field provenance classifications are correct
- occurrence and environmental inputs are classified accurately
- the checker performs NO training, NO prediction, NO DB mutation
- production state (cells, monitoring priority, Bahamas deployments)
  remains unchanged
"""

from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest


EXPECTED_SHA = (
    "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
)


def _db_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def _artifact_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "prediction_models",
        "pterois-volitans-suitability-v3.joblib",
    )


def _require_production():
    """Skip the test if the production DB / artifact is not present."""
    db = _db_path()
    artifact = _artifact_path()
    if not os.path.exists(db) or not os.path.exists(artifact):
        pytest.skip("Production DB or v3 artifact not present")


# ----------------------------------------------------------------------
# 1. Jamaica v3 target resolves.
# ----------------------------------------------------------------------


def test_jamaica_v3_target_resolves():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.target_species == "Pterois volitans"
    assert report.target_jurisdiction == "Jamaica"
    assert report.target_model_version == "pterois-volitans-suitability-v3"


# ----------------------------------------------------------------------
# 2. Correct SpeciesProgram resolves.
# ----------------------------------------------------------------------


def test_species_program_resolves():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    fields = report.field_dict
    assert fields["species_program_id"].value == 1
    assert fields["jurisdiction"].value == "Jamaica"
    assert fields["region"].value == "Caribbean"


# ----------------------------------------------------------------------
# 3. Correct occurrence dataset resolves.
# ----------------------------------------------------------------------


def test_occurrence_dataset_resolves():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    fields = report.field_dict
    assert fields["occurrence_scientific_dataset_id"].value == 1
    assert fields["occurrence_scientific_dataset_slug"].value == (
        "pterois-volitans-jamaica-obis-iNaturalist-2025-08"
    )
    assert fields["occurrence_geographic_ownership"].value == "JURISDICTION"


# ----------------------------------------------------------------------
# 4. Exactly 54 historical occurrence rows resolve.
# ----------------------------------------------------------------------


def test_exactly_54_historical_occurrences_resolve():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    fields = report.field_dict
    assert fields["historical_occurrence_rows_resolved"].value == 54
    assert report.occurrence_reconstruction == "EXACTLY_RECONSTRUCTABLE"


# ----------------------------------------------------------------------
# 5. Correct environmental dataset resolves.
# ----------------------------------------------------------------------


def test_environmental_dataset_resolves():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    fields = report.field_dict
    assert fields["environmental_scientific_dataset_id"].value == 2
    assert fields["environmental_scientific_dataset_slug"].value == (
        "pterois-volitans-environmental-caribbean-grid-v2-environment-v1"
    )
    assert fields["environmental_geographic_ownership"].value == "REGION"


# ----------------------------------------------------------------------
# 6. Artifact SHA matches expected production SHA.
# ----------------------------------------------------------------------


def test_artifact_sha_matches_expected():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.artifact_sha256_matches is True
    assert report.artifact_sha256_expected == EXPECTED_SHA
    assert report.artifact_sha256_observed == EXPECTED_SHA
    # Also verify the deployment row's persisted hash matches.
    fields = report.field_dict
    assert fields["artifact_sha256_persisted"].value == EXPECTED_SHA


# ----------------------------------------------------------------------
# 7. Training geography and prediction grid are reported separately.
# ----------------------------------------------------------------------


def test_training_geography_and_prediction_grid_reported_separately():
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.training_geography["latitude_min"] == 9.0
    assert report.training_geography["latitude_max"] == 28.0
    assert report.training_geography["longitude_min"] == -89.0
    assert report.training_geography["longitude_max"] == -59.0
    assert report.prediction_grid["bounds"] == [-78.6, -75.9, 16.9, 18.7]
    assert report.prediction_grid["grid_size_degrees"] == 0.1
    # They must NOT be conflated: the prediction grid is a strict subset
    # of the training geography.
    tl = report.training_geography
    pg_bounds = report.prediction_grid["bounds"]
    assert tl["latitude_min"] <= pg_bounds[2] < pg_bounds[3] <= tl["latitude_max"]
    assert tl["longitude_min"] <= pg_bounds[0] < pg_bounds[1] <= tl["longitude_max"]


# ----------------------------------------------------------------------
# 8. Persisted values are labeled PERSISTED.
# ----------------------------------------------------------------------


def test_persisted_values_labeled_persisted():
    from suitability_reconstruction_checker import (
        SRC_PERSISTED,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    expected_persisted_fields = {
        "canonical_species",
        "species_program_id",
        "jurisdiction",
        "region",
        "occurrence_scientific_dataset_id",
        "occurrence_scientific_dataset_slug",
        "occurrence_geographic_ownership",
        "occurrence_species_ownership",
        "occurrence_source_reference",
        "occurrence_source_version",
        "occurrence_record_count_dataset",
        "historical_occurrence_rows_resolved",
        "environmental_scientific_dataset_id",
        "environmental_scientific_dataset_slug",
        "environmental_geographic_ownership",
        "environmental_source_reference",
        "environmental_source_version",
        "environmental_record_count_dataset",
        "environmental_feature_version",
        "environmental_feature_rows_total",
        "feature_list",
        "feature_version",
        "model_version",
        "generation_version",
        "selected_candidate",
        "algorithm",
        "artifact_path",
        "artifact_sha256_persisted",
        "deployment_status",
        "training_sample_count_persisted",
        "eligible_presence_count_persisted",
        "eligible_background_count_persisted",
        "spatial_block_count_persisted",
    }
    for field_name in expected_persisted_fields:
        entry = report.field_dict[field_name]
        assert entry.source == SRC_PERSISTED, (
            f"expected PERSISTED for {field_name}, got {entry.source}"
        )


# ----------------------------------------------------------------------
# 9. Compatibility/source constants are labeled SOURCE_CONFIG.
# ----------------------------------------------------------------------


def test_compatibility_constants_labeled_source_config():
    from suitability_reconstruction_checker import (
        SRC_SOURCE_CONFIG,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    expected_source_config_fields = {
        "candidate_models",
        "logistic_hyperparameters",
        "nonlinear_hyperparameters",
        "random_seed",
        "depth_strata",
        "max_presence_depth_m",
        "selection_geography_threshold",
        "selection_rule_text",
        "training_geography_bounds",
        "prediction_grid_bounds",
        "prediction_grid_size_degrees",
        "suitability_band_thresholds",
    }
    for field_name in expected_source_config_fields:
        entry = report.field_dict[field_name]
        assert entry.source == SRC_SOURCE_CONFIG, (
            f"expected SOURCE_CONFIG for {field_name}, got {entry.source}"
        )


# ----------------------------------------------------------------------
# 10. Missing provenance is not mislabeled as persisted.
# ----------------------------------------------------------------------


def test_missing_provenance_not_mislabeled():
    """After Phase 10E-1, environmental_dataset_row_ownership is
    MIGRATION_VERIFIED (not PERSISTED, not MISSING). It must not be
    mislabeled as PERSISTED because the FK did NOT exist at the
    original training time.
    """
    from suitability_reconstruction_checker import (
        SRC_MIGRATION_VERIFIED,
        SRC_PERSISTED,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    entry = report.field_dict["environmental_dataset_row_ownership"]
    assert entry.source == SRC_MIGRATION_VERIFIED
    assert entry.source != SRC_PERSISTED


# ----------------------------------------------------------------------
# 11. Environmental ownership limitation is reported.
# ----------------------------------------------------------------------


def test_environmental_ownership_limitation_reported():
    """After Phase 10E-1 the environmental row set is
    EXACTLY_RECONSTRUCTABLE but classified as MIGRATION_VERIFIED
    (not historically PERSISTED). The notes must say so.
    """
    from suitability_reconstruction_checker import reconstruct_jamaica_v3
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.environmental_reconstruction == "EXACTLY_RECONSTRUCTABLE"
    fields = report.field_dict
    notes = fields["environmental_dataset_row_ownership"].notes.lower()
    assert "migration" in notes
    assert "retroactively" in notes or "not" in notes.lower()


# ----------------------------------------------------------------------
# 12. Configuration reconstruction receives a conservative status.
# ----------------------------------------------------------------------


def test_configuration_reconstruction_conservative_status():
    from suitability_reconstruction_checker import (
        STATUS_FULL,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.configuration_reconstruction != STATUS_FULL


# ----------------------------------------------------------------------
# 13. Scientific input reconstruction receives a conservative status.
# ----------------------------------------------------------------------


def test_scientific_input_reconstruction_conservative_status():
    from suitability_reconstruction_checker import (
        STATUS_FULL,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.scientific_input_reconstruction != STATUS_FULL


# ----------------------------------------------------------------------
# 14. Byte-identical reproducibility is NOT claimed without evidence.
# ----------------------------------------------------------------------


def test_byte_identical_reproducibility_not_claimed():
    from suitability_reconstruction_checker import (
        STATUS_PROVEN,
        reconstruct_jamaica_v3,
    )
    _require_production()
    report = reconstruct_jamaica_v3()
    assert report.byte_identical_reproducibility != STATUS_PROVEN


# ----------------------------------------------------------------------
# 15. Checker performs no model training.
# ----------------------------------------------------------------------


def test_checker_performs_no_model_training():
    import suitability_reconstruction_checker as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "train(",
        "fit(",
        "fit_candidates",
        "fit_final_model",
        "model.fit(",
        "LogisticRegression(",
        "HistGradientBoostingClassifier(",
        "StratifiedGroupKFold(",
    )
    for token in forbidden:
        assert token not in src, (
            f"checker must not perform training: {token!r}"
        )


# ----------------------------------------------------------------------
# 16. Checker performs no grid prediction.
# ----------------------------------------------------------------------


def test_checker_performs_no_grid_prediction():
    import suitability_reconstruction_checker as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "predict_grid",
        "predict_proba",
        "suitability_prediction_engine",
    )
    for token in forbidden:
        assert token not in src, (
            f"checker must not perform prediction: {token!r}"
        )


# ----------------------------------------------------------------------
# 17. Checker performs no database mutation.
# ----------------------------------------------------------------------


def test_checker_performs_no_db_mutation():
    import suitability_reconstruction_checker as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "db.add",
        "session.add",
        ".commit",
        "conn.execute(\"INSERT",
        "conn.execute(\"UPDATE",
        "conn.execute(\"DELETE",
    )
    for token in forbidden:
        assert token not in src, (
            f"checker must not perform DB mutations: {token!r}"
        )


# ----------------------------------------------------------------------
# 18. Existing production suitability cells remain unchanged.
# ----------------------------------------------------------------------


def test_existing_suitability_v3_cells_unchanged():
    db = _db_path()
    if not os.path.exists(db):
        pytest.skip("Production DB not present in this environment")
    conn = sqlite3.connect(db)
    try:
        cells = conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0]
        assert cells == 391
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 19. Existing Monitoring Priority state remains unchanged.
# ----------------------------------------------------------------------


def test_existing_monitoring_priority_state_unchanged():
    db = _db_path()
    if not os.path.exists(db):
        pytest.skip("Production DB not present in this environment")
    conn = sqlite3.connect(db)
    try:
        active_generation = conn.execute(
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
        ).fetchall()
        assert active_generation == [(2,)]
        active_cells = conn.execute(
            "SELECT COUNT(*) FROM next_area_snapshot_cells "
            "WHERE generation_id IN ("
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
            ")"
        ).fetchone()[0]
        assert active_cells == 390
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 20. Bahamas remains without suitability deployment.
# ----------------------------------------------------------------------


def test_bahamas_remains_without_deployment():
    db = _db_path()
    if not os.path.exists(db):
        pytest.skip("Production DB not present in this environment")
    conn = sqlite3.connect(db)
    try:
        deployments = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert deployments == 0
    finally:
        conn.close()