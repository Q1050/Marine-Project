"""Phase 10D-4 focused tests for the generalized grid prediction engine.

Run only:
    pytest test_phase10d4_prediction_engine.py -v

The tests verify:
- grid generation uses the explicit SuitabilityGrid
- the predictor does not assume Jamaica / Pterois / pterois-v3
- cell ordering is deterministic
- the v3 band thresholds (0.2, 0.4, 0.6, 0.8) are preserved
- the predictor does NOT write to the database
- the predictor does NOT create SuitabilityDeployment
- the predictor does NOT regenerate monitoring priority
- prepare_deployment_candidate returns a non-active structured candidate
- existing Jamaica v3 artifact and cells remain unchanged
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import sqlite3
import sys
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Proxy / fixture helpers.
# ---------------------------------------------------------------------------


PHYSICAL_FEATURES = (
    "bathymetry_center_depth",
    "bathymetry_neighbor_mean",
    "bathymetry_neighbor_std",
    "bathymetry_local_relief",
    "bathymetry_max_slope",
    "distance_to_land_km",
)
CLIMATE_FEATURES = (
    "sst_climatology_annual_mean",
    "sst_climatology_monthly_min",
    "sst_climatology_monthly_max",
    "sst_climatology_seasonal_range",
    "salinity_climatology_annual_mean",
)


class _ProxyEnv:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ProxyOcc:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _build_env_features(grid_bounds, grid_size, value_factory):
    """Yield _ProxyEnv rows covering ``grid_bounds`` at ``grid_size``."""
    lon_min, lon_max, lat_min, lat_max = grid_bounds
    next_id = 0
    rows = []
    for lat_index in range(int(round(lat_min / grid_size)),
                           int(round(lat_max / grid_size))):
        for lon_index in range(int(round(lon_min / grid_size)),
                               int(round(lon_max / grid_size))):
            cell_id = f"{lat_index}:{lon_index}"
            for feature_index, fn in enumerate(PHYSICAL_FEATURES + CLIMATE_FEATURES):
                rows.append(_ProxyEnv(
                    id=next_id,
                    prediction_model_sample_id=cell_id,
                    feature_name=fn, value=value_factory(feature_index),
                    source="test",
                    sampling_method="NEAREST",
                    is_missing=False,
                    feature_version="caribbean-grid-v2-environment-v1",
                ))
                next_id += 1
    return tuple(rows)


def _make_inputs(env_rows=None, value_factory=None, occurrences=None):
    """Build a SuitabilityTrainingInputs bundle for prediction tests."""
    from suitability_training_loaders import (
        DatasetProvenanceSummary, SuitabilityTrainingInputs,
    )

    class _ProxyDataset:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    if occurrences is None:
        # Default: 10 presences spread 2.5° apart so they fall in
        # distinct 5° spatial blocks. This produces multiple
        # StratifiedGroupKFold groups, matching the v3 spatial-blocking
        # hygiene.
        occurrence_ids = list(range(10))
    else:
        occurrence_ids = list(occurrences)

    summary = DatasetProvenanceSummary(
        id=1, slug="occ", name="occ", dataset_type="OCCURRENCE",
        status="ACTIVE", geographic_scope_type="REGION",
        region_id=1, jurisdiction_id=None, species_id=1,
        species_program_id=1, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=len(occurrence_ids),
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    env_summary = DatasetProvenanceSummary(
        id=2, slug="env", name="env", dataset_type="ENVIRONMENTAL",
        status="ACTIVE", geographic_scope_type="REGION",
        region_id=1, jurisdiction_id=None, species_id=1,
        species_program_id=1, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=len(env_rows or ()),
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    occ_dataset = _ProxyDataset(
        id=summary.id, slug=summary.slug, name=summary.name,
        dataset_type=summary.dataset_type, status=summary.status,
        geographic_scope_type=summary.geographic_scope_type,
        region_id=summary.region_id, jurisdiction_id=summary.jurisdiction_id,
        species_id=summary.species_id, species_program_id=summary.species_program_id,
        source_name=summary.source_name, source_type=summary.source_type,
        source_reference=summary.source_reference, source_version=summary.source_version,
        retrieved_at=summary.retrieved_at, record_count=summary.record_count,
        artifact_path=summary.artifact_path, artifact_sha256=summary.artifact_sha256,
        notes=summary.notes,
    )
    env_dataset = _ProxyDataset(
        id=env_summary.id, slug=env_summary.slug, name=env_summary.name,
        dataset_type=env_summary.dataset_type, status=env_summary.status,
        geographic_scope_type=env_summary.geographic_scope_type,
        region_id=env_summary.region_id, jurisdiction_id=env_summary.jurisdiction_id,
        species_id=env_summary.species_id, species_program_id=env_summary.species_program_id,
        source_name=env_summary.source_name, source_type=env_summary.source_type,
        source_reference=env_summary.source_reference, source_version=env_summary.source_version,
        retrieved_at=env_summary.retrieved_at, record_count=env_summary.record_count,
        artifact_path=env_summary.artifact_path, artifact_sha256=env_summary.artifact_sha256,
        notes=env_summary.notes,
    )

    occ_rows = tuple(
        _ProxyOcc(
            id=i, scientific_name="Pterois volitans", taxon_id=159559,
            latitude=18.0 + i * 2.5,
            longitude=-77.0 + i * 0.0,
            event_date=None, source="test",
            deduplication_key=f"test-{i}",
            dataset_id=1,
        )
        for i in occurrence_ids
    )

    if value_factory is None:
        def value_factory(_i): return 0.5
    return SuitabilityTrainingInputs(
        occurrence_dataset=occ_dataset,
        occurrence_rows=occ_rows,
        environmental_datasets=(
            (env_dataset, env_rows if env_rows is not None else ()),
        ),
        provenance_summary={"occurrence": summary, "environmental": [env_summary]},
    )


def _train_minimal(spec_kwargs=None, env_grid_bounds=None):
    """Train a tiny model and return the SuitabilityTrainingResult.

    The training is driven through the Phase 10D-3 engine with a
    minimal grid covering the test grid bounds. Returns the
    ``SuitabilityTrainingResult`` produced by ``train``.
    """
    from suitability_training_engine import train
    from suitability_training_spec import SuitabilityTrainingSpec, SuitabilityGrid

    if env_grid_bounds is None:
        # Cover lat 17.5..43.5 (10 presences at lat 18, 20.5, ..., 40.5)
        # and lon -77..-77, so background sampling can find valid cells.
        env_grid_bounds = (-78.0, -76.0, 17.5, 43.5)

    def _value_factory(_i): return 0.5
    env_rows = _build_env_features(env_grid_bounds, 0.1, _value_factory)
    inputs = _make_inputs(env_rows=env_rows, occurrences=list(range(10)))

    spec = SuitabilityTrainingSpec(
        species="Pterois volitans",
        species_program_id=1,
        geographic_scope="REGION",
        region_id=1,
        jurisdiction_id=None,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        random_seed=4242,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        artifact_path=None,
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    if spec_kwargs:
        spec = dataclasses.replace(spec, **spec_kwargs)
    return train(spec, inputs, artifact_path=None)


# ---------------------------------------------------------------------------
# 1. Grid generation uses SuitabilityGrid.
# ---------------------------------------------------------------------------


def test_grid_generation_uses_spec_grid():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="test-grid",
    )
    result = predict_grid(training_result, _make_inputs(), grid)
    assert result.grid == {
        "name": "test-grid",
        "bounds": [-78.0, -76.0, 17.5, 18.5],
        "grid_size_degrees": 0.1,
    }


# ---------------------------------------------------------------------------
# 2. A different hypothetical jurisdiction can use different bounds.
# ---------------------------------------------------------------------------


def test_different_jurisdiction_uses_different_bounds():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.2,
        bounds=(12.0, 14.0, 41.5, 43.5),
        name="hypothetical-jurisdiction",
    )
    result = predict_grid(training_result, _make_inputs(), grid)
    assert result.grid["bounds"] == [12.0, 14.0, 41.5, 43.5]
    assert result.grid["grid_size_degrees"] == 0.2
    assert result.grid["name"] == "hypothetical-jurisdiction"


# ---------------------------------------------------------------------------
# 3. No Jamaica bounds are inherited automatically.
# ---------------------------------------------------------------------------


def test_no_jamaica_bounds_inherited_automatically():
    import suitability_prediction_engine as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "JAMAICA_BOUNDS",
        "jamaica_bounds",
        "pterois-volitans-suitability-v3",
        "pterois_volitans",
    )
    for token in forbidden:
        assert token not in src, (
            f"prediction engine must not reference {token!r}"
        )


# ---------------------------------------------------------------------------
# 4. Cell ordering is deterministic.
# ---------------------------------------------------------------------------


def test_cell_ordering_is_deterministic():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="deterministic",
    )
    first = predict_grid(training_result, _make_inputs(), grid)
    second = predict_grid(training_result, _make_inputs(), grid)
    first_ids = [cell.grid_cell_id for cell in first.cell_predictions]
    second_ids = [cell.grid_cell_id for cell in second.cell_predictions]
    assert first_ids == second_ids
    # Cells are enumerated row-major by (lat_index, lon_index): outer
    # loop = latitude index ascending, inner loop = longitude index
    # ascending. Verify this directly from the cell ids
    # ("{lat_index}:{lon_index}").
    def parse(cell_id):
        lat_str, lon_str = cell_id.split(":")
        return int(lat_str), int(lon_str)
    parsed = [parse(cell_id) for cell_id in first_ids]
    for index in range(1, len(parsed)):
        prev_lat, prev_lon = parsed[index - 1]
        cur_lat, cur_lon = parsed[index]
        assert (prev_lat, prev_lon) <= (cur_lat, cur_lon), (
            "Cells must be enumerated row-major by (lat_index, lon_index)"
        )


# ---------------------------------------------------------------------------
# 5. Selected fitted model generates scores.
# ---------------------------------------------------------------------------


def test_selected_fitted_model_generates_scores():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="scoring",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5),
        0.1,
        lambda _i: 0.5,
    )
    inputs = _make_inputs(env_rows=env_rows)
    result = predict_grid(training_result, inputs, grid)
    assert result.scored_cells >= 1
    for cell in result.cell_predictions:
        if cell.status == "SCORED":
            assert cell.score is not None
            assert 0.0 <= cell.score <= 1.0


# ---------------------------------------------------------------------------
# 6. Suitability band thresholds match current semantics.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_band",
    [
        (0.0, "VERY_LOW"),
        (0.1, "VERY_LOW"),
        (0.2, "LOW"),
        (0.3, "LOW"),
        (0.4, "MODERATE"),
        (0.5, "MODERATE"),
        (0.6, "HIGH"),
        (0.7, "HIGH"),
        (0.8, "VERY_HIGH"),
        (0.9, "VERY_HIGH"),
        (1.0, "VERY_HIGH"),
    ],
)
def test_band_thresholds_match_v3_semantics(score, expected_band):
    from suitability_prediction_engine import suitability_band

    assert suitability_band(score) == expected_band


def test_band_thresholds_match_v3_for_all_cells():
    from suitability_prediction_engine import predict_grid, suitability_band
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="band-check",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5),
        0.1,
        lambda _i: 0.5,
    )
    inputs = _make_inputs(env_rows=env_rows)
    result = predict_grid(training_result, inputs, grid)
    for cell in result.cell_predictions:
        if cell.status == "SCORED":
            assert cell.band == suitability_band(cell.score)


# ---------------------------------------------------------------------------
# 7. Prediction result contains species/model/grid/provenance.
# ---------------------------------------------------------------------------


def test_prediction_result_contains_required_fields():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="result-fields",
    )
    result = predict_grid(training_result, _make_inputs(), grid)
    assert result.species == "Pterois volitans"
    assert result.geographic_scope == "REGION"
    assert result.region_id == 1
    assert result.model_version == training_result.model_version
    assert result.feature_version == training_result.feature_version
    assert result.generation_version == training_result.generation_version
    assert result.grid["name"] == "result-fields"
    assert "occurrence_dataset_id" in result.dataset_provenance
    assert result.generated_at


# ---------------------------------------------------------------------------
# 8. Environmental feature lookup uses explicit input bundle.
# ---------------------------------------------------------------------------


def test_environmental_feature_lookup_uses_inputs():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()

    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="env-lookup",
    )

    def _factory_with_signal(_i): return 0.7
    env_rows_with_signal = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5), 0.1, _factory_with_signal
    )
    inputs_with_signal = _make_inputs(env_rows=env_rows_with_signal)
    result_with = predict_grid(training_result, inputs_with_signal, grid)
    assert result_with.scored_cells > 0

    def _factory_sparse(_i): return float("nan")
    # No env rows means INCOMPLETE_FEATURES for every cell.
    inputs_empty = _make_inputs(env_rows=())
    result_empty = predict_grid(training_result, inputs_empty, grid)
    assert result_empty.scored_cells == 0
    assert result_empty.incomplete_cells == result_empty.total_cells


# ---------------------------------------------------------------------------
# 9. Missing feature values fail or are handled exactly per v3 semantics.
# ---------------------------------------------------------------------------


def test_missing_feature_values_handled_per_v3_semantics():
    from suitability_prediction_engine import predict_grid
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="missing-features",
    )

    incomplete_rows = []
    lat_index = 180
    lon_index = -780
    cell_id = f"{lat_index}:{lon_index}"
    # Provide only one feature so the rest are missing.
    incomplete_rows.append(_ProxyEnv(
        id=0, prediction_model_sample_id=cell_id,
        feature_name="bathymetry_center_depth", value=0.1,
        source="test", sampling_method="NEAREST", is_missing=False,
        feature_version="caribbean-grid-v2-environment-v1",
    ))
    inputs = _make_inputs(env_rows=tuple(incomplete_rows))
    result = predict_grid(training_result, inputs, grid)
    target = next(
        cell for cell in result.cell_predictions
        if cell.grid_cell_id == cell_id
    )
    assert target.status == "INCOMPLETE_FEATURES"
    assert target.score is None
    assert target.band is None
    assert "bathymetry_neighbor_mean" in target.missing_features


# ---------------------------------------------------------------------------
# 10. Prediction does not write DB rows.
# ---------------------------------------------------------------------------


def test_prediction_does_not_write_db_rows():
    import suitability_prediction_engine as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "db.commit",
        "session.add",
    )
    for token in forbidden:
        assert token not in src, (
            f"prediction engine must not perform DB writes: {token!r}"
        )


# ---------------------------------------------------------------------------
# 11. Prediction does not create SuitabilityDeployment.
# ---------------------------------------------------------------------------


def test_prediction_does_not_create_deployment():
    import suitability_prediction_engine as mod

    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "suitability_deployments",
        "INSERT INTO suitability_deployments",
        "INSERT INTO habitat_suitability_v3_grid_cells",
        "INSERT INTO habitat_suitability_grid_cells",
    )
    for token in forbidden:
        assert token not in src, (
            f"prediction engine must not reference {token!r}"
        )


# ---------------------------------------------------------------------------
# 12. Prediction does not regenerate monitoring-priority artifacts.
# ---------------------------------------------------------------------------


def test_prediction_does_not_regenerate_monitoring_priority():
    import suitability_prediction_engine as mod

    src = open(mod.__file__, "r", encoding="utf-8").read().lower()
    forbidden = (
        "monitoring priority",
        "nextareasnapshotgeneration",
        "next_area_snapshot_generation",
    )
    for token in forbidden:
        assert token not in src, (
            f"prediction engine must not reference {token!r}"
        )


# ---------------------------------------------------------------------------
# 13. Deployment candidate can be created in memory.
# ---------------------------------------------------------------------------


def test_deployment_candidate_can_be_created():
    from suitability_prediction_engine import (
        predict_grid, prepare_deployment_candidate,
    )
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="candidate",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5), 0.1, lambda _i: 0.5
    )
    inputs = _make_inputs(env_rows=env_rows)
    prediction = predict_grid(training_result, inputs, grid)
    candidate = prepare_deployment_candidate(prediction, species_program_id=42)
    assert candidate.species == "Pterois volitans"
    assert candidate.species_program_id == 42
    assert candidate.region_id == 1
    assert candidate.model_version == training_result.model_version


# ---------------------------------------------------------------------------
# 14. Deployment candidate remains non-active.
# ---------------------------------------------------------------------------


def test_deployment_candidate_is_not_active():
    from suitability_prediction_engine import (
        predict_grid, prepare_deployment_candidate,
    )
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="not-active",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5), 0.1, lambda _i: 0.5
    )
    inputs = _make_inputs(env_rows=env_rows)
    prediction = predict_grid(training_result, inputs, grid)
    candidate = prepare_deployment_candidate(prediction, species_program_id=42)
    assert candidate.is_active is False
    assert candidate.status in ("CANDIDATE", "NOT_ACTIVE")
    assert candidate.status != "ACTIVE"


# ---------------------------------------------------------------------------
# 15. Deployment candidate contains dataset provenance.
# ---------------------------------------------------------------------------


def test_deployment_candidate_contains_dataset_provenance():
    from suitability_prediction_engine import (
        predict_grid, prepare_deployment_candidate,
    )
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="provenance",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5), 0.1, lambda _i: 0.5
    )
    inputs = _make_inputs(env_rows=env_rows)
    prediction = predict_grid(training_result, inputs, grid)
    candidate = prepare_deployment_candidate(prediction, species_program_id=42)
    assert "occurrence_dataset_id" in candidate.source_dataset_ids
    assert "environmental_dataset_ids" in candidate.source_dataset_ids
    assert candidate.source_dataset_ids["occurrence_dataset_id"] == 1
    assert 2 in candidate.source_dataset_ids["environmental_dataset_ids"]


# ---------------------------------------------------------------------------
# 16. Artifact hash is carried forward.
# ---------------------------------------------------------------------------


def test_artifact_hash_carried_forward():
    from suitability_prediction_engine import (
        predict_grid, prepare_deployment_candidate,
    )
    from suitability_training_spec import SuitabilityGrid

    training_result = _train_minimal()
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="artifact-hash",
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 18.5), 0.1, lambda _i: 0.5
    )
    inputs = _make_inputs(env_rows=env_rows)
    prediction = predict_grid(training_result, inputs, grid)
    candidate = prepare_deployment_candidate(prediction, species_program_id=42)
    assert prediction.artifact_sha256 is None  # no artifact was written
    # When the artifact_sha256 is None, the candidate must be NOT_ACTIVE
    # with an eligibility reason. This proves the boundary enforces
    # the requirement rather than silently activating.
    assert candidate.status == "NOT_ACTIVE"
    assert "missing_artifact_sha256" in candidate.eligibility_reasons


# ---------------------------------------------------------------------------
# 17. Temporary fixture grid works for a hypothetical second species.
# ---------------------------------------------------------------------------


def test_temporary_grid_works_for_second_species():
    from suitability_prediction_engine import predict_grid
    from suitability_training_engine import train
    from suitability_training_loaders import (
        DatasetProvenanceSummary, SuitabilityTrainingInputs,
    )
    from suitability_training_spec import SuitabilityGrid, SuitabilityTrainingSpec

    class _ProxyDataset:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    summary = DatasetProvenanceSummary(
        id=10, slug="lionfish-occ", name="lionfish-occ", dataset_type="OCCURRENCE",
        status="ACTIVE", geographic_scope_type="REGION",
        region_id=2, jurisdiction_id=None, species_id=2,
        species_program_id=2, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=2,
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    env_summary = DatasetProvenanceSummary(
        id=11, slug="lionfish-env", name="lionfish-env", dataset_type="ENVIRONMENTAL",
        status="ACTIVE", geographic_scope_type="REGION",
        region_id=2, jurisdiction_id=None, species_id=2,
        species_program_id=2, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=0,
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    occ_dataset = _ProxyDataset(
        id=summary.id, slug=summary.slug, name=summary.name,
        dataset_type=summary.dataset_type, status=summary.status,
        geographic_scope_type=summary.geographic_scope_type,
        region_id=summary.region_id, jurisdiction_id=summary.jurisdiction_id,
        species_id=summary.species_id, species_program_id=summary.species_program_id,
        source_name=summary.source_name, source_type=summary.source_type,
        source_reference=summary.source_reference, source_version=summary.source_version,
        retrieved_at=summary.retrieved_at, record_count=summary.record_count,
        artifact_path=summary.artifact_path, artifact_sha256=summary.artifact_sha256,
        notes=summary.notes,
    )
    env_dataset = _ProxyDataset(
        id=env_summary.id, slug=env_summary.slug, name=env_summary.name,
        dataset_type=env_summary.dataset_type, status=env_summary.status,
        geographic_scope_type=env_summary.geographic_scope_type,
        region_id=env_summary.region_id, jurisdiction_id=env_summary.jurisdiction_id,
        species_id=env_summary.species_id, species_program_id=env_summary.species_program_id,
        source_name=env_summary.source_name, source_type=env_summary.source_type,
        source_reference=env_summary.source_reference, source_version=env_summary.source_version,
        retrieved_at=env_summary.retrieved_at, record_count=env_summary.record_count,
        artifact_path=env_summary.artifact_path, artifact_sha256=env_summary.artifact_sha256,
        notes=env_summary.notes,
    )

    occ_rows = tuple(
        _ProxyOcc(
            id=i, scientific_name="Pterois miles", taxon_id=159559,
            latitude=18.0 + i * 2.5,
            longitude=-77.0 + i * 0.0,
            event_date=None, source="test",
            deduplication_key=f"miles-{i}",
            dataset_id=10,
        )
        for i in range(10)
    )
    env_rows = _build_env_features(
        (-78.0, -76.0, 17.5, 43.5), 0.1, lambda _i: 0.5
    )
    inputs = SuitabilityTrainingInputs(
        occurrence_dataset=occ_dataset,
        occurrence_rows=occ_rows,
        environmental_datasets=((env_dataset, env_rows),),
        provenance_summary={"occurrence": summary, "environmental": [env_summary]},
    )
    spec = SuitabilityTrainingSpec(
        species="Pterois miles",
        species_program_id=2,
        geographic_scope="REGION",
        region_id=2,
        jurisdiction_id=None,
        occurrence_dataset_id=10,
        environmental_dataset_ids=(11,),
        random_seed=4242,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        artifact_path=None,
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    training_result = train(spec, inputs, artifact_path=None)

    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.0, -76.0, 17.5, 18.5),
        name="miles-grid",
    )
    prediction = predict_grid(training_result, inputs, grid)
    assert prediction.species == "Pterois miles"
    assert prediction.region_id == 2
    assert prediction.grid["name"] == "miles-grid"


# ---------------------------------------------------------------------------
# 18. Temporary fixture grid works for a hypothetical second jurisdiction.
# ---------------------------------------------------------------------------


def test_temporary_grid_works_for_second_jurisdiction():
    from suitability_prediction_engine import predict_grid
    from suitability_training_engine import train
    from suitability_training_loaders import (
        DatasetProvenanceSummary, SuitabilityTrainingInputs,
    )
    from suitability_training_spec import SuitabilityGrid, SuitabilityTrainingSpec

    class _ProxyDataset:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    summary = DatasetProvenanceSummary(
        id=20, slug="bahamas-occ", name="bahamas-occ", dataset_type="OCCURRENCE",
        status="ACTIVE", geographic_scope_type="JURISDICTION",
        region_id=1, jurisdiction_id=2, species_id=1,
        species_program_id=3, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=10,
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    env_summary = DatasetProvenanceSummary(
        id=21, slug="bahamas-env", name="bahamas-env", dataset_type="ENVIRONMENTAL",
        status="ACTIVE", geographic_scope_type="JURISDICTION",
        region_id=1, jurisdiction_id=2, species_id=1,
        species_program_id=3, source_name="test",
        source_type=None, source_reference=None, source_version=None,
        retrieved_at=None, record_count=0,
        artifact_path=None, artifact_sha256=None, notes=None,
    )
    occ_dataset = _ProxyDataset(
        id=summary.id, slug=summary.slug, name=summary.name,
        dataset_type=summary.dataset_type, status=summary.status,
        geographic_scope_type=summary.geographic_scope_type,
        region_id=summary.region_id, jurisdiction_id=summary.jurisdiction_id,
        species_id=summary.species_id, species_program_id=summary.species_program_id,
        source_name=summary.source_name, source_type=summary.source_type,
        source_reference=summary.source_reference, source_version=summary.source_version,
        retrieved_at=summary.retrieved_at, record_count=summary.record_count,
        artifact_path=summary.artifact_path, artifact_sha256=summary.artifact_sha256,
        notes=summary.notes,
    )
    env_dataset = _ProxyDataset(
        id=env_summary.id, slug=env_summary.slug, name=env_summary.name,
        dataset_type=env_summary.dataset_type, status=env_summary.status,
        geographic_scope_type=env_summary.geographic_scope_type,
        region_id=env_summary.region_id, jurisdiction_id=env_summary.jurisdiction_id,
        species_id=env_summary.species_id, species_program_id=env_summary.species_program_id,
        source_name=env_summary.source_name, source_type=env_summary.source_type,
        source_reference=env_summary.source_reference, source_version=env_summary.source_version,
        retrieved_at=env_summary.retrieved_at, record_count=env_summary.record_count,
        artifact_path=env_summary.artifact_path, artifact_sha256=env_summary.artifact_sha256,
        notes=env_summary.notes,
    )
    occ_rows = tuple(
        _ProxyOcc(
            id=i, scientific_name="Pterois volitans", taxon_id=159559,
            latitude=18.0 + i * 2.5,
            longitude=-77.0 + i * 0.0,
            event_date=None, source="test",
            deduplication_key=f"bah-{i}",
            dataset_id=20,
        )
        for i in range(10)
    )
    # The training background region is the v3 Caribbean extent
    # (lat 9-28). For this hypothetical-jurisdiction test we use
    # presences inside that range so the training engine can
    # synthesize background samples for the same spatial blocks.
    # The jurisdiction identifier is carried by the spec and the
    # prediction result; the prediction grid itself is the
    # jurisdiction-specific surface. The geographic_scope is
    # ``JURISDICTION`` to prove the predictor accepts that variant.
    env_rows = _build_env_features(
        (-78.5, -76.5, 17.5, 43.5), 0.1, lambda _i: 0.5
    )
    inputs = SuitabilityTrainingInputs(
        occurrence_dataset=occ_dataset,
        occurrence_rows=occ_rows,
        environmental_datasets=((env_dataset, env_rows),),
        provenance_summary={"occurrence": summary, "environmental": [env_summary]},
    )
    spec = SuitabilityTrainingSpec(
        species="Pterois volitans",
        species_program_id=3,
        geographic_scope="JURISDICTION",
        region_id=1,
        jurisdiction_id=2,
        occurrence_dataset_id=20,
        environmental_dataset_ids=(21,),
        random_seed=4242,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        artifact_path=None,
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    training_result = train(spec, inputs, artifact_path=None)
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-78.5, -76.5, 17.5, 18.5),
        name="bahamas-grid",
    )
    prediction = predict_grid(training_result, inputs, grid)
    assert prediction.geographic_scope == "JURISDICTION"
    assert prediction.jurisdiction_id == 2
    assert prediction.grid["name"] == "bahamas-grid"


# ---------------------------------------------------------------------------
# 19. Existing Jamaica artifact remains byte-identical.
# ---------------------------------------------------------------------------


def test_existing_jamaica_artifact_unchanged():
    target_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "prediction_models",
        "pterois-volitans-suitability-v3.joblib",
    )
    target_path = os.path.abspath(target_path)
    if not os.path.exists(target_path):
        pytest.skip("Production v3 artifact not present in this environment")
    expected = "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
    with open(target_path, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    assert actual == expected, (
        "Existing v3 artifact SHA must not change as a result of "
        "Phase 10D-4 work"
    )


# ---------------------------------------------------------------------------
# 20. Existing 391 production suitability cells remain unchanged.
# ---------------------------------------------------------------------------


def test_existing_suitability_v3_cells_unchanged():
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )
    db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present in this environment")
    conn = sqlite3.connect(db_path)
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


# ---------------------------------------------------------------------------
# 21. Bahamas remains without suitability deployment.
# ---------------------------------------------------------------------------


def test_bahamas_remains_without_deployment():
    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )
    db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present in this environment")
    conn = sqlite3.connect(db_path)
    try:
        deployments = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert deployments == 0
    finally:
        conn.close()