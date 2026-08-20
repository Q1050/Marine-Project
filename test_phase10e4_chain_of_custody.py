"""Phase 10E-4 focused tests: dataset + artifact chain of custody.

Run only:
    pytest test_phase10e4_chain_of_custody.py -v
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
# Helpers.
# ---------------------------------------------------------------------------


def _db_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def _require_production():
    if not os.path.exists(_db_path()):
        pytest.skip("Production DB not present")


def _make_minimal_provenance_db():
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


def _seed_minimal(SessionLocal, *, env_artifact_sha=None, occ_artifact_sha=None):
    """Seed a minimal dataset + TrainingRun + Deployment setup."""
    import models
    db = SessionLocal()
    try:
        region = models.Region(name="r", slug="r", status="ACTIVE")
        db.add(region); db.flush()
        jur = models.Jurisdiction(
            region_id=region.id, name="j", slug="j", country_code="JM",
            center_latitude=0.0, center_longitude=0.0, default_zoom=5.0,
        )
        db.add(jur); db.flush()
        species = models.Species(scientific_name="Hyp sp.", aphia_id=999)
        db.add(species); db.flush()
        program = models.SpeciesProgram(
            jurisdiction_id=jur.id, scientific_name="Hyp sp.",
            status="ACTIVE", species_id=species.id,
        )
        db.add(program); db.flush()
        occ = models.ScientificDataset(
            slug="hyp-occ", name="Hyp occ", dataset_type="OCCURRENCE",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="JURISDICTION",
            region_id=region.id, jurisdiction_id=jur.id,
            source_name="TEST", source_type="TEST",
            source_version="v1", record_count=2,
            artifact_sha256=occ_artifact_sha,
        )
        db.add(occ); db.flush()
        env = models.ScientificDataset(
            slug="hyp-env", name="Hyp env", dataset_type="ENVIRONMENTAL",
            status="ACTIVE", species_id=species.id,
            species_program_id=program.id,
            geographic_scope_type="REGION", region_id=region.id,
            jurisdiction_id=None, source_name="TEST", source_type="TEST",
            source_version="v1", record_count=2,
            artifact_sha256=env_artifact_sha,
        )
        db.add(env); db.flush()
        db.commit()
        return program.id, occ.id, env.id
    finally:
        db.close()


# ----------------------------------------------------------------------
# 1. Dataset artifact registration computes SHA-256.
# ----------------------------------------------------------------------


def test_dataset_artifact_registration_computes_sha256():
    from suitability_dataset_artifact_repository import register_dataset_artifact
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        import models
        occ = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == occ_id
        ).one()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            content = b"col1,col2\n1,2\n3,4\n"
            tmp.write(content)
            path = tmp.name
        try:
            result = register_dataset_artifact(
                db, occ, path, artifact_format="csv",
                expected_record_count=2,
            )
            assert result["artifact_sha256_set"] is True
            expected_sha = hashlib.sha256(content).hexdigest()
            assert occ.artifact_sha256 == expected_sha
            assert occ.artifact_path == path
            # Format was set via acquisition_manifest_json.
            manifest = json.loads(occ.acquisition_manifest_json)
            assert manifest["artifact_format"] == "csv"
        finally:
            os.unlink(path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 2. Missing file is rejected.
# ----------------------------------------------------------------------


def test_missing_file_is_rejected():
    from suitability_dataset_artifact_repository import register_dataset_artifact
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        import models
        occ = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == occ_id
        ).one()
        with pytest.raises(FileNotFoundError):
            register_dataset_artifact(
                db, occ, "/nonexistent/path/file.csv",
            )
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 3. Stored SHA matches actual bytes.
# ----------------------------------------------------------------------


def test_stored_sha_matches_actual_bytes():
    from suitability_dataset_artifact_repository import (
        register_dataset_artifact, verify_dataset_artifact,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        import models
        occ = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == occ_id
        ).one()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            content = b"stable-content"
            tmp.write(content)
            path = tmp.name
        try:
            register_dataset_artifact(db, occ, path)
            assert verify_dataset_artifact(occ)["verified"] is True
            assert verify_dataset_artifact(occ)["status"] == "COMPLETE"
        finally:
            os.unlink(path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 4. Dataset artifact cannot silently change after a COMPLETED native run.
# ----------------------------------------------------------------------


def test_dataset_artifact_cannot_silently_change_after_completed_run():
    from suitability_dataset_artifact_repository import (
        ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES,
        create_completed_native_run_for_test,
        register_dataset_artifact,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        # Create a controlled artifact for both datasets; pass the
        # SHA so the run can transition to COMPLETE with input
        # integrity status COMPLETE.
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as t1:
            occ_bytes = b"original-content"
            t1.write(occ_bytes)
            occ_path = t1.name
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as t2:
            env_bytes = b"original-env-content"
            t2.write(env_bytes)
            env_path = t2.name
        try:
            occ_sha = hashlib.sha256(occ_bytes).hexdigest()
            env_sha = hashlib.sha256(env_bytes).hexdigest()
            # Build a controlled model artifact.
            with tempfile.NamedTemporaryFile(
                suffix=".joblib", delete=False,
            ) as mt:
                model_bytes = b"native-model"
                mt.write(model_bytes)
                model_path = mt.name
            try:
                model_sha = hashlib.sha256(model_bytes).hexdigest()
                create_completed_native_run_for_test(
                    db, program_id=program_id,
                    occ_id=occ_id, env_id=env_id,
                    occ_artifact_sha=occ_sha,
                    occ_artifact_path=occ_path,
                    env_artifact_sha=env_sha,
                    env_artifact_path=env_path,
                    model_artifact_path=model_path,
                    model_artifact_sha=model_sha,
                )
            finally:
                os.unlink(model_path)
            # Now attempt to replace the occurrence dataset artifact
            # with different bytes. This MUST be refused.
            import models
            occ = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == occ_id
            ).one()
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False,
            ) as t3:
                t3.write(b"tampered-content")
                tampered_path = t3.name
            try:
                with pytest.raises(ValueError):
                    register_dataset_artifact(db, occ, tampered_path)
            finally:
                os.unlink(tampered_path)
        finally:
            os.unlink(occ_path)
            os.unlink(env_path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 5. Record count inconsistency is rejected where verifiable.
# ----------------------------------------------------------------------


def test_record_count_inconsistency_is_rejected():
    from suitability_dataset_artifact_repository import register_dataset_artifact
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        import models
        occ = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == occ_id
        ).one()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(b"x")
            path = tmp.name
        try:
            # record_count is 2; ask for 9999.
            with pytest.raises(ValueError):
                register_dataset_artifact(
                    db, occ, path, expected_record_count=9999,
                )
        finally:
            os.unlink(path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 6. Training input canonicalization is deterministic.
# ----------------------------------------------------------------------


def test_training_input_canonicalization_is_deterministic():
    from suitability_dataset_artifact_repository import compute_training_input_sha256
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha",
        occ_artifact_sha="occ_sha",
    )
    db = SessionLocal()
    try:
        import models
        # Create a run + dataset links in the same order both times.
        from suitability_training_run_repository import (
            ORIGIN_NATIVE, create_training_run,
        )
        from suitability_training_spec import (
            SuitabilityGrid, SuitabilityTrainingSpec,
        )
        grid = SuitabilityGrid(
            grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
            name="g",
        )
        spec = SuitabilityTrainingSpec(
            species="Hyp sp.", species_program_id=program_id,
            geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
            occurrence_dataset_id=occ_id,
            environmental_dataset_ids=(env_id,),
            grid=grid,
            model_version="hyp-v1",
            feature_version="hyp-env-v1",
            generation_version="hyp-gen-v1",
            background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

        run = create_training_run(db, spec)
        from suitability_training_run_repository import link_training_run_dataset
        from suitability_dataset_artifact_repository import (
            ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
        )
        occ = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == occ_id
        ).one()
        env = db.query(models.ScientificDataset).filter(
            models.ScientificDataset.id == env_id
        ).one()
        link_training_run_dataset(db, run, occ, ROLE_TRAINING_OCCURRENCES)
        link_training_run_dataset(db, run, env, ROLE_ENVIRONMENTAL_INPUT)
        sha1, status1 = compute_training_input_sha256(db, run)
        # Re-create the run and links in the same order: hash must match.
        sha2, status2 = compute_training_input_sha256(db, run)
        assert sha1 == sha2
        assert status1 == status2 == "COMPLETE"
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 7. Identical inputs produce identical training_input_sha256.
# ----------------------------------------------------------------------


def test_identical_inputs_produce_identical_training_input_sha256():
    from suitability_dataset_artifact_repository import compute_training_input_sha256
    from suitability_training_run_repository import (
        create_training_run, link_training_run_dataset,
    )
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    from suitability_dataset_artifact_repository import (
        ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    # First run.
    db = SessionLocal()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha", occ_artifact_sha="occ_sha",
    )
    grid = SuitabilityGrid(
        grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
        name="g",
    )
    spec_a = SuitabilityTrainingSpec(
        species="Hyp sp.", species_program_id=program_id,
        geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
        grid=grid, model_version="hyp-v1",
        feature_version="hyp-env-v1",
        generation_version="hyp-gen-v1",
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    run_a = create_training_run(db, spec_a)
    occ = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == occ_id
    ).one()
    env = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == env_id
    ).one()
    link_training_run_dataset(db, run_a, occ, ROLE_TRAINING_OCCURRENCES)
    link_training_run_dataset(db, run_a, env, ROLE_ENVIRONMENTAL_INPUT)
    sha_a, status_a = compute_training_input_sha256(db, run_a)
    db.close()

    # Second run with identical dataset links.
    db = SessionLocal()
    spec_b = SuitabilityTrainingSpec(
        species="Hyp sp.", species_program_id=program_id,
        geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
        grid=grid, model_version="hyp-v1",
        feature_version="hyp-env-v1",
        generation_version="hyp-gen-v1",
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    run_b = create_training_run(db, spec_b)
    occ = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == occ_id
    ).one()
    env = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == env_id
    ).one()
    link_training_run_dataset(db, run_b, occ, ROLE_TRAINING_OCCURRENCES)
    link_training_run_dataset(db, run_b, env, ROLE_ENVIRONMENTAL_INPUT)
    sha_b, status_b = compute_training_input_sha256(db, run_b)
    db.close()
    engine.dispose()
    assert sha_a == sha_b
    assert status_a == status_b == "COMPLETE"


# ----------------------------------------------------------------------
# 8. Dataset hash change changes training_input_sha256.
# ----------------------------------------------------------------------


def test_dataset_hash_change_changes_training_input_sha256():
    from suitability_dataset_artifact_repository import compute_training_input_sha256
    from suitability_training_run_repository import (
        create_training_run, link_training_run_dataset,
    )
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    from suitability_dataset_artifact_repository import (
        ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    db = SessionLocal()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha_a",
        occ_artifact_sha="occ_sha_a",
    )
    grid = SuitabilityGrid(
        grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
        name="g",
    )
    spec = SuitabilityTrainingSpec(
        species="Hyp sp.", species_program_id=program_id,
        geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
        grid=grid, model_version="hyp-v1",
        feature_version="hyp-env-v1",
        generation_version="hyp-gen-v1",
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    run_a = create_training_run(db, spec)
    occ = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == occ_id
    ).one()
    env = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == env_id
    ).one()
    link_training_run_dataset(db, run_a, occ, ROLE_TRAINING_OCCURRENCES)
    link_training_run_dataset(db, run_a, env, ROLE_ENVIRONMENTAL_INPUT)
    sha_a, _ = compute_training_input_sha256(db, run_a)

    # Change occurrence dataset artifact SHA.
    occ.artifact_sha256 = "occ_sha_b"
    db.flush()
    sha_b, _ = compute_training_input_sha256(db, run_a)
    db.close()
    engine.dispose()
    assert sha_a != sha_b


# ----------------------------------------------------------------------
# 9. Dataset role changes change training_input_sha256.
# ----------------------------------------------------------------------


def test_dataset_role_change_changes_training_input_sha256():
    from suitability_dataset_artifact_repository import compute_training_input_sha256
    from suitability_training_run_repository import (
        create_training_run, link_training_run_dataset,
    )
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    from suitability_dataset_artifact_repository import (
        ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
        ROLE_VALIDATION_INPUT,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    db = SessionLocal()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha",
        occ_artifact_sha="occ_sha",
    )
    grid = SuitabilityGrid(
        grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
        name="g",
    )
    spec = SuitabilityTrainingSpec(
        species="Hyp sp.", species_program_id=program_id,
        geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
        grid=grid, model_version="hyp-v1",
        feature_version="hyp-env-v1",
        generation_version="hyp-gen-v1",
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    run_a = create_training_run(db, spec)
    occ = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == occ_id
    ).one()
    env = db.query(__import__("models").ScientificDataset).filter(
        __import__("models").ScientificDataset.id == env_id
    ).one()
    link_training_run_dataset(db, run_a, occ, ROLE_TRAINING_OCCURRENCES)
    link_training_run_dataset(db, run_a, env, ROLE_ENVIRONMENTAL_INPUT)
    sha_a, _ = compute_training_input_sha256(db, run_a)

    # Re-link the occurrence dataset to a different role.
    link = db.query(__import__("models").TrainingRunDataset).filter(
        __import__("models").TrainingRunDataset.training_run_id == run_a.id,
        __import__("models").TrainingRunDataset.scientific_dataset_id == occ_id,
    ).one()
    link.role = ROLE_VALIDATION_INPUT
    db.flush()
    sha_b, _ = compute_training_input_sha256(db, run_a)
    db.close()
    engine.dispose()
    assert sha_a != sha_b


# ----------------------------------------------------------------------
# 10. Completed native TrainingRun validates dataset artifact hashes.
# ----------------------------------------------------------------------


def test_completed_native_run_validates_dataset_hashes():
    """A native completion with PARTIAL integrity must fail."""
    from suitability_dataset_artifact_repository import (
        create_completed_native_run_for_test,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(SessionLocal)
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            create_completed_native_run_for_test(
                db, program_id=program_id,
                occ_id=occ_id, env_id=env_id,
                occ_artifact_sha=None,
                env_artifact_sha=None,
            )
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 11. TrainingRun artifact SHA validates against actual model artifact.
# ----------------------------------------------------------------------


def test_training_run_artifact_sha_validates_against_actual_file():
    from suitability_dataset_artifact_repository import verify_model_artifact_chain
    from suitability_training_run_repository import (
        create_training_run, link_training_run_dataset,
    )
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    from suitability_dataset_artifact_repository import (
        ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha", occ_artifact_sha="occ_sha",
    )
    db = SessionLocal()
    try:
        import models
        grid = SuitabilityGrid(
            grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
            name="g",
        )
        spec = SuitabilityTrainingSpec(
            species="Hyp sp.", species_program_id=program_id,
            geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
            occurrence_dataset_id=occ_id,
            environmental_dataset_ids=(env_id,),
            grid=grid, model_version="hyp-v1",
            feature_version="hyp-env-v1",
            generation_version="hyp-gen-v1",
            background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

        run = create_training_run(db, spec)
        # Make a controlled model artifact.
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            content = b"model-bytes"
            tmp.write(content)
            model_path = tmp.name
        try:
            run.artifact_path = model_path
            run.artifact_sha256 = hashlib.sha256(content).hexdigest()
            db.flush()
            # Add dataset links (required for integrity).
            occ = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == occ_id
            ).one()
            env = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == env_id
            ).one()
            link_training_run_dataset(db, run, occ, ROLE_TRAINING_OCCURRENCES)
            link_training_run_dataset(db, run, env, ROLE_ENVIRONMENTAL_INPUT)
            # Verification must succeed with COMPLETE status.
            result = verify_model_artifact_chain(db, run)
            assert result["status"] == "COMPLETE"
            assert result["matches_run_sha"] is True
        finally:
            os.unlink(model_path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 12. Deployment artifact hash mismatch is detected.
# ----------------------------------------------------------------------


def test_deployment_artifact_hash_mismatch_detected():
    from suitability_dataset_artifact_repository import verify_model_artifact_chain
    from suitability_training_run_repository import (
        create_training_run, link_training_run_dataset,
    )
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    from suitability_dataset_artifact_repository import (
        ROLE_TRAINING_OCCURRENCES, ROLE_ENVIRONMENTAL_INPUT,
    )
    engine, SessionLocal = _make_minimal_provenance_db()
    db = SessionLocal()
    program_id, occ_id, env_id = _seed_minimal(
        SessionLocal, env_artifact_sha="env_sha", occ_artifact_sha="occ_sha",
    )
    try:
        import models
        # Create a HabitatSuitabilityModel so the deployment FK resolves.
        habitat_model = models.HabitatSuitabilityModel(
            model_version="hyp-v1", scientific_name="Hyp sp.",
            algorithm="LogisticRegression", feature_list_json="[]",
            training_generation_version="hyp-gen-v1",
            training_sample_count=10, eligible_presence_count=5,
            eligible_background_count=5, spatial_block_count=1,
            validation_metrics_json="{}", coefficients_json="{}",
            artifact_path="/tmp/none.joblib",
        )
        db.add(habitat_model); db.flush()
        grid = SuitabilityGrid(
            grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
            name="g",
        )
        spec = SuitabilityTrainingSpec(
            species="Hyp sp.", species_program_id=program_id,
            geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
            occurrence_dataset_id=occ_id,
            environmental_dataset_ids=(env_id,),
            grid=grid, model_version="hyp-v1",
            feature_version="hyp-env-v1",
            generation_version="hyp-gen-v1",
            background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

        run = create_training_run(db, spec)
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            tmp.write(b"model")
            model_path = tmp.name
        try:
            run.artifact_path = model_path
            run.artifact_sha256 = hashlib.sha256(b"model").hexdigest()
            db.flush()
            occ = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == occ_id
            ).one()
            env = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == env_id
            ).one()
            link_training_run_dataset(db, run, occ, ROLE_TRAINING_OCCURRENCES)
            link_training_run_dataset(db, run, env, ROLE_ENVIRONMENTAL_INPUT)
            # Build a fake deployment with a mismatched artifact_hash.
            dep = models.SuitabilityDeployment(
                species_program_id=program_id,
                habitat_suitability_model_id=habitat_model.id,
                model_version="hyp-v1", status="ACTIVE",
                artifact_hash="0" * 64,
            )
            db.add(dep)
            db.flush()
            result = verify_model_artifact_chain(db, run, deployment=dep)
            assert result["matches_deployment"] is False
            assert result["status"] == "MISMATCH"
        finally:
            os.unlink(model_path)
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# 13. No deployment is activated.
# ----------------------------------------------------------------------


def test_no_deployment_activation():
    import inspect
    import suitability_dataset_artifact_repository as r
    src = inspect.getsource(r)
    forbidden = (
        "status = 'ACTIVE'",
        "UPDATE suitability_deployments SET status",
        "INSERT INTO suitability_deployments",
    )
    for token in forbidden:
        assert token not in src


# ----------------------------------------------------------------------
# 14. Legacy Jamaica remains LEGACY_RECONSTRUCTED.
# ----------------------------------------------------------------------


def test_legacy_jamaica_remains_legacy_reconstructed():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            "SELECT provenance_origin, training_input_sha256, "
            "input_integrity_status FROM training_runs WHERE id = 1"
        ).fetchone()
        assert row[0] == "LEGACY_RECONSTRUCTED"
        assert row[1] is not None
        assert row[2] == "PARTIAL"
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 15. Legacy input-integrity state is honest when dataset artifacts are unavailable.
# ----------------------------------------------------------------------


def test_legacy_input_integrity_state_is_honest():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Both production datasets have NULL artifact_sha256.
        for ds_id in (1, 2):
            row = conn.execute(
                "SELECT artifact_path, artifact_sha256 FROM "
                "scientific_datasets WHERE id = ?",
                (ds_id,),
            ).fetchone()
            assert row[0] is None and row[1] is None, (
                f"dataset {ds_id} unexpectedly has an artifact"
            )
        # The legacy TrainingRun must be PARTIAL.
        run = conn.execute(
            "SELECT input_integrity_status FROM training_runs WHERE id = 1"
        ).fetchone()
        assert run[0] == "PARTIAL"
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 16. Existing v3 model artifact SHA remains unchanged.
# ----------------------------------------------------------------------


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
# 17-21. Production state invariants.
# ----------------------------------------------------------------------


def test_existing_occurrences_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_occurrences"
        ).fetchone()[0] == 54
    finally:
        conn.close()


def test_existing_environmental_values_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features"
        ).fetchone()[0] == 25674
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


def test_monitoring_priority_state_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        active_gens = conn.execute(
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
        ).fetchall()
        assert active_gens == [(2,)]
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


def test_bahamas_remains_without_deployment():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        deployments = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert deployments == 0
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 22. Migration is idempotent.
# ----------------------------------------------------------------------


def test_migration_is_idempotent():
    from phase10e4_migrate_chain_of_custody import run_migration
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        first = run_migration(conn)
        second = run_migration(conn)
        assert first["training_input_sha256_added"] is False
        assert first["input_integrity_status_added"] is False
        assert second["training_input_sha256_added"] is False
        assert second["input_integrity_status_added"] is False
    finally:
        conn.close()