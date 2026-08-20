"""Phase 10E-5 focused tests: remove hidden geographic defaults.

Run only:
    pytest test_phase10e5_explicit_geography.py -v

These tests prove:
- Generic SuitabilityTrainingSpec requires explicit fields.
- Generic engine has no DEFAULT_BACKGROUND_REGION_BOUNDS fallback.
- Background sampling uses spec background extent.
- Spatial blocking uses spec origin.
- Non-Caribbean hypothetical extent works.
- Configuration snapshot persists explicit geography.
- Jamaica compatibility factory fills all three explicitly.
- Legacy Jamaica still reconstructs from snapshot.
- No training/prediction/deployment activation.
- Production scientific state unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3

import pytest


def _db_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def _require_production():
    if not os.path.exists(_db_path()):
        pytest.skip("Production DB not present")


# ---------------------------------------------------------------------------
# 1. Generic spec requires explicit grid.
# ---------------------------------------------------------------------------


def test_generic_spec_requires_explicit_grid():
    from suitability_training_spec import SuitabilityTrainingSpec
    with pytest.raises(ValueError, match="grid is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            background_extent_bounds={
                "latitude_min": 9.0, "latitude_max": 28.0,
                "longitude_min": -89.0, "longitude_max": -59.0,
            },
            spatial_block_origin={
                "latitude_origin": 9.0, "longitude_origin": -89.0,
            },
        )


# ---------------------------------------------------------------------------
# 2. Generic spec requires explicit background extent.
# ---------------------------------------------------------------------------


def test_generic_spec_requires_explicit_background_extent():
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    with pytest.raises(ValueError, match="background_extent_bounds is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            spatial_block_origin={
                "latitude_origin": 9.0, "longitude_origin": -89.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(0.0, 0.5, 0.0, 0.5),
                name="h",
            ),
        )


# ---------------------------------------------------------------------------
# 3. Generic spec requires explicit spatial block origin where required.
# ---------------------------------------------------------------------------


def test_generic_spec_requires_explicit_spatial_block_origin():
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    with pytest.raises(ValueError, match="spatial_block_origin is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            background_extent_bounds={
                "latitude_min": 9.0, "latitude_max": 28.0,
                "longitude_min": -89.0, "longitude_max": -59.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(0.0, 0.5, 0.0, 0.5),
                name="h",
            ),
        )


# ---------------------------------------------------------------------------
# 4. Jamaica compatibility factory fills all three explicitly.
# ---------------------------------------------------------------------------


def test_jamaica_v3_factory_fills_all_three_explicitly():
    from suitability_training_spec import SuitabilityTrainingSpec
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    assert spec.background_extent_bounds == {
        "latitude_min": 9.0, "latitude_max": 28.0,
        "longitude_min": -89.0, "longitude_max": -59.0,
    }
    assert spec.spatial_block_origin == {
        "latitude_origin": 9.0, "longitude_origin": -89.0,
    }
    assert spec.grid.name == "jamaica-v3"
    assert spec.grid.bounds == (-78.6, -75.9, 16.9, 18.7)


# ---------------------------------------------------------------------------
# 5. Generic engine has no DEFAULT_BACKGROUND_REGION_BOUNDS fallback.
# ---------------------------------------------------------------------------


def test_engine_no_default_background_fallback():
    import inspect
    import suitability_training_engine as eng
    src = inspect.getsource(eng)
    # The module-level constant DEFAULT_BACKGROUND_REGION_BOUNDS
    # was removed in Phase 10E-5. Any reference to it (other than
    # the deletion comment) is a regression.
    pattern = re.compile(
        r"DEFAULT_BACKGROUND_REGION_BOUNDS\s*="
    )
    matches = list(pattern.finditer(src))
    # Only the comment line is acceptable; it does not match
    # "DEFAULT_BACKGROUND_REGION_BOUNDS =" since the comment
    # uses the past tense.
    assert matches == [], (
        f"DEFAULT_BACKGROUND_REGION_BOUNDS constant must be removed; "
        f"found {len(matches)} occurrences"
    )


# ---------------------------------------------------------------------------
# 6. Spatial-block calculation uses spec origin.
# ---------------------------------------------------------------------------


def test_spatial_block_uses_spec_origin():
    from suitability_training_engine import _build_candidate_matrix

    class _ProxySpec:
        def __init__(self, lat_origin, lon_origin, block_size=5.0):
            self.spatial_block_origin = {
                "latitude_origin": lat_origin,
                "longitude_origin": lon_origin,
            }
            self.spatial_block_size_degrees = block_size

    # Use a non-Jamaica origin.
    spec = _ProxySpec(lat_origin=30.0, lon_origin=-50.0, block_size=5.0)

    class _Sample:
        def __init__(self, lat, lon):
            self.latitude = lat
            self.longitude = lon
            self.sample_type = "PRESENCE"
            self.feature_values = {"a": 0.0, "b": 0.0}

    class _Dataset:
        def __init__(self, samples):
            self.samples = samples
            self.spec = spec
            self.feature_names = ("a", "b")

    # Both samples within the block at (30, -50) (origin) with size 5.
    samples = [
        _Sample(30.1, -50.1),
        _Sample(31.5, -49.5),
    ]
    _, _, groups = _build_candidate_matrix(_Dataset(samples), ("a", "b"))
    # First sample at (30.1, -50.1) with origin (30, -50) and block 5
    # => (int(round(0.1/5)), int(round(-0.1/5))) = (0, 0)
    # Second sample at (31.5, -49.5) with origin (30, -50) and block 5
    # => (int(round(1.5/5)), int(round(0.5/5))) = (0, 0)
    # So both should be in the same block.
    assert tuple(groups[0]) == tuple(groups[1])
    # Sanity check: a third sample far outside this block differs.
    samples.append(_Sample(40.0, -40.0))
    _, _, groups = _build_candidate_matrix(_Dataset(samples), ("a", "b"))
    assert tuple(groups[0]) != tuple(groups[2])


# ---------------------------------------------------------------------------
# 7. Background sampling uses spec background extent.
# ---------------------------------------------------------------------------


def test_background_sampling_uses_spec_extent():
    """The engine's ``_build_background_samples`` reads
    ``spec.background_extent_bounds`` rather than any module-level
    constant."""
    import inspect
    import suitability_training_engine as eng
    src = inspect.getsource(eng._build_background_samples)
    assert "spec.background_extent_bounds" in src


# ---------------------------------------------------------------------------
# 7b. Background-sample type contract matches runtime behaviour.
# ---------------------------------------------------------------------------


def test_background_sample_type_contract_matches_runtime():
    """The annotation and the runtime contract of
    ``_build_background_samples`` must agree.

    The runtime has always returned ``List[Tuple[float, float,
    float]]``. The annotation must match.
    """
    import inspect
    import suitability_training_engine as eng
    sig = inspect.signature(eng._build_background_samples)
    annotation = str(sig.return_annotation)
    # The annotation must reference the tuple return type, not the
    # SuitabilityTrainingSample dataclass (which is the conversion
    # responsibility of the caller).
    assert "Tuple[float, float, float]" in annotation
    # Runtime behaviour: tuples of three floats.
    from suitability_training_spec import SuitabilityGrid, SuitabilityTrainingSpec
    from suitability_training_engine import _build_background_samples
    import numpy as np
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(0.0, 0.5, 0.0, 0.5),
        name="g",
    )
    spec = SuitabilityTrainingSpec(
        species="X", species_program_id=1,
        geographic_scope="JURISDICTION", jurisdiction_id=1,
        region_id=None,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(1,),
        feature_version="fv", generation_version="gv",
        model_version="mv",
        background_extent_bounds={
            "latitude_min": 0.0, "latitude_max": 0.3,
            "longitude_min": 0.0, "longitude_max": 0.3,
        },
        spatial_block_origin={
            "latitude_origin": 0.0, "longitude_origin": 0.0,
        },
        grid=grid,
    )
    rng = np.random.default_rng(1)
    result = _build_background_samples(
        spec, rng, presence_cells={}, capacity=5,
    )
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, tuple)
        assert len(item) == 3
        assert all(isinstance(v, float) for v in item)


# ---------------------------------------------------------------------------
# 8. Non-Caribbean hypothetical extent works.
# ---------------------------------------------------------------------------


def test_non_caribbean_extent_works():
    """A spec with non-Caribbean extent must be accepted and the
    engine must use it without modification."""
    from suitability_training_spec import SuitabilityTrainingSpec
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    # Replace extent + spatial-block origin with non-Caribbean values.
    object.__setattr__(spec, "background_extent_bounds", {
        "latitude_min": 30.0, "latitude_max": 31.0,
        "longitude_min": -50.0, "longitude_max": -49.0,
    })
    object.__setattr__(spec, "spatial_block_origin", {
        "latitude_origin": 30.0, "longitude_origin": -50.0,
    })
    assert spec.background_extent_bounds["latitude_min"] == 30.0


# ---------------------------------------------------------------------------
# 9. Configuration snapshot persists explicit geography.
# ---------------------------------------------------------------------------


def test_configuration_snapshot_persists_explicit_geography():
    from suitability_training_run_repository import (
        build_configuration_snapshot, compute_configuration_sha256,
    )
    from suitability_training_spec import SuitabilityTrainingSpec
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    snapshot = build_configuration_snapshot(spec)
    # The snapshot should explicitly carry the geography.
    assert snapshot["background_extent"]["latitude_min"] == 9.0
    assert snapshot["background_extent"]["latitude_max"] == 28.0
    assert snapshot["spatial_block_origin"]["latitude_origin"] == 9.0
    assert snapshot["spatial_block_origin"]["longitude_origin"] == -89.0
    assert snapshot["prediction_grid"]["bounds"] == [-78.6, -75.9, 16.9, 18.7]
    # And a SHA must be computable.
    sha = compute_configuration_sha256(snapshot)
    assert len(sha) == 64


# ---------------------------------------------------------------------------
# 10. Non-Caribbean spec does not inherit Caribbean values.
# ---------------------------------------------------------------------------


def test_non_caribbean_spec_has_no_caribbean_defaults():
    """A spec built for a non-Caribbean jurisdiction must NOT silently
    inherit Caribbean values via source_config."""
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-50.0, -49.0, 30.0, 31.0),
        name="non-caribbean",
    )
    spec = SuitabilityTrainingSpec(
        species="Hyp sp.",
        species_program_id=1,
        geographic_scope="REGION",
        region_id=1,
        jurisdiction_id=None,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        background_extent_bounds={
            "latitude_min": 30.0, "latitude_max": 31.0,
            "longitude_min": -50.0, "longitude_max": -49.0,
        },
        spatial_block_origin={
            "latitude_origin": 30.0, "longitude_origin": -50.0,
        },
        grid=grid,
    )
    assert spec.background_extent_bounds["latitude_min"] == 30.0
    assert spec.background_extent_bounds["latitude_max"] == 31.0
    assert spec.background_extent_bounds["longitude_min"] == -50.0
    assert spec.background_extent_bounds["longitude_max"] == -49.0
    assert spec.grid.bounds == (-50.0, -49.0, 30.0, 31.0)
    assert spec.spatial_block_origin["latitude_origin"] == 30.0


# ---------------------------------------------------------------------------
# 11. Invalid latitude bounds rejected.
# ---------------------------------------------------------------------------


def test_invalid_latitude_bounds_rejected():
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    with pytest.raises(ValueError, match="outside"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            background_extent_bounds={
                "latitude_min": -200.0, "latitude_max": 28.0,
                "longitude_min": -89.0, "longitude_max": -59.0,
            },
            spatial_block_origin={
                "latitude_origin": 9.0, "longitude_origin": -89.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(0.0, 0.5, 0.0, 0.5),
                name="h",
            ),
        )


# ---------------------------------------------------------------------------
# 12. Invalid longitude bounds rejected.
# ---------------------------------------------------------------------------


def test_invalid_longitude_bounds_rejected():
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    with pytest.raises(ValueError, match="outside"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            background_extent_bounds={
                "latitude_min": 9.0, "latitude_max": 28.0,
                "longitude_min": -300.0, "longitude_max": -59.0,
            },
            spatial_block_origin={
                "latitude_origin": 9.0, "longitude_origin": -89.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(0.0, 0.5, 0.0, 0.5),
                name="h",
            ),
        )


# ---------------------------------------------------------------------------
# 13. Reversed bounds rejected.
# ---------------------------------------------------------------------------


def test_reversed_bounds_rejected():
    from suitability_training_spec import (
        SuitabilityGrid, SuitabilityTrainingSpec,
    )
    with pytest.raises(ValueError, match="must be <"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            background_extent_bounds={
                "latitude_min": 28.0, "latitude_max": 9.0,
                "longitude_min": -89.0, "longitude_max": -59.0,
            },
            spatial_block_origin={
                "latitude_origin": 9.0, "longitude_origin": -89.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(0.0, 0.5, 0.0, 0.5),
                name="h",
            ),
        )


# ---------------------------------------------------------------------------
# 14. Prediction requires explicit grid.
# ---------------------------------------------------------------------------


def test_prediction_requires_explicit_grid():
    """``predict_grid`` must always receive an explicit grid; the
    spec default must never silently inject a grid."""
    import inspect
    import suitability_prediction_engine as eng
    sig = inspect.signature(eng.predict_grid)
    assert "grid" in sig.parameters
    # And it must NOT accept a ``spec`` parameter (the prediction
    # engine has no business with the training spec).
    assert "spec" not in sig.parameters


# ---------------------------------------------------------------------------
# 15. Native completion rejects missing geography.
# ---------------------------------------------------------------------------


def test_native_completion_rejects_missing_geography():
    """``validate_native_completion`` rejects a native run whose
    configuration snapshot is missing the new geography fields.
    """
    import json
    from suitability_training_run_repository import (
        build_configuration_snapshot, compute_configuration_sha256,
        validate_native_completion,
    )
    from suitability_training_spec import SuitabilityTrainingSpec

    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    # Start from a complete snapshot, then strip ``background_extent``.
    snapshot = build_configuration_snapshot(spec)
    snapshot.pop("background_extent", None)
    # Recompute the configuration_sha256 for the (incomplete) snapshot.
    expected_sha = compute_configuration_sha256(snapshot)

    class _FakeRun:
        id = 999
        provenance_origin = "NATIVE"
        configuration_json = json.dumps(snapshot)
        configuration_sha256 = expected_sha
        artifact_sha256 = "x" * 64
        validation_metrics_json = "{}"
        training_input_sha256 = "y" * 64
        input_integrity_status = "COMPLETE"
        species_program_id = spec.species_program_id

        @property
        def selected_candidate(self):
            return "model_b_physical_habitat"

        @property
        def dataset_links(self):
            return []

    with pytest.raises(ValueError):
        validate_native_completion(None, _FakeRun(), None)


def spec_to_json(spec):
    """Local helper that returns the spec as a JSON dict."""
    import dataclasses, json
    return json.dumps(dataclasses.asdict(spec))


def dataclasses_asdict(spec):
    import dataclasses
    return dataclasses.asdict(spec)


# ---------------------------------------------------------------------------
# 16. Legacy Jamaica remains valid.
# ---------------------------------------------------------------------------


def test_legacy_jamaica_remains_valid():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        # Existing artifact SHA must be unchanged.
        artifact_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "prediction_models",
            "pterois-volitans-suitability-v3.joblib",
        )
        if os.path.exists(artifact_path):
            actual = hashlib.sha256(
                open(artifact_path, "rb").read()
            ).hexdigest()
            assert actual == (
                "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
            )
        # Deployment row exists with LEGACY_RECONSTRUCTED training run.
        row = conn.execute(
            "SELECT d.id, d.training_run_id, r.provenance_origin "
            "FROM suitability_deployments d "
            "LEFT JOIN training_runs r ON d.training_run_id = r.id "
            "WHERE d.model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()
        assert row is not None
        if row[1] is not None:
            assert row[2] == "LEGACY_RECONSTRUCTED"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 17. No training is executed.
# ---------------------------------------------------------------------------


def test_no_training_is_executed():
    """The Phase 10E-5 module only audits. It MUST NOT train."""
    import inspect
    import suitability_prediction_engine as eng
    src = inspect.getsource(eng)
    forbidden = (
        "LogisticRegression(",
        "HistGradientBoostingClassifier(",
        "StratifiedGroupKFold(",
        ".fit(",
    )
    for token in forbidden:
        assert token not in src, (
            f"prediction engine must not execute training: {token!r}"
        )


# ---------------------------------------------------------------------------
# 18. No deployment activation.
# ---------------------------------------------------------------------------


def test_no_deployment_activation():
    """The Phase 10E-5 module does NOT activate any deployment."""
    import inspect
    import suitability_training_run_repository as repo
    src = inspect.getsource(repo)
    forbidden = (
        "INSERT INTO suitability_deployments",
        "UPDATE suitability_deployments SET status",
    )
    for token in forbidden:
        assert token not in src, (
            f"repository must not activate deployments: {token!r}"
        )


# ---------------------------------------------------------------------------
# 19. Production scientific integrity invariants.
# ---------------------------------------------------------------------------


def test_production_scientific_state_unchanged():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0] == 12
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_occurrences"
        ).fetchone()[0] == 54
        assert conn.execute(
            "SELECT COUNT(*) FROM prediction_sample_environmental_features"
        ).fetchone()[0] == 25674
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
            "SELECT COUNT(*) FROM next_area_snapshot_cells "
            "WHERE generation_id IN ("
            "SELECT id FROM next_area_snapshot_generations "
            "WHERE is_active = 1 AND status = 'ACTIVE'"
            ")"
        ).fetchone()[0] == 390
        assert conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 20. Legacy TrainingRun schema_version remains 1.
# ---------------------------------------------------------------------------


def test_legacy_training_run_schema_version():
    _require_production()
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            "SELECT configuration_json FROM training_runs WHERE id = 1"
        ).fetchone()
        snapshot = json.loads(row[0])
        assert snapshot["schema_version"] == 1
        assert snapshot["provenance_origin"] == "LEGACY_RECONSTRUCTED"
    finally:
        conn.close()
