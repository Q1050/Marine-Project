"""Phase 10E-3 focused tests: immutable native training configuration.

Run only:
    pytest test_phase10e3_immutable_configuration.py -v
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------



def _minimal_spec_kwargs(**overrides):
    from suitability_training_spec import SuitabilityGrid
    base = {
        "background_extent_bounds": {
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        "spatial_block_origin": {
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        "grid": SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ),
    }
    base.update(overrides)
    return base
def _db_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def _require_production():
    if not os.path.exists(_db_path()):
        pytest.skip("Production DB not present")


def _make_minimal_provenance_db():
    """Create an in-memory SQLite DB with the Phase 10E-2 / 10E-3
    schema populated with a single SpeciesProgram, two
    ScientificDatasets, and a SuitabilityDeployment.
    """
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    import models  # noqa: F401
    from database import Base

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


def _seed_minimal(SessionLocal):
    import models
    db = SessionLocal()
    try:
        region = models.Region(name="r", slug="r", status="ACTIVE")
        db.add(region); db.flush()
        jurisdiction = models.Jurisdiction(
            region_id=region.id, name="j", slug="j", country_code="JM",
            center_latitude=0.0, center_longitude=0.0, default_zoom=5.0,
        )
        db.add(jurisdiction); db.flush()
        species = models.Species(scientific_name="Hyp sp.", aphia_id=999)
        db.add(species); db.flush()
        program = models.SpeciesProgram(
            jurisdiction_id=jurisdiction.id, scientific_name="Hyp sp.",
            status="ACTIVE", species_id=species.id,
        )
        db.add(program); db.flush()
        occ = models.ScientificDataset(
            slug="hyp-occ", name="Hyp occ", dataset_type="OCCURRENCE",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="JURISDICTION",
            region_id=region.id, jurisdiction_id=jurisdiction.id,
            source_name="TEST", record_count=2,
        )
        db.add(occ); db.flush()
        env = models.ScientificDataset(
            slug="hyp-env", name="Hyp env", dataset_type="ENVIRONMENTAL",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="REGION", region_id=region.id,
            jurisdiction_id=None, source_name="TEST", record_count=2,
        )
        db.add(env); db.flush()
        habitat = models.HabitatSuitabilityModel(
            model_version="hyp-v1", scientific_name="Hyp sp.",
            algorithm="LogisticRegression", feature_list_json="[]",
            training_generation_version="gen-v1",
            training_sample_count=10, eligible_presence_count=5,
            eligible_background_count=5, spatial_block_count=1,
            validation_metrics_json="{}", coefficients_json="{}",
            artifact_path="/tmp/none.joblib",
        )
        db.add(habitat); db.flush()
        dep = models.SuitabilityDeployment(
            species_program_id=program.id,
            habitat_suitability_model_id=habitat.id,
            model_version="hyp-v1", status="ACTIVE",
        )
        db.add(dep); db.flush()
        db.commit()
        return program.id, occ.id, env.id
    finally:
        db.close()


def _make_spec(**overrides):
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-77.5, -77.0, 18.0, 18.5),
        name="hypothetical-grid",
    )
    base = dict(
        species="Hyp sp.",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        region_id=1,
        jurisdiction_id=1,
        occurrence_dataset_id=10,
        environmental_dataset_ids=(11,),
        feature_version="hypothetical-environment-v1",
        generation_version="hypothetical-grid-v1",
        model_version="hyp-v1",
        random_seed=4242,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        grid=grid,
    )
    base.update(overrides)
    helper = _minimal_spec_kwargs()
    helper = {k: v for k, v in helper.items() if k not in base}
    return SuitabilityTrainingSpec(
        **base,
        **helper,
    )


def _make_minimal_result(spec, selected_candidate="model_x"):
    """Build a minimal SuitabilityTrainingResult."""
    from suitability_training_engine import (
        SuitabilityCandidateResult, SuitabilityTrainingResult,
    )
    from sklearn.linear_model import LogisticRegression
    return SuitabilityTrainingResult(
        spec_snapshot=dataclasses.asdict(spec),
        candidate_results={
            selected_candidate: SuitabilityCandidateResult(
                name=selected_candidate,
                features=("a", "b"),
                algorithm="LogisticRegression",
                nonlinear=False,
                fold_metrics=[{"roc_auc": 0.7}],
                aggregate={
                    "roc_auc": {"mean": 0.7, "std": 0.0},
                    "average_precision": {"mean": 0.7, "std": 0.0},
                },
                extra={},
            ),
        },
        selected_candidate_name=selected_candidate,
        selection_rationale={"rule": "test"},
        fitted_model=LogisticRegression(),
        selected_feature_names=("a", "b"),
        training_sample_count=10,
        presence_count=5,
        background_count=5,
        feature_names=("a", "b"),
        dataset_provenance={"occurrence_dataset_id": 10},
        artifact_path=None,
        artifact_sha256=None,
        warnings=[],
        feature_version="hypothetical-environment-v1",
        model_version="hyp-v1",
        generation_version="hypothetical-grid-v1",
    )


# ----------------------------------------------------------------------
# 1. Native snapshot contains all training-scientific configuration.
# ----------------------------------------------------------------------


def test_native_snapshot_contains_all_training_scientific_configuration():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    # Identity
    for k in ("species", "species_program_id", "geographic_scope",
              "region_id", "jurisdiction_id"):
        assert k in s, f"missing key {k}"
    # Datasets
    assert s["occurrence_dataset_id"] == 10
    assert s["environmental_dataset_ids"] == [11]
    # Features + ordering
    assert isinstance(s["physical_features"], list)
    assert isinstance(s["climate_features"], list)
    assert s["feature_order"] == s["physical_features"] + s["climate_features"]
    # Candidates
    assert isinstance(s["candidate_models"], list)
    assert all("name" in c and "features" in c for c in s["candidate_models"])
    # Hyperparameters
    assert s["logistic_hyperparameters"]["estimator_family"] == "LogisticRegression"
    assert s["nonlinear_hyperparameters"]["estimator_family"] == \
        "HistGradientBoostingClassifier"
    # Sampling
    assert s["random_seed"] == 4242
    assert s["background_ratio"] == 5
    assert "background_extent" in s
    # Spatial blocking
    assert s["spatial_block_size_degrees"] == 5.0
    assert "spatial_block_origin" in s
    # CV
    assert s["cv_folds"] == 2
    assert s["cv_strategy"]["method"] == "StratifiedGroupKFold"
    assert s["cv_strategy"]["shuffle"] is True
    assert "primary_selection_metrics" in s
    # Selection
    assert "selection_geography_threshold" in s
    assert "selection_rule_text" in s
    # Training extent
    assert "training_extent" in s
    # Prediction grid
    assert "prediction_grid" in s
    assert "grid" in s
    # Band thresholds
    assert s["suitability_band_thresholds"] == [0.2, 0.4, 0.6, 0.8]
    # Versions
    assert s["model_version"] == "hyp-v1"
    assert s["feature_version"] == "hypothetical-environment-v1"
    assert s["generation_version"] == "hypothetical-grid-v1"
    # Artifact format
    assert s["artifact_format"] == "joblib"


# ----------------------------------------------------------------------
# 2. Candidate hyperparameters are persisted.
# ----------------------------------------------------------------------


def test_candidate_hyperparameters_are_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    # The current engine exposes logistic and nonlinear hyperparameters
    # at the snapshot level (not per-candidate) so that the snapshot
    # documents the two estimator families and their params.
    assert s["logistic_hyperparameters"]["transformer"] == "StandardScaler"
    assert s["logistic_hyperparameters"]["classifier_class_weight"] == \
        "balanced"
    assert s["logistic_hyperparameters"]["classifier_max_iter"] == 1000
    assert s["nonlinear_hyperparameters"]["learning_rate"] == 0.08
    assert s["nonlinear_hyperparameters"]["max_iter"] == 200
    assert s["nonlinear_hyperparameters"]["max_leaf_nodes"] == 15
    assert s["nonlinear_hyperparameters"]["l2_regularization"] == 1.0
    assert s["nonlinear_hyperparameters"]["permutation_importance_n_repeats"] == 10


# ----------------------------------------------------------------------
# 3. Training extent is persisted.
# ----------------------------------------------------------------------


def test_training_extent_is_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    assert s["training_extent"]["latitude_min"] == 9.0
    assert s["training_extent"]["latitude_max"] == 28.0
    assert s["training_extent"]["longitude_min"] == -89.0
    assert s["training_extent"]["longitude_max"] == -59.0
    assert s["background_extent"] == s["training_extent"]


# ----------------------------------------------------------------------
# 4. Prediction grid is persisted.
# ----------------------------------------------------------------------


def test_prediction_grid_is_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    assert s["grid"]["name"] == "hypothetical-grid"
    assert s["grid"]["bounds"] == [-77.5, -77.0, 18.0, 18.5]
    assert s["grid"]["grid_size_degrees"] == 0.1
    assert s["prediction_grid"] == s["grid"]


# ----------------------------------------------------------------------
# 5. Background extent is persisted.
# ----------------------------------------------------------------------


def test_background_extent_is_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    assert "background_extent" in s
    assert s["background_extent"]["latitude_min"] == 9.0
    assert s["background_extent"]["latitude_max"] == 28.0
    assert s["background_extent"]["longitude_min"] == -89.0
    # The Caribbean extent has latitude_max=28, longitude_max=-59.
    # Verify both endpoints of the longitude axis.
    assert s["background_extent"]["longitude_max"] == -59.0
    assert s["background_extent"]["longitude_min"] < s["background_extent"]["longitude_max"]
    assert s["background_extent"]["longitude_min"] < s["background_extent"]["longitude_max"]


# ----------------------------------------------------------------------
# 6. Band thresholds are persisted.
# ----------------------------------------------------------------------


def test_band_thresholds_are_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    assert s["suitability_band_thresholds"] == [0.2, 0.4, 0.6, 0.8]


# ----------------------------------------------------------------------
# 7. CV method and shuffle behavior are persisted.
# ----------------------------------------------------------------------


def test_cv_method_and_shuffle_are_persisted():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_spec()
    s = build_configuration_snapshot(spec)
    assert s["cv_strategy"]["method"] == "StratifiedGroupKFold"
    assert s["cv_strategy"]["shuffle"] is True
    assert s["cv_strategy"]["random_state_source"] == "spec.random_seed"


# ----------------------------------------------------------------------
# 8. Canonical serialization is deterministic.
# ----------------------------------------------------------------------


def test_canonical_serialization_is_deterministic():
    from suitability_training_run_repository import (
        canonical_configuration_json,
    )
    a = {"a": 1, "b": [3, 2, 1], "c": {"z": 1, "y": 2}}
    b = {"c": {"y": 2, "z": 1}, "b": [3, 2, 1], "a": 1}
    assert canonical_configuration_json(a) == canonical_configuration_json(b)


# ----------------------------------------------------------------------
# 9. Identical specs produce identical SHA.
# ----------------------------------------------------------------------


def test_identical_specs_produce_identical_sha():
    from suitability_training_run_repository import (
        build_configuration_snapshot, compute_configuration_sha256,
    )
    a = build_configuration_snapshot(_make_spec())
    b = build_configuration_snapshot(_make_spec())
    assert compute_configuration_sha256(a) == compute_configuration_sha256(b)


# ----------------------------------------------------------------------
# 10. Meaningful config change changes SHA.
# ----------------------------------------------------------------------


def test_meaningful_change_changes_sha():
    from suitability_training_run_repository import (
        build_configuration_snapshot, compute_configuration_sha256,
    )
    a = build_configuration_snapshot(_make_spec(random_seed=1))
    b = build_configuration_snapshot(_make_spec(random_seed=2))
    assert compute_configuration_sha256(a) != compute_configuration_sha256(b)


# ----------------------------------------------------------------------
# 11. NATIVE run requires a complete configuration.
# ----------------------------------------------------------------------


def test_native_run_requires_complete_configuration():
    """A native run with schema_version != 2 cannot be COMPLETED."""
    from suitability_training_run_repository import (
        STATUS_BUILDING, build_configuration_snapshot,
        create_training_run, record_training_completion,
        validate_native_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        # Downgrade schema_version to a wrong value to force failure.
        config = json.loads(run.configuration_json)
        config["schema_version"] = 999
        run.configuration_json = json.dumps(config)
        run.configuration_sha256 = None
        # Now validation must fail.
        result = _make_minimal_result(spec)
        with pytest.raises(ValueError):
            validate_native_completion(db, run, result)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 12. Dataset links must match configuration IDs.
# ----------------------------------------------------------------------


def test_dataset_links_must_match_configuration():
    from suitability_training_run_repository import (
        ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES,
        STATUS_BUILDING, build_configuration_snapshot,
        create_training_run, link_training_run_dataset,
        record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        # Tamper with the persisted configuration to introduce a mismatch.
        config = json.loads(run.configuration_json)
        config["occurrence_dataset_id"] = 9999
        run.configuration_json = json.dumps(config)
        from suitability_training_run_repository import (
            compute_configuration_sha256,
        )
        run.configuration_sha256 = compute_configuration_sha256(config)
        # No link to dataset 9999 exists.
        result = _make_minimal_result(spec)
        with pytest.raises(ValueError):
            record_training_completion(db, run, result)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 13. Missing occurrence link prevents completion.
# ----------------------------------------------------------------------


def test_missing_occurrence_link_prevents_completion():
    from suitability_training_run_repository import (
        ROLE_ENVIRONMENTAL_INPUT, STATUS_BUILDING,
        create_training_run, link_training_run_dataset, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        # Only link environmental; omit occurrence.
        env_dataset = db.query(__import__("models").ScientificDataset).filter(
            __import__("models").ScientificDataset.id == env_id
        ).one()
        link_training_run_dataset(db, run, env_dataset, ROLE_ENVIRONMENTAL_INPUT)
        result = _make_minimal_result(spec)
        with pytest.raises(ValueError):
            record_training_completion(db, run, result)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 14. Missing environmental link prevents completion.
# ----------------------------------------------------------------------


def test_missing_environmental_link_prevents_completion():
    from suitability_training_run_repository import (
        ROLE_TRAINING_OCCURRENCES, STATUS_BUILDING,
        create_training_run, link_training_run_dataset, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        occ_dataset = db.query(__import__("models").ScientificDataset).filter(
            __import__("models").ScientificDataset.id == occ_id
        ).one()
        link_training_run_dataset(db, run, occ_dataset, ROLE_TRAINING_OCCURRENCES)
        result = _make_minimal_result(spec)
        with pytest.raises(ValueError):
            record_training_completion(db, run, result)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 15. Selected candidate must exist in configured candidates.
# ----------------------------------------------------------------------


def test_selected_candidate_must_exist_in_configured():
    from suitability_training_run_repository import (
        ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES,
        create_training_run, link_training_run_dataset,
        record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        occ = db.query(__import__("models").ScientificDataset).filter(
            __import__("models").ScientificDataset.id == occ_id
        ).one()
        env = db.query(__import__("models").ScientificDataset).filter(
            __import__("models").ScientificDataset.id == env_id
        ).one()
        link_training_run_dataset(db, run, occ, ROLE_TRAINING_OCCURRENCES)
        link_training_run_dataset(db, run, env, ROLE_ENVIRONMENTAL_INPUT)
        # Selected candidate not in configured candidates.
        result = _make_minimal_result(spec, selected_candidate="ghost_candidate")
        with pytest.raises(ValueError):
            record_training_completion(db, run, result)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 16. Completed configuration cannot be changed.
# ----------------------------------------------------------------------


def test_completed_configuration_cannot_be_changed():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_COMPLETED,
        assert_completed_immutable,
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        # BUILDING is mutable.
        assert_completed_immutable(run, "configuration_json")
        # COMPLETED raises.
        result = _make_minimal_result(spec)
        record_training_completion(
            db, run, result, skip_validation=True,
        )
        db.commit()
        assert run.status == STATUS_COMPLETED
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "configuration_json")
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "configuration_sha256")
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "artifact_sha256")
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 17. Completed dataset links cannot be changed through repository API.
# ----------------------------------------------------------------------


def test_completed_dataset_links_cannot_be_changed():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_COMPLETED,
        create_training_run, link_training_run_dataset,
        record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        record_training_completion(
            db, run, result, skip_validation=True,
        )
        db.commit()
        assert run.status == STATUS_COMPLETED
        # Attempt to add a new link must fail.
        from models import ScientificDataset
        # Re-link an existing dataset via a third role.
        occ = db.query(ScientificDataset).filter(
            ScientificDataset.id == occ_id
        ).one()
        with pytest.raises(ValueError):
            link_training_run_dataset(
                db, run, occ, "ENVIRONMENTAL_INPUT"
            )
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 18. Completed artifact SHA cannot be changed.
# ----------------------------------------------------------------------


def test_completed_artifact_sha_cannot_be_changed():
    """The repository's assert_completed_immutable guard refuses
    silent changes to artifact_sha256 after COMPLETED."""
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_COMPLETED,
        assert_completed_immutable, create_training_run,
        record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        record_training_completion(
            db, run, result, skip_validation=True,
        )
        db.commit()
        assert run.status == STATUS_COMPLETED
        # The application-level guard fires for any mutation attempt.
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "artifact_sha256")
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 19. Failed runs can retain partial diagnostics without completion.
# ----------------------------------------------------------------------


def test_failed_run_retains_diagnostics_without_completion():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_FAILED,
        create_training_run, record_training_failure,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        record_training_failure(
            db, run, "inconclusive fit", warnings=["step 1", "step 2"],
        )
        db.commit()
        assert run.status == STATUS_FAILED
        assert "inconclusive fit" in run.failure_reason
        # FAILED runs do NOT need validation; configuration_sha256
        # may be present from creation but the run is not promoted.
        assert run.configuration_sha256 is not None
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 20. Legacy Jamaica remains LEGACY_RECONSTRUCTED.
# ----------------------------------------------------------------------


def test_legacy_jamaica_remains_legacy_reconstructed():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            "SELECT provenance_origin, configuration_sha256 "
            "FROM training_runs WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "LEGACY_RECONSTRUCTED"
        assert row[1] is not None  # backfilled by Phase 10E-3
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 21. Legacy configuration hash does not change provenance classification.
# ----------------------------------------------------------------------


def test_legacy_hash_does_not_change_provenance_classification():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            "SELECT configuration_json FROM training_runs WHERE id = 1"
        ).fetchone()
        snapshot = json.loads(row[0])
        # The legacy snapshot must still carry the
        # _provenance_classification map.
        assert "_provenance_classification" in snapshot
        classification = snapshot["_provenance_classification"]
        assert classification["random_seed"] == "SOURCE_CONFIG"
        assert classification["selection_geography_threshold"] == \
            "SOURCE_CONFIG"
        assert classification["species_program_id"] == "PERSISTED"
        assert classification["dataset_ids"] == "PERSISTED"
        # And the hash verifies the reconstructed snapshot as stored;
        # it does not prove historical provenance.
        assert snapshot["schema_version"] == 1
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 22. No training is executed.
# ----------------------------------------------------------------------


def test_no_training_is_executed():
    import inspect
    import suitability_training_run_repository as repo
    # Look for actual training call sites, not class-name mentions
    # in import statements or string literals.
    forbidden = (
        ".fit(",
        ".fit_candidates(",
        "StratifiedGroupKFold(n_splits=",
        "_logistic_pipeline(",
        "_nonlinear_pipeline(",
    )
    src = inspect.getsource(repo)
    for token in forbidden:
        assert token not in src, (
            f"repository must not execute training: {token!r}"
        )


# ----------------------------------------------------------------------
# 23. No deployment activation occurs.
# ----------------------------------------------------------------------


def test_no_deployment_activation():
    import inspect
    import suitability_training_run_repository as repo
    src = inspect.getsource(repo)
    forbidden = (
        "INSERT INTO suitability_deployments",
        "UPDATE suitability_deployments SET status",
        "status = 'ACTIVE'",
    )
    for token in forbidden:
        assert token not in src


# ----------------------------------------------------------------------
# 24. Existing scientific state remains unchanged.
# ----------------------------------------------------------------------


def test_existing_scientific_state_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 12
        assert conn.execute("SELECT COUNT(*) FROM historical_occurrences").fetchone()[0] == 54
        assert conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0] == 391
        active_gens = conn.execute(
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
        ).fetchall()
        assert active_gens == [(2,)]
        assert conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_v3_artifact_sha_unchanged():
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
# Additional: configuration snapshot hash is computed at creation.
# ----------------------------------------------------------------------


def test_create_training_run_persists_configuration_sha256():
    from suitability_training_run_repository import (
        STATUS_BUILDING,
        build_configuration_snapshot,
        compute_configuration_sha256,
        create_training_run,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    spec = _make_spec(
        species_program_id=program_id,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
    )
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        db.commit()
        assert run.configuration_sha256 is not None
        expected = compute_configuration_sha256(
            build_configuration_snapshot(spec)
        )
        assert run.configuration_sha256 == expected
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# Additional: migration idempotency.
# ----------------------------------------------------------------------


def test_migration_is_idempotent():
    from phase10e3_migrate_configuration_sha256 import run_migration
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        first = run_migration(conn)
        second = run_migration(conn)
        assert first["configuration_sha256_added"] is False
        assert second["configuration_sha256_added"] is False
    finally:
        conn.close()