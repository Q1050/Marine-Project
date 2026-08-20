"""Phase 10E-2 focused tests: TrainingRun provenance model.

Run only:
    pytest test_phase10e2_training_run.py -v
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror the production data shape with in-memory SQLite).
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
    """Create a tiny in-memory SQLite DB with the Phase 10E-2 schema
    populated with a single SpeciesProgram, two ScientificDatasets,
    and a SuitabilityDeployment. Used by the repository unit tests.
    """
    import sqlalchemy
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


def _seed_minimal_provenance_db(SessionLocal):
    """Insert a single SpeciesProgram + two ScientificDatasets +
    a SuitabilityDeployment. Returns (program_id, occ_dataset_id,
    env_dataset_id, deployment_id, run_id).
    """
    import models
    db = SessionLocal()
    try:
        # We need Region + Jurisdiction for FK constraints.
        region = models.Region(name="r1", slug="r1", status="ACTIVE")
        db.add(region); db.flush()
        jurisdiction = models.Jurisdiction(
            region_id=region.id, name="j1", slug="j1", country_code="JM",
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
        occ_dataset = models.ScientificDataset(
            slug="hyp-occ", name="Hyp occ", dataset_type="OCCURRENCE",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="JURISDICTION",
            region_id=region.id, jurisdiction_id=jurisdiction.id,
            source_name="TEST", record_count=2,
        )
        db.add(occ_dataset); db.flush()
        env_dataset = models.ScientificDataset(
            slug="hyp-env", name="Hyp env", dataset_type="ENVIRONMENTAL",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="REGION", region_id=region.id,
            jurisdiction_id=None, source_name="TEST", record_count=2,
        )
        db.add(env_dataset); db.flush()
        habitat_model = models.HabitatSuitabilityModel(
            model_version="hyp-v1", scientific_name="Hyp sp.",
            algorithm="LogisticRegression", feature_list_json="[]",
            training_generation_version="gen-v1",
            training_sample_count=10, eligible_presence_count=5,
            eligible_background_count=5, spatial_block_count=1,
            validation_metrics_json="{}", coefficients_json="{}",
            artifact_path="/tmp/none.joblib",
        )
        db.add(habitat_model); db.flush()
        deployment = models.SuitabilityDeployment(
            species_program_id=program.id,
            habitat_suitability_model_id=habitat_model.id,
            model_version="hyp-v1", status="ACTIVE",
        )
        db.add(deployment); db.flush()
        db.commit()
        return (
            program.id, occ_dataset.id, env_dataset.id, deployment.id,
        )
    finally:
        db.close()


def _make_minimal_spec(**overrides):
    from suitability_training_spec import SuitabilityGrid, SuitabilityTrainingSpec
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
    # Remove helper keys already supplied by `base` to avoid
    # duplicate-kwarg errors when callers pre-supply their own grid.
    helper = {k: v for k, v in helper.items() if k not in base}
    return SuitabilityTrainingSpec(
        **base,
        **helper,
    )


def _make_minimal_result(spec, selected_candidate="model_x", fitted_model=None):
    """Build a minimal SuitabilityTrainingResult."""
    from suitability_training_engine import (
        SuitabilityCandidateResult, SuitabilityTrainingResult,
    )
    if fitted_model is None:
        from sklearn.linear_model import LogisticRegression
        fitted_model = LogisticRegression()
    return SuitabilityTrainingResult(
        spec_snapshot=dataclasses.asdict(spec),
        candidate_results={
            "model_x": SuitabilityCandidateResult(
                name="model_x",
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
        selected_candidate_name="model_x",
        selection_rationale={"rule": "test"},
        fitted_model=fitted_model,
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


# ---------------------------------------------------------------------------
# 1. TrainingRun can represent a future native run.
# ---------------------------------------------------------------------------


def test_training_run_represents_future_native_run():
    from suitability_training_run_repository import (
        ORIGIN_NATIVE, STATUS_BUILDING, create_training_run,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        db.commit()
        assert run.id is not None
        assert run.status == STATUS_BUILDING
        assert run.provenance_origin == ORIGIN_NATIVE
        assert run.species_program_id == program_id
        assert run.model_version == "hyp-v1"
        assert run.started_at is not None
        assert run.completed_at is None
        assert run.artifact_sha256 is None
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# 2. TrainingRun links to explicit ScientificDataset snapshots.
# ---------------------------------------------------------------------------


def test_training_run_links_to_scientific_dataset_snapshots():
    from suitability_training_run_repository import (
        ROLE_ENVIRONMENTAL_INPUT,
        ROLE_TRAINING_OCCURRENCES,
        link_training_run_dataset,
        create_training_run,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(
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
        db.commit()
        roles = sorted(
            link.role
            for link in run.dataset_links
        )
        assert roles == [ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES]
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 3. Dataset roles are preserved.
# ----------------------------------------------------------------------


def test_dataset_roles_are_preserved():
    from suitability_training_run_repository import (
        ROLE_ENVIRONMENTAL_INPUT,
        ROLE_TRAINING_OCCURRENCES,
        create_training_run,
        link_training_run_dataset,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(
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
        db.commit()
        role_by_dataset = {
            link.scientific_dataset_id: link.role
            for link in run.dataset_links
        }
        assert role_by_dataset[occ_id] == ROLE_TRAINING_OCCURRENCES
        assert role_by_dataset[env_id] == ROLE_ENVIRONMENTAL_INPUT
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 4. Configuration snapshot contains no hidden Jamaica defaults.
# ----------------------------------------------------------------------


def test_configuration_snapshot_has_no_hidden_jamaica_defaults():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_minimal_spec(
        species="Lutjanus analis",
        species_program_id=999,
        region_id=99,
        jurisdiction_id=99,
        occurrence_dataset_id=9990,
        environmental_dataset_ids=(9991,),
        model_version="hypothetical-suitability-v1",
        feature_version="hypothetical-environment-v1",
        generation_version="hypothetical-grid-v1",
    )
    snapshot = build_configuration_snapshot(spec)
    assert snapshot["species"] == "Lutjanus analis"
    assert snapshot["model_version"] == "hypothetical-suitability-v1"
    assert snapshot["feature_version"] == "hypothetical-environment-v1"
    assert snapshot["generation_version"] == "hypothetical-grid-v1"
    assert snapshot["species_program_id"] == 999
    assert snapshot["occurrence_dataset_id"] == 9990
    assert snapshot["environmental_dataset_ids"] == [9991]
    assert "jamaica" not in json.dumps(snapshot).lower()
    assert "pterois" not in json.dumps(snapshot).lower()
    assert "pterois-volitans-suitability-v3" not in json.dumps(snapshot)


# ----------------------------------------------------------------------
# 5. Configuration snapshot is JSON serializable.
# ----------------------------------------------------------------------


def test_configuration_snapshot_is_json_serializable():
    from suitability_training_run_repository import build_configuration_snapshot
    spec = _make_minimal_spec()
    snapshot = build_configuration_snapshot(spec)
    encoded = json.dumps(snapshot)
    decoded = json.loads(encoded)
    assert decoded == snapshot


# ----------------------------------------------------------------------
# 6. BUILDING -> COMPLETED works.
# ----------------------------------------------------------------------


def test_building_to_completed_works():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_COMPLETED,
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            tmp.write(b"x")
            artifact_path = tmp.name
        try:
            record_training_completion(
                db, run, result, artifact_path=artifact_path, skip_validation=True,
            )
            db.commit()
            assert run.status == STATUS_COMPLETED
            assert run.completed_at is not None
            assert run.selected_candidate == "model_x"
            assert run.artifact_path == artifact_path
            assert run.artifact_sha256 is not None
            assert run.training_sample_count == 10
            assert run.presence_count == 5
            assert run.background_count == 5
            assert run.validation_metrics_json is not None
        finally:
            os.unlink(artifact_path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 7. BUILDING -> FAILED works.
# ----------------------------------------------------------------------


def test_building_to_failed_works():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_FAILED,
        create_training_run, record_training_failure,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        record_training_failure(
            db, run, "test failure", warnings=["warning A", "warning B"],
        )
        db.commit()
        assert run.status == STATUS_FAILED
        assert run.completed_at is not None
        assert run.failure_reason == "test failure"
        assert run.warnings_json is not None
        parsed_warnings = json.loads(run.warnings_json)
        assert parsed_warnings == ["warning A", "warning B"]
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 8. COMPLETED scientific provenance cannot be silently changed.
# ----------------------------------------------------------------------


def test_completed_immutable_guard():
    from suitability_training_run_repository import (
        STATUS_BUILDING, STATUS_COMPLETED, STATUS_FAILED,
        assert_completed_immutable,
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        # BUILDING -> editable
        assert_completed_immutable(run, "configuration_json")  # no-op
        result = _make_minimal_result(spec)
        record_training_completion(db, run, result, skip_validation=True)
        db.commit()
        assert run.status == STATUS_COMPLETED
        # COMPLETED -> must raise
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "configuration_json")
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "artifact_sha256")
        with pytest.raises(ValueError):
            assert_completed_immutable(run, "selected_candidate")
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 9. Failed run retains diagnostic context.
# ----------------------------------------------------------------------


def test_failed_run_retains_diagnostic_context():
    from suitability_training_run_repository import (
        STATUS_FAILED, create_training_run, record_training_failure,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        record_training_failure(
            db, run,
            "ValueError: sample size insufficient",
            warnings=["first warning"],
        )
        db.commit()
        assert run.status == STATUS_FAILED
        assert "ValueError: sample size insufficient" in run.failure_reason
        warnings = json.loads(run.warnings_json)
        assert "first warning" in warnings
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 10. Artifact SHA is persisted for completed run.
# ----------------------------------------------------------------------


def test_artifact_sha_persisted():
    from suitability_training_run_repository import (
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            content = b"abc-test-bytes"
            tmp.write(content)
            artifact_path = tmp.name
        try:
            record_training_completion(
                db, run, result, artifact_path=artifact_path, skip_validation=True,
            )
            db.commit()
            expected_sha = hashlib.sha256(content).hexdigest()
            assert run.artifact_sha256 == expected_sha
        finally:
            os.unlink(artifact_path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 11. Selected candidate is persisted.
# ----------------------------------------------------------------------


def test_selected_candidate_persisted():
    from suitability_training_run_repository import (
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        record_training_completion(db, run, result, skip_validation=True)
        db.commit()
        assert run.selected_candidate == "model_x"
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 12. Validation metrics are persisted.
# ----------------------------------------------------------------------


def test_validation_metrics_persisted():
    from suitability_training_run_repository import (
        create_training_run, record_training_completion,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, _, _, _ = _seed_minimal_provenance_db(SessionLocal)
    spec = _make_minimal_spec(species_program_id=program_id)
    db = SessionLocal()
    try:
        run = create_training_run(db, spec)
        result = _make_minimal_result(spec)
        record_training_completion(db, run, result, skip_validation=True)
        db.commit()
        assert run.validation_metrics_json is not None
        parsed = json.loads(run.validation_metrics_json)
        assert parsed["aggregate"]["roc_auc"]["mean"] == 0.7
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 13. Explicit persistence boundary: train() alone does not write a TrainingRun.
# ----------------------------------------------------------------------


def test_train_does_not_write_training_run():
    """The Phase 10D-3 training engine must remain side-effect free
    with respect to TrainingRun. The training function must NOT
    import or invoke the repository."""
    import inspect
    import suitability_training_engine as eng
    src = inspect.getsource(eng.train)
    for token in (
        "training_run",
        "TrainingRun",
        "suitability_training_run_repository",
    ):
        assert token not in src, (
            f"Training engine must not reference {token!r}"
        )


# ----------------------------------------------------------------------
# 14. SuitabilityDeployment does not auto-activate.
# ----------------------------------------------------------------------


def test_suitability_deployment_does_not_auto_activate():
    """The repository and migration MUST NOT activate any deployment."""
    import inspect
    import suitability_training_run_repository as repo
    src = inspect.getsource(repo)
    for token in (
        "status = 'ACTIVE'",
        "suitability_deployments.status = 'ACTIVE'",
        "UPDATE suitability_deployments SET status",
    ):
        assert token not in src


# ----------------------------------------------------------------------
# 15. Existing Jamaica deployment remains valid.
# ----------------------------------------------------------------------


def test_existing_jamaica_deployment_remains_valid():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        dep = conn.execute(
            "SELECT id, species_program_id, status, training_run_id "
            "FROM suitability_deployments "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()
        assert dep is not None
        assert dep[2] == "ACTIVE"
        # training_run_id may be NULL or set by the backfill; either
        # is acceptable. If set, it MUST reference an existing row.
        if dep[3] is not None:
            run = conn.execute(
                "SELECT id, provenance_origin FROM training_runs WHERE id = ?",
                (dep[3],),
            ).fetchone()
            assert run is not None
            assert run[1] == "LEGACY_RECONSTRUCTED"
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 16. Bahamas remains without scientific deployment.
# ----------------------------------------------------------------------


def test_bahamas_remains_without_scientific_deployment():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        deployments = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert deployments == 0
        sp_count = conn.execute(
            "SELECT COUNT(*) FROM species_programs WHERE jurisdiction_id = 2"
        ).fetchone()[0]
        assert sp_count == 0
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 17. Migration is idempotent.
# ----------------------------------------------------------------------


def test_migration_is_idempotent():
    from phase10e2_migrate_training_run import run_migration
    # Use the production DB. The migration is idempotent so a
    # second run is a no-op.
    conn = sqlite3.connect(_db_path())
    try:
        first = run_migration(conn)
        second = run_migration(conn)
        assert first["training_runs_created"] is False
        assert first["training_run_datasets_created"] is False
        assert first["deployment_training_run_id_added"] is False
        assert second["training_runs_created"] is False
        assert second["training_run_datasets_created"] is False
        assert second["deployment_training_run_id_added"] is False
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 18-22. Production scientific integrity invariants.
# ----------------------------------------------------------------------


def test_existing_observations_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0] == 12
    finally:
        conn.close()


def test_existing_historical_occurrences_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_occurrences"
        ).fetchone()[0] == 54
    finally:
        conn.close()


def test_existing_suitability_cells_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0] == 391
    finally:
        conn.close()


def test_existing_monitoring_priority_state_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        active_gen = conn.execute(
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
        ).fetchall()
        assert active_gen == [(2,)]
        cells = conn.execute(
            "SELECT COUNT(*) FROM next_area_snapshot_cells "
            "WHERE generation_id IN ("
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
            ")"
        ).fetchone()[0]
        assert cells == 390
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
# Additional: legacy backfill produced a LEGACY_RECONSTRUCTED row.
# ----------------------------------------------------------------------


def test_legacy_backfill_was_run():
    """If the legacy backfill has been run, there is exactly one
    TrainingRun with provenance_origin=LEGACY_RECONSTRUCTED and
    model_version='pterois-volitans-suitability-v3'. If not run,
    the test is skipped."""
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM training_runs "
            "WHERE provenance_origin = 'LEGACY_RECONSTRUCTED' "
            "AND model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0]
        if rows == 0:
            pytest.skip("Legacy backfill has not been run on this DB")
        assert rows == 1
        # And the deployment must reference the run.
        dep = conn.execute(
            "SELECT training_run_id FROM suitability_deployments "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()
        assert dep[0] is not None
    finally:
        conn.close()