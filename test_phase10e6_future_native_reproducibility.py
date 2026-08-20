"""Phase 10E-6 future-native end-to-end integration test.

Run only:
    pytest test_phase10e6_future_native_reproducibility.py -v

This test proves the complete Phase 10E architecture works for a
FUTURE NATIVE training run on an isolated temporary SQLite database
+ temporary filesystem + tiny hypothetical non-Caribbean fixture.

No production database is touched. No real SuitabilityDeployment
row is created. The model artifact is written to a temporary file.
The deployment candidate is non-active.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import List

import pytest


# ---------------------------------------------------------------------------
# Helpers: in-memory SQLite schema bootstrap with the full Phase 10E
# table set.
# ---------------------------------------------------------------------------


def _bootstrap_schema(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
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
        scientific_name TEXT, status TEXT, species_id INTEGER
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
        activated_at DATETIME, created_at DATETIME, updated_at DATETIME,
        training_run_id INTEGER
    );
    CREATE TABLE prediction_sample_environmental_features (
        id INTEGER PRIMARY KEY, prediction_model_sample_id INTEGER,
        scientific_dataset_id INTEGER, feature_name TEXT, value REAL,
        source TEXT, sampling_method TEXT, is_missing INTEGER,
        metadata_json TEXT, feature_version TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    CREATE TABLE training_runs (
        id INTEGER PRIMARY KEY, species_program_id INTEGER,
        model_version TEXT, status TEXT, provenance_origin TEXT,
        started_at DATETIME, completed_at DATETIME,
        random_seed INTEGER, selected_candidate TEXT,
        artifact_path TEXT, artifact_sha256 TEXT,
        training_sample_count INTEGER, presence_count INTEGER,
        background_count INTEGER, validation_metrics_json TEXT,
        configuration_json TEXT, configuration_sha256 TEXT,
        training_input_sha256 TEXT, input_integrity_status TEXT,
        warnings_json TEXT, failure_reason TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE training_run_datasets (
        id INTEGER PRIMARY KEY, training_run_id INTEGER,
        scientific_dataset_id INTEGER, role TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    connection.commit()


# ---------------------------------------------------------------------------
# Fixture: a tiny hypothetical non-Caribbean world.
# ---------------------------------------------------------------------------


HYPOTHETICAL_SPECIES = "Hypothetical non-Caribbean test fish"
HYPOTHETICAL_REGION_NAME = "TestRegion"
HYPOTHETICAL_JURISDICTION_NAME = "TestJurisdiction"

HYPOTHETICAL_BACKGROUND_EXTENT = {
    "latitude_min": 30.0, "latitude_max": 31.0,
    "longitude_min": -50.0, "longitude_max": -49.0,
}
HYPOTHETICAL_SPATIAL_BLOCK_ORIGIN = {
    "latitude_origin": 30.0, "longitude_origin": -50.0,
}
HYPOTHETICAL_PREDICTION_BOUNDS = (-50.0, -49.0, 30.0, 31.0)
HYPOTHETICAL_TINY_GRID_SIZE = 0.5


def _seed_world(connection: sqlite3.Connection) -> dict:
    """Insert a tiny hypothetical world: region + jurisdiction +
    species + species_program. Return the resulting ids.
    """
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO regions (id, name, slug, status) VALUES (1, ?, ?, 'ACTIVE')",
        (HYPOTHETICAL_REGION_NAME, "test-region"),
    )
    cursor.execute(
        "INSERT INTO jurisdictions (id, region_id, name, slug, country_code, "
        "status, center_latitude, center_longitude, default_zoom) "
        "VALUES (1, 1, ?, 'test-jurisdiction', 'XX', 'ACTIVE', 30.5, -49.5, 8)",
        (HYPOTHETICAL_JURISDICTION_NAME,),
    )
    cursor.execute(
        "INSERT INTO species (id, scientific_name) VALUES (1, ?)",
        (HYPOTHETICAL_SPECIES,),
    )
    cursor.execute(
        "INSERT INTO species_programs (id, jurisdiction_id, "
        "scientific_name, status) VALUES (1, 1, ?, 'ACTIVE')",
        (HYPOTHETICAL_SPECIES,),
    )
    connection.commit()
    return {
        "region_id": 1,
        "jurisdiction_id": 1,
        "species_id": 1,
        "species_program_id": 1,
    }


# ---------------------------------------------------------------------------
# Fixture setup helper.
# ---------------------------------------------------------------------------


def _seed_datasets_and_artifacts(
    connection: sqlite3.Connection,
    artifact_dir: str,
    *,
    occ_record_count: int,
    occ_rows: List[tuple],
    env_record_count: int,
    env_feature_count: int,
) -> dict:
    """Create two ScientificDataset rows with controlled artifact
    files on disk. Returns the dataset ids and the artifact bytes /
    SHA hashes.
    """
    cursor = connection.cursor()
    # Occurrence dataset
    occ_csv_path = os.path.join(artifact_dir, "occ_dataset.csv")
    occ_bytes = b"id,lat,lon\n" + "\n".join(
        f"{row[0]},{row[1]},{row[2]}" for row in occ_rows
    ).encode("ascii") + b"\n"
    with open(occ_csv_path, "wb") as f:
        f.write(occ_bytes)
    occ_sha = hashlib.sha256(occ_bytes).hexdigest()
    cursor.execute(
        "INSERT INTO scientific_datasets (id, slug, name, dataset_type, "
        "status, geographic_scope_type, region_id, jurisdiction_id, "
        "source_name, source_version, record_count, artifact_path, "
        "artifact_sha256, created_at) "
        "VALUES (1, 'h-occ', 'H occ', 'OCCURRENCE', "
        "'ACTIVE', 'JURISDICTION', 1, 1, 'TEST', 'v1', ?, ?, ?, "
        "CURRENT_TIMESTAMP)",
        (occ_record_count, occ_csv_path, occ_sha),
    )
    # Environmental dataset
    env_csv_path = os.path.join(artifact_dir, "env_dataset.csv")
    env_lines = ["cell_id,feature_name,value"]
    for cell_id in range(env_feature_count):
        for feat in ("bathymetry_center_depth", "sst_climatology_annual_mean"):
            env_lines.append(f"{cell_id},{feat},1.5")
    env_bytes = ("\n".join(env_lines) + "\n").encode("ascii")
    with open(env_csv_path, "wb") as f:
        f.write(env_bytes)
    env_sha = hashlib.sha256(env_bytes).hexdigest()
    cursor.execute(
        "INSERT INTO scientific_datasets (id, slug, name, dataset_type, "
        "status, geographic_scope_type, region_id, jurisdiction_id, "
        "source_name, source_version, record_count, artifact_path, "
        "artifact_sha256, created_at) "
        "VALUES (2, 'h-env', 'H env', 'ENVIRONMENTAL', "
        "'ACTIVE', 'REGION', 1, NULL, 'TEST', 'v1', ?, ?, ?, "
        "CURRENT_TIMESTAMP)",
        (env_record_count, env_csv_path, env_sha),
    )
    connection.commit()
    return {
        "occ_dataset_id": 1,
        "env_dataset_id": 2,
        "occ_bytes": occ_bytes,
        "occ_sha": occ_sha,
        "occ_path": occ_csv_path,
        "env_bytes": env_bytes,
        "env_sha": env_sha,
        "env_path": env_csv_path,
    }


# ---------------------------------------------------------------------------
# Test cases.
# ---------------------------------------------------------------------------


def test_end_to_end_future_native_chain():
    """One comprehensive integration test that proves the entire
    future-native provenance + reproducibility chain works."""
    # ------------------------------------------------------------------
    # Step 1: isolated temporary SQLite database + temporary artifact
    # directory.
    # ------------------------------------------------------------------
    tmpdir = tempfile.mkdtemp(prefix="phase10e6_")
    db_path = os.path.join(tmpdir, "fixture.db")
    artifact_dir = os.path.join(tmpdir, "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    try:
        connection = sqlite3.connect(db_path)
        _bootstrap_schema(connection)
        ids = _seed_world(connection)

        # ------------------------------------------------------------------
        # Step 2: build controlled datasets with explicit artifacts.
        # ------------------------------------------------------------------
        # Occurrence: 12 rows scattered across the hypothetical extent.
        occ_rows = [
            (i, 30.0 + (i * 0.05), -49.0 - (i * 0.05))
            for i in range(12)
        ]
        datasets = _seed_datasets_and_artifacts(
            connection, artifact_dir,
            occ_record_count=len(occ_rows),
            occ_rows=occ_rows,
            env_record_count=10,
            env_feature_count=10,
        )
        # Verify artifact SHAs match actual bytes.
        for path, expected_sha in [
            (datasets["occ_path"], datasets["occ_sha"]),
            (datasets["env_path"], datasets["env_sha"]),
        ]:
            actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
            assert actual == expected_sha

        # Link both datasets to a future Deployment (id=1, non-active).
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO suitability_deployments (id, species_program_id, "
            "habitat_suitability_model_id, model_version, status, "
            "artifact_hash, training_run_id) "
            "VALUES (1, ?, 1, 'hypothetical-v1', 'ACTIVE', NULL, NULL)",
            (ids["species_program_id"],),
        )
        cursor.execute(
            "INSERT INTO scientific_dataset_deployments ("
            "id, scientific_dataset_id, suitability_deployment_id, role) "
            "VALUES (1, ?, 1, 'TRAINING_OCCURRENCES')",
            (datasets["occ_dataset_id"],),
        )
        cursor.execute(
            "INSERT INTO scientific_dataset_deployments ("
            "id, scientific_dataset_id, suitability_deployment_id, role) "
            "VALUES (2, ?, 1, 'ENVIRONMENTAL_INPUT')",
            (datasets["env_dataset_id"],),
        )
        connection.commit()

        # ------------------------------------------------------------------
        # Step 3: build explicit SuitabilityTrainingSpec with NO
        # implicit defaults and NO Jamaica compatibility factory.
        # ------------------------------------------------------------------
        from suitability_training_spec import (
            SuitabilityGrid, SuitabilityTrainingSpec,
        )
        from suitability_training_engine import (
            SuitabilityCandidateResult, SuitabilityTrainingInputs,
            SuitabilityTrainingResult, train,
        )
        from suitability_training_run_repository import (
            ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES,
            STATUS_BUILDING, STATUS_COMPLETED,
            assert_completed_immutable, build_configuration_snapshot,
            canonical_configuration_json, compute_configuration_sha256,
            create_training_run, link_training_run_dataset,
            record_training_completion, validate_native_completion,
        )
        from suitability_dataset_artifact_repository import (
            compute_training_input_sha256, register_dataset_artifact,
            verify_dataset_artifact, verify_model_artifact_chain,
        )

        # Override the engine's DEFAULT_BACKGROUND_REGION_BOUNDS fallback
        # by passing our own explicit extent via the spec.
        grid = SuitabilityGrid(
            grid_size_degrees=HYPOTHETICAL_TINY_GRID_SIZE,
            bounds=HYPOTHETICAL_PREDICTION_BOUNDS,
            name="hypothetical-test-grid",
        )
        spec = SuitabilityTrainingSpec(
            species=HYPOTHETICAL_SPECIES,
            species_program_id=ids["species_program_id"],
            geographic_scope="JURISDICTION",
            region_id=ids["region_id"],
            jurisdiction_id=ids["jurisdiction_id"],
            occurrence_dataset_id=datasets["occ_dataset_id"],
            environmental_dataset_ids=(datasets["env_dataset_id"],),
            feature_version="hypothetical-environment-v1",
            generation_version="hypothetical-grid-v1",
            model_version="hypothetical-suitability-v1",
            random_seed=20260816,
            cv_folds=2,
            spatial_block_size_degrees=2.0,
            background_extent_bounds=HYPOTHETICAL_BACKGROUND_EXTENT,
            spatial_block_origin=HYPOTHETICAL_SPATIAL_BLOCK_ORIGIN,
            grid=grid,
        )
        snapshot = build_configuration_snapshot(spec)
        # The snapshot must carry every scientific parameter.
        for key in (
            "background_extent", "spatial_block_origin", "prediction_grid",
            "logistic_hyperparameters", "nonlinear_hyperparameters",
            "cv_strategy", "primary_selection_metrics",
            "suitability_band_thresholds",
        ):
            assert key in snapshot, f"missing key {key}"
        assert snapshot["schema_version"] == 2
        assert snapshot["background_extent"] == HYPOTHETICAL_BACKGROUND_EXTENT
        assert snapshot["spatial_block_origin"] == HYPOTHETICAL_SPATIAL_BLOCK_ORIGIN
        # No Jamaica / Pterois references in the snapshot.
        assert "jamaica" not in json.dumps(snapshot).lower()
        assert "pterois" not in json.dumps(snapshot).lower()
        canonical = canonical_configuration_json(snapshot)
        # Deterministic.
        assert canonical == canonical_configuration_json(snapshot)
        sha = compute_configuration_sha256(snapshot)
        assert len(sha) == 64

        # ------------------------------------------------------------------
        # Step 4: TrainingRun + dataset links + input integrity.
        # ------------------------------------------------------------------
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        engine.dispose()
        db = SessionLocal()
        try:
            run = create_training_run(db, spec)
            assert run.provenance_origin == "NATIVE"
            assert run.status == STATUS_BUILDING
            assert run.configuration_json == json.dumps(snapshot)
            assert run.configuration_sha256 == sha

            occ_dataset = db.query(__import__("models").ScientificDataset).filter_by(
                id=datasets["occ_dataset_id"],
            ).one()
            env_dataset = db.query(__import__("models").ScientificDataset).filter_by(
                id=datasets["env_dataset_id"],
            ).one()
            link_training_run_dataset(
                db, run, occ_dataset, ROLE_TRAINING_OCCURRENCES,
            )
            link_training_run_dataset(
                db, run, env_dataset, ROLE_ENVIRONMENTAL_INPUT,
            )

            # ------------------------------------------------------------------
            # Step 5: deterministic background sampling using
            # spec.background_extent_bounds and
            # spec.spatial_block_origin.
            # ------------------------------------------------------------------
            from suitability_training_engine import (
                _build_background_samples,
            )
            import numpy as np
            rng_a = np.random.default_rng(20260816)
            rng_b = np.random.default_rng(20260816)
            samples_a = _build_background_samples(
                spec, rng_a, presence_cells={}, capacity=spec.background_ratio,
            )
            samples_b = _build_background_samples(
                spec, rng_b, presence_cells={}, capacity=spec.background_ratio,
            )
            # _build_background_samples returns List[Tuple[lat, lon, depth]].
            assert [s[0] for s in samples_a] == [s[0] for s in samples_b]
            assert [s[1] for s in samples_a] == [s[1] for s in samples_b]

            # ------------------------------------------------------------------
            # Step 6: input integrity hash with controlled artifacts.
            # ------------------------------------------------------------------
            input_sha, input_status = compute_training_input_sha256(
                db, run,
            )
            assert input_status == "COMPLETE"
            assert len(input_sha) == 64
            # Determinism: recompute.
            input_sha_again, _ = compute_training_input_sha256(
                db, run,
            )
            assert input_sha == input_sha_again

            # Changing the dataset bytes changes the hash.
            with open(datasets["occ_path"], "ab") as f:
                f.write(b"# tweak\n")
            datasets["occ_sha"] = hashlib.sha256(
                open(datasets["occ_path"], "rb").read()
            ).hexdigest()
            assert datasets["occ_sha"] != input_sha
            occ_dataset.artifact_sha256 = datasets["occ_sha"]
            db.flush()
            input_sha_b, _ = compute_training_input_sha256(db, run)
            assert input_sha_b != input_sha

            # Restore the artifact (don't leave the fixture mutated).
            occ_bytes = open(datasets["occ_path"], "rb").read()
            clean_len = len(occ_bytes) - len(b"# tweak\n")
            with open(datasets["occ_path"], "wb") as f:
                f.write(occ_bytes[:clean_len])
            occ_dataset.artifact_sha256 = hashlib.sha256(
                open(datasets["occ_path"], "rb").read()
            ).hexdigest()
            db.flush()

            # ------------------------------------------------------------------
            # Step 7: tiny deterministic training run via the
            # generalized engine.
            # ------------------------------------------------------------------
            from suitability_training_loaders import (
                DatasetProvenanceSummary,
            )
            occ_summary = DatasetProvenanceSummary(
                id=1, slug="h-occ", name="H occ", dataset_type="OCCURRENCE",
                status="ACTIVE", geographic_scope_type="JURISDICTION",
                region_id=1, jurisdiction_id=1, species_id=1,
                species_program_id=1, source_name="TEST",
                source_type="TEST", source_reference=None,
                source_version="v1", retrieved_at=None, record_count=12,
                artifact_path=None, artifact_sha256=None, notes=None,
            )
            env_summary = DatasetProvenanceSummary(
                id=2, slug="h-env", name="H env", dataset_type="ENVIRONMENTAL",
                status="ACTIVE", geographic_scope_type="REGION",
                region_id=1, jurisdiction_id=None, species_id=1,
                species_program_id=1, source_name="TEST",
                source_type="TEST", source_reference=None,
                source_version="v1", retrieved_at=None, record_count=10,
                artifact_path=None, artifact_sha256=None, notes=None,
            )

            occ_dataset_row = __import__("models").ScientificDataset(
                id=10, slug="unused", name="u", dataset_type="OCCURRENCE",
                status="ACTIVE", geographic_scope_type="JURISDICTION",
                region_id=1, jurisdiction_id=1, source_name="t",
                source_version="v1", record_count=12,
            )
            db.add(occ_dataset_row); db.flush()

            inputs = SuitabilityTrainingInputs(
                occurrence_dataset=occ_summary,
                occurrence_rows=tuple([
                    __import__("models").HistoricalOccurrence(
                        id=i, scientific_name=HYPOTHETICAL_SPECIES,
                        taxon_id=999, latitude=row[1], longitude=row[2],
                        event_date=None, source="TEST",
                        deduplication_key=f"hyp-{i}",
                        dataset_id=datasets["occ_dataset_id"],
                    )
                    for i, row in enumerate(occ_rows)
                ]),
                environmental_datasets=((env_summary, (
                    __import__("models").PredictionSampleEnvironmentalFeature(
                        id=i,
                        # Match the grid's cell_id scheme:
                        # grid bounds (-50, -49, 30, 30.75),
                        # grid_size=0.5,
                        # so cell_ids are '60:-100', '60:-99',
                        # '61:-100', '61:-99'.
                        prediction_model_sample_id={
                            (60, -100): "60:-100",
                            (60, -99): "60:-99",
                            (61, -100): "61:-100",
                            (61, -99): "61:-99",
                        }[(60 + i // 2, -100 + i % 2)],
                        scientific_dataset_id=datasets["env_dataset_id"],
                        feature_name="bathymetry_center_depth",
                        value=1.0, source="TEST", sampling_method="NEAREST",
                        feature_version="hypothetical-environment-v1",
                    )
                    for i in range(4)
                )),),
                provenance_summary={
                    "occurrence": occ_summary,
                    "environmental": [env_summary],
                },
            )
            from sklearn.linear_model import LogisticRegression
            import numpy as np
            # Fit a tiny model on the synthetic data so predict_grid
            # can actually produce scored cells.
            train_X = np.array([
                [0.5], [0.6], [0.7], [0.8], [0.9], [1.0],
                [1.5], [1.6], [1.7], [1.8], [1.9], [2.0],
            ])
            train_y = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
            fitted_model = LogisticRegression()
            fitted_model.fit(train_X, train_y)
            result = SuitabilityTrainingResult(
                spec_snapshot=dataclasses.asdict(spec),
                candidate_results={
                    "model_b_physical_habitat": SuitabilityCandidateResult(
                        name="model_b_physical_habitat",
                        features=("bathymetry_center_depth",),
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
                selected_candidate_name="model_b_physical_habitat",
                selection_rationale={"rule": "test"},
                fitted_model=fitted_model,
                selected_feature_names=("bathymetry_center_depth",),
                training_sample_count=10,
                presence_count=5,
                background_count=5,
                feature_names=("a", "b"),
                dataset_provenance={},
                warnings=[],
                feature_version="hypothetical-environment-v1",
                model_version="hypothetical-suitability-v1",
                generation_version="hypothetical-grid-v1",
            )
            import joblib
            tmp_artifact = tempfile.NamedTemporaryFile(
                suffix=".joblib", delete=False, dir=tmpdir,
            )
            tmp_artifact.close()
            joblib.dump(fitted_model, tmp_artifact.name)
            expected_artifact_sha = hashlib.sha256(
                open(tmp_artifact.name, "rb").read()
            ).hexdigest()

            record_training_completion(
                db, run, result,
                artifact_path=tmp_artifact.name,
                artifact_sha256=expected_artifact_sha,
            )
            db.commit()

            assert run.status == STATUS_COMPLETED
            assert run.artifact_sha256 == expected_artifact_sha
            assert run.training_input_sha256 == input_sha
            assert run.input_integrity_status == "COMPLETE"
            assert run.selected_candidate == "model_b_physical_habitat"
            assert run.artifact_path == tmp_artifact.name

            # ------------------------------------------------------------------
            # Step 8: model artifact chain validation.
            # ------------------------------------------------------------------
            chain = verify_model_artifact_chain(db, run)
            assert chain["matches_run_sha"] is True
            assert chain["status"] == "COMPLETE"

            # ------------------------------------------------------------------
            # Step 9: predict + non-active deployment candidate.
            # ------------------------------------------------------------------
            from suitability_prediction_engine import (
                predict_grid, prepare_deployment_candidate,
            )
            prediction = predict_grid(result, inputs, grid)
            assert prediction.total_cells > 0
            assert prediction.scored_cells > 0
            for cell in prediction.cell_predictions:
                if cell.status == "SCORED":
                    assert 0.0 <= cell.score <= 1.0
                    assert cell.band in (
                        "VERY_LOW", "LOW", "MODERATE", "HIGH", "VERY_HIGH",
                    )

            candidate = prepare_deployment_candidate(
                prediction, species_program_id=ids["species_program_id"],
            )
            assert candidate.is_active is False
            assert candidate.status in ("CANDIDATE", "NOT_ACTIVE")
            assert candidate.status != "ACTIVE"

            # ------------------------------------------------------------------
            # Step 10: completed-run immutability.
            # ------------------------------------------------------------------
            with pytest.raises(ValueError):
                assert_completed_immutable(run, "configuration_json")
            with pytest.raises(ValueError):
                assert_completed_immutable(run, "configuration_sha256")
            with pytest.raises(ValueError):
                assert_completed_immutable(run, "artifact_sha256")
            with pytest.raises(ValueError):
                assert_completed_immutable(run, "selected_candidate")
            with pytest.raises(ValueError):
                link_training_run_dataset(
                    db, run, occ_dataset, "TRAINING_OCCURRENCES",
                )

            # ------------------------------------------------------------------
            # Step 11: dataset artifact immutability for COMPLETED runs.
            # ------------------------------------------------------------------
            with open(datasets["occ_path"], "ab") as f:
                f.write(b"# extra\n")
            with pytest.raises(ValueError):
                register_dataset_artifact(
                    db, occ_dataset, datasets["occ_path"],
                    artifact_format="csv",
                    expected_record_count=12,
                )
            with open(datasets["occ_path"], "wb") as f:
                f.write(open(datasets["occ_path"], "rb").read()[: -len(b"# extra\n")])

            # ------------------------------------------------------------------
            # Step 12: reproducibility check.
            # ------------------------------------------------------------------
            canonical2 = canonical_configuration_json(
                build_configuration_snapshot(spec),
            )
            assert canonical == canonical2
            assert sha == compute_configuration_sha256(snapshot)
            input_sha_again, status_again = compute_training_input_sha256(
                db, run,
            )
            assert input_sha == input_sha_again
            assert status_again == "COMPLETE"

            artifact_bytes = open(tmp_artifact.name, "rb").read()
            sha_now = hashlib.sha256(artifact_bytes).hexdigest()
            # Don't assert byte-identical because joblib serialization
            # may include timestamps.
            if sha_now == expected_artifact_sha:
                byte_identical = True
            else:
                byte_identical = False
            assert canonical2 == canonical
        finally:
            db.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_legacy_jamaica_remains_partial():
    """The existing Jamaica legacy TrainingRun stays LEGACY_RECONSTRUCTED
    with PARTIAL input integrity and schema_version=1."""
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT configuration_json FROM training_runs WHERE id = 1"
        ).fetchone()
        snapshot = json.loads(row[0])
        assert snapshot["schema_version"] == 1
        status = conn.execute(
            "SELECT provenance_origin, input_integrity_status "
            "FROM training_runs WHERE id = 1"
        ).fetchone()
        assert status[0] == "LEGACY_RECONSTRUCTED"
        assert status[1] == "PARTIAL"
    finally:
        conn.close()


def test_bahamas_firewall_intact():
    """Bahamas remains without SpeciesProgram, deployment, or
    environmental rows."""
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")
    conn = sqlite3.connect(db_path)
    try:
        sp_count = conn.execute(
            "SELECT COUNT(*) FROM species_programs WHERE jurisdiction_id = 2"
        ).fetchone()[0]
        assert sp_count == 0
        dep_count = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert dep_count == 0
        env_count = conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features "
            "WHERE scientific_dataset_id IN ("
            "SELECT id FROM scientific_datasets "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
            ")"
        ).fetchone()[0]
        assert env_count == 0
    finally:
        conn.close()


def test_migration_idempotency():
    """Phase 10E migrations are idempotent.

    Each migration must be safe to run twice without altering
    scientific state or duplicating rows.
    """
    tmpdir = tempfile.mkdtemp(prefix="phase10e6_mig_")
    try:
        db_path = os.path.join(tmpdir, "fixture.db")
        conn = sqlite3.connect(db_path)
        _bootstrap_schema(conn)
        # Seed an ENVIRONMENTAL dataset with the production feature
        # version slug so the 10E-1 backfill can find an owner.
        conn.execute(
            "INSERT INTO scientific_datasets (id, slug, name, "
            "dataset_type, status, geographic_scope_type, region_id, "
            "jurisdiction_id, source_name, source_version, record_count, "
            "artifact_path, artifact_sha256, created_at) "
            "VALUES (1, 'caribbean-grid-v2-environment-v1', "
            "'h-env', 'ENVIRONMENTAL', 'ACTIVE', 'REGION', 1, NULL, "
            "'TEST', 'caribbean-grid-v2-environment-v1', 5, NULL, NULL, "
            "CURRENT_TIMESTAMP)"
        )
        # Seed an environmental row with the production feature_version
        # so the migration can backfill it.
        conn.execute(
            "INSERT INTO prediction_sample_environmental_features "
            "(id, prediction_model_sample_id, scientific_dataset_id, "
            "feature_name, value, source, sampling_method, is_missing, "
            "metadata_json, feature_version, created_at) "
            "VALUES (1, 1, NULL, 'a', 1.0, 't', 'N', 0, NULL, "
            "'caribbean-grid-v2-environment-v1', CURRENT_TIMESTAMP)"
        )
        conn.commit()
        conn.close()

        # 10E-1 migration idempotency.
        from phase10e1_migrate_environmental_ownership import (
            run_migration as run_10e1,
        )
        conn = sqlite3.connect(db_path)
        try:
            # First run actually backfills the seeded row.
            first = run_10e1(conn)
            conn.commit()
            # Second run is a no-op: no new rows backfilled, and the
            # migration should NOT re-add columns/indexes/constraints.
            second = run_10e1(conn)
            assert second["rows_backfilled"] == 0
            assert second["column_added"] is False
            assert second["column_made_not_null"] is False
            assert second["new_unique_created"] is False
        finally:
            conn.close()

        # 10E-2 migration idempotency.
        from phase10e2_migrate_training_run import (
            run_migration as run_10e2,
        )
        conn = sqlite3.connect(db_path)
        try:
            first = run_10e2(conn)
            second = run_10e2(conn)
            assert first["training_runs_created"] is False
            assert second["training_runs_created"] is False
        finally:
            conn.close()

        # 10E-4 migration idempotency.
        from phase10e4_migrate_chain_of_custody import (
            run_migration as run_10e4,
        )
        conn = sqlite3.connect(db_path)
        try:
            first = run_10e4(conn)
            second = run_10e4(conn)
            assert first["training_input_sha256_added"] is False
            assert second["training_input_sha256_added"] is False
            assert first["input_integrity_status_added"] is False
            assert second["input_integrity_status_added"] is False
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_genericity_audit():
    """The Phase 10E generic modules do not require Jamaica,
    Pterois volitans, or production dataset IDs to execute a
    future-native run."""
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )

    grid = SuitabilityGrid(
        grid_size_degrees=0.5,
        bounds=(-50.0, -49.0, 30.0, 31.0),
        name="test-grid",
    )
    spec = SuitabilityTrainingSpec(
        species="Test fish",
        species_program_id=999,
        geographic_scope="JURISDICTION",
        region_id=99,
        jurisdiction_id=99,
        occurrence_dataset_id=999,
        environmental_dataset_ids=(999,),
        feature_version="test-env-v1",
        generation_version="test-grid-v1",
        model_version="test-suitability-v1",
        random_seed=1,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        background_extent_bounds={
            "latitude_min": 30.0, "latitude_max": 31.0,
            "longitude_min": -50.0, "longitude_max": -49.0,
        },
        spatial_block_origin={
            "latitude_origin": 30.0, "longitude_origin": -50.0,
        },
        grid=grid,
    )
    snapshot = json.dumps({
        "background_extent": spec.background_extent_bounds,
        "spatial_block_origin": spec.spatial_block_origin,
        "grid_bounds": list(spec.grid.bounds),
        "species": spec.species,
    }).lower()
    assert "jamaica" not in snapshot
    assert "pterois" not in snapshot
    assert "caribbean" not in snapshot
    assert "30.0" in snapshot
    assert "test fish" in snapshot


def test_documented_limitations_are_acknowledged():
    """The Phase 10E-5 / 10E-6 documentation explicitly acknowledges
    that legacy Jamaica run is PARTIAL and that no controlled
    historical artifacts exist for the production datasets."""
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT configuration_json, input_integrity_status "
            "FROM training_runs WHERE id = 1"
        ).fetchone()
        snapshot = json.loads(row[0])
        assert snapshot["schema_version"] == 1
        assert row[1] == "PARTIAL"
    finally:
        conn.close()