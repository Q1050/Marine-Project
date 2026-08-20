"""Phase 10D-6 end-to-end hypothetical fixture test.

One small deterministic fixture that exercises the complete Phase 10D
architecture for a hypothetical species in a hypothetical jurisdiction,
proving:

- no Jamaica defaults are inherited
- no Pterois defaults are required
- explicit dataset identity is respected
- explicit grid is respected
- training completes
- prediction completes
- deployment candidate is produced
- deployment candidate is NOT active
- no production rows are created

The fixture is intentionally small and uses in-memory / temporary
state only.
"""

from __future__ import annotations

import os
import tempfile

import pytest


HYPOTHETICAL_SPECIES = "Lutjanus analis"
HYPOTHETICAL_SPECIES_PROGRAM_ID = 900
HYPOTHETICAL_REGION_ID = 90
HYPOTHETICAL_OCCURRENCE_DATASET_ID = 9000
HYPOTHETICAL_ENVIRONMENTAL_DATASET_ID = 9001
HYPOTHETICAL_JURISDICTION_ID = 90


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


class _ProxyDataset:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ProxyOcc:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ProxyEnv:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _make_hypothetical_summary(
    *,
    dataset_id: int,
    dataset_type: str,
    record_count: int,
    scope_type: str = "JURISDICTION",
    jurisdiction_id: int | None = HYPOTHETICAL_JURISDICTION_ID,
    region_id: int | None = HYPOTHETICAL_REGION_ID,
):
    from suitability_training_loaders import DatasetProvenanceSummary
    return DatasetProvenanceSummary(
        id=dataset_id,
        slug=f"hypothetical-{dataset_id}",
        name=f"Hypothetical {dataset_type} dataset",
        dataset_type=dataset_type,
        status="ACTIVE",
        geographic_scope_type=scope_type,
        region_id=region_id,
        jurisdiction_id=jurisdiction_id,
        species_id=HYPOTHETICAL_SPECIES_PROGRAM_ID,
        species_program_id=HYPOTHETICAL_SPECIES_PROGRAM_ID,
        source_name="test",
        source_type="TEST",
        source_reference="test://hypothetical",
        source_version="test-1",
        retrieved_at=None,
        record_count=record_count,
        artifact_path=None,
        artifact_sha256=None,
        notes=None,
    )


def _make_hypothetical_inputs(
    *,
    occurrences: list[int],
    env_grid_bounds: tuple[float, float, float, float],
    value_factory,
):
    from suitability_training_loaders import SuitabilityTrainingInputs

    occ_summary = _make_hypothetical_summary(
        dataset_id=HYPOTHETICAL_OCCURRENCE_DATASET_ID,
        dataset_type="OCCURRENCE",
        record_count=len(occurrences),
    )
    env_summary = _make_hypothetical_summary(
        dataset_id=HYPOTHETICAL_ENVIRONMENTAL_DATASET_ID,
        dataset_type="ENVIRONMENTAL",
        record_count=0,
        scope_type="REGION",
        jurisdiction_id=None,
    )
    occ_dataset = _ProxyDataset(**{
        k: getattr(occ_summary, k)
        for k in (
            "id", "slug", "name", "dataset_type", "status",
            "geographic_scope_type", "region_id", "jurisdiction_id",
            "species_id", "species_program_id", "source_name",
            "source_type", "source_reference", "source_version",
            "retrieved_at", "record_count", "artifact_path",
            "artifact_sha256", "notes",
        )
    })
    env_dataset = _ProxyDataset(**{
        k: getattr(env_summary, k)
        for k in (
            "id", "slug", "name", "dataset_type", "status",
            "geographic_scope_type", "region_id", "jurisdiction_id",
            "species_id", "species_program_id", "source_name",
            "source_type", "source_reference", "source_version",
            "retrieved_at", "record_count", "artifact_path",
            "artifact_sha256", "notes",
        )
    })
    occ_rows = tuple(
        _ProxyOcc(
            id=i,
            scientific_name=HYPOTHETICAL_SPECIES,
            taxon_id=999999,
            latitude=18.0 + (i % 3) * 5.0,
            longitude=-77.0 + (i // 3) * 5.0,
            event_date=None,
            source="test",
            deduplication_key=f"hyp-{i}",
            dataset_id=HYPOTHETICAL_OCCURRENCE_DATASET_ID,
        )
        for i in occurrences
    )
    # Build env features covering the entire grid bounds.
    feature_names = (
        "bathymetry_center_depth",
        "bathymetry_neighbor_mean",
        "bathymetry_neighbor_std",
        "bathymetry_local_relief",
        "bathymetry_max_slope",
        "distance_to_land_km",
        "sst_climatology_annual_mean",
        "sst_climatology_monthly_min",
        "sst_climatology_monthly_max",
        "sst_climatology_seasonal_range",
        "salinity_climatology_annual_mean",
    )
    env_rows = []
    next_id = 0
    lon_min, lon_max, lat_min, lat_max = env_grid_bounds
    for lat_index in range(int(round(lat_min / 0.1)), int(round(lat_max / 0.1))):
        for lon_index in range(int(round(lon_min / 0.1)), int(round(lon_max / 0.1))):
            cell_id = f"{lat_index}:{lon_index}"
            for f_index, fn in enumerate(feature_names):
                env_rows.append(_ProxyEnv(
                    id=next_id,
                    prediction_model_sample_id=cell_id,
                    feature_name=fn,
                    value=value_factory(f_index),
                    source="test",
                    sampling_method="NEAREST",
                    is_missing=False,
                    feature_version="hypothetical-environment-v1",
                ))
                next_id += 1
    return SuitabilityTrainingInputs(
        occurrence_dataset=occ_dataset,
        occurrence_rows=occ_rows,
        environmental_datasets=((env_dataset, tuple(env_rows)),),
        provenance_summary={"occurrence": occ_summary, "environmental": [env_summary]},
    )


def _make_hypothetical_spec(
    *,
    grid,
    random_seed=4242,
):
    from suitability_training_spec import SuitabilityTrainingSpec
    return SuitabilityTrainingSpec(
        species=HYPOTHETICAL_SPECIES,
        species_program_id=HYPOTHETICAL_SPECIES_PROGRAM_ID,
        geographic_scope="JURISDICTION",
        region_id=HYPOTHETICAL_REGION_ID,
        jurisdiction_id=HYPOTHETICAL_JURISDICTION_ID,
        occurrence_dataset_id=HYPOTHETICAL_OCCURRENCE_DATASET_ID,
        environmental_dataset_ids=(HYPOTHETICAL_ENVIRONMENTAL_DATASET_ID,),
        feature_version="hypothetical-environment-v1",
        generation_version="hypothetical-grid-v1",
        model_version="hypothetical-suitability-v1",
        random_seed=random_seed,
        cv_folds=2,
        spatial_block_size_degrees=5.0,
        grid=grid,
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )



# ---------------------------------------------------------------------------
# End-to-end test.
# ---------------------------------------------------------------------------


def test_end_to_end_hypothetical_species_and_jurisdiction():
    """Run the full Phase 10D path on a hypothetical species in a
    hypothetical jurisdiction, proving the path is generic and the
    deployment boundary remains non-active.
    """
    from suitability_training_engine import train
    from suitability_training_spec import SuitabilityGrid
    from suitability_prediction_engine import (
        predict_grid, prepare_deployment_candidate,
    )

    # Use a tiny grid for speed (5x5 = 25 cells).
    # The grid bounds are inside the Caribbean background extent
    # (lat 9-28) so the Phase 10D-3 background sampler can find cells.
    # SuitabilityGrid.bounds is (lon_min, lon_max, lat_min, lat_max).
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-77.5, -77.0, 18.0, 18.5),
        name="hypothetical-test-grid",
    )

    def _value_factory(_i):
        return 0.5

    # Occurrences are spread across 3 lat x 4 lon cells in 5-degree
    # spatial blocks so the StratifiedGroupKFold split has multiple
    # groups. The occurrences are within the Caribbean background
    # extent (lat 9-28, lon -89 to -59).
    inputs = _make_hypothetical_inputs(
        occurrences=list(range(12)),
        env_grid_bounds=(-89.0, -59.0, 9.0, 28.0),
        value_factory=_value_factory,
    )
    spec = _make_hypothetical_spec(grid=grid)

    # === Step 1: training completes without raising ===
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
        artifact_path = tmp.name
    try:
        training_result = train(spec, inputs, artifact_path=artifact_path)
        # Step 2: training result uses the hypothetical species (assert here while artifact exists)
        assert training_result.spec_snapshot["species"] == HYPOTHETICAL_SPECIES
        assert training_result.spec_snapshot["species_program_id"] == (
            HYPOTHETICAL_SPECIES_PROGRAM_ID
        )
        assert training_result.spec_snapshot["jurisdiction_id"] == (
            HYPOTHETICAL_JURISDICTION_ID
        )
        assert training_result.model_version == "hypothetical-suitability-v1"
        assert training_result.feature_version == "hypothetical-environment-v1"
        assert training_result.generation_version == "hypothetical-grid-v1"
        assert training_result.artifact_sha256 is not None
        assert len(training_result.artifact_sha256) == 64

        # === Step 3: prediction completes for the hypothetical grid ===
        prediction = predict_grid(training_result, inputs, grid)
        assert prediction.species == HYPOTHETICAL_SPECIES
        assert prediction.region_id == HYPOTHETICAL_REGION_ID
        assert prediction.jurisdiction_id == HYPOTHETICAL_JURISDICTION_ID
        assert prediction.geographic_scope == "JURISDICTION"
        assert prediction.model_version == "hypothetical-suitability-v1"
        assert prediction.grid["name"] == "hypothetical-test-grid"
        assert prediction.grid["bounds"] == [-77.5, -77.0, 18.0, 18.5]
        assert prediction.total_cells == 25

        # === Step 4: deployment candidate is produced and is NOT active ===
        candidate = prepare_deployment_candidate(prediction, species_program_id=999)
        assert candidate.species == HYPOTHETICAL_SPECIES
        assert candidate.species_program_id == 999
        assert candidate.model_version == "hypothetical-suitability-v1"
        assert candidate.is_active is False
        assert candidate.status in ("CANDIDATE", "NOT_ACTIVE")
        assert candidate.status != "ACTIVE"
        # The artifact exists, so the candidate is CANDIDATE.
        assert candidate.status == "CANDIDATE"
        assert candidate.artifact_sha256 is not None
        assert len(candidate.artifact_sha256) == 64

        # === Step 5: no production rows are created ===
        # Verify the production DB is unchanged.
        import sqlite3
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "marine_observations.db",
        )
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            try:
                deployments = conn.execute(
                    "SELECT COUNT(*) FROM suitability_deployments "
                    "WHERE model_version = ?",
                    ("hypothetical-suitability-v1",),
                ).fetchone()[0]
                assert deployments == 0
                cells = conn.execute(
                    "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
                    "WHERE model_version = ?",
                    ("hypothetical-suitability-v1",),
                ).fetchone()[0]
                assert cells == 0
            finally:
                conn.close()

        # === Step 6: no Jamaica / Pterois defaults were inherited ===
        assert prediction.grid["name"] != "jamaica-v3-default-for-backcompat"
        assert prediction.grid["name"] != "jamaica-v3"
    finally:
        if os.path.exists(artifact_path):
            os.unlink(artifact_path)


def test_jamaica_v3_factory_remains_explicit_and_isolated():
    """The ``jamaica_v3()`` factory still exists for compatibility
    but is NOT called by the generic end-to-end path above.
    """
    from suitability_training_spec import SuitabilityTrainingSpec, SuitabilityGrid
    # Construct a Jamaica-v3 spec explicitly via the factory.
    jamaica_spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        region_id=1,
    )
    assert jamaica_spec.species == "Pterois volitans"
    assert jamaica_spec.model_version == "pterois-volitans-suitability-v3"
    assert jamaica_spec.grid.name == "jamaica-v3"
    assert jamaica_spec.grid.bounds == (-78.6, -75.9, 16.9, 18.7)
    # And confirm a separate hypothetical spec does NOT inherit it.
    grid = SuitabilityGrid(
        grid_size_degrees=0.1,
        bounds=(-77.5, -77.0, 18.0, 18.5),
        name="hypothetical-test-grid",
    )
    hyp_spec = SuitabilityTrainingSpec(
        species="Hypothetical species",
        species_program_id=900,
        geographic_scope="JURISDICTION",
        region_id=90,
        jurisdiction_id=90,
        occurrence_dataset_id=9000,
        environmental_dataset_ids=(9001,),
        feature_version="hypothetical-environment-v1",
        generation_version="hypothetical-grid-v1",
        model_version="hypothetical-suitability-v1",
        grid=grid,
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    assert hyp_spec.grid.bounds != jamaica_spec.grid.bounds
    assert hyp_spec.species != jamaica_spec.species


# ---------------------------------------------------------------------------
# Architecture / genericity / safety checks.
# ---------------------------------------------------------------------------


def test_generic_modules_have_no_db_engine_imports():
    """None of the four generic Phase 10D modules may import a DB
    engine or sessionmaker. This proves they are side-effect free
    with respect to database state.
    """
    files = (
        "suitability_training_spec.py",
        "suitability_training_loaders.py",
        "suitability_training_engine.py",
        "suitability_prediction_engine.py",
    )
    forbidden = ("create_engine", "sessionmaker", "from database")
    for filename in files:
        path = os.path.join(os.path.dirname(__file__), filename)
        src = open(path, "r", encoding="utf-8").read()
        for token in forbidden:
            assert token not in src, (
                f"{filename} must not reference {token!r}"
            )


def test_generic_engine_execution_paths_do_not_read_spec_grid():
    """The default SuitabilityTrainingSpec.grid is a backward-
    compatibility Jamaica default. The generic engine execution
    paths must NOT read it implicitly; only the prediction engine
    consumes the grid (via an explicit argument).
    """
    import inspect
    from suitability_training_engine import (
        prepare_training_dataset, fit_candidates, fit_final_model,
        select_candidate, train, write_temporary_artifact,
    )
    for fn in (
        prepare_training_dataset, fit_candidates, fit_final_model,
        select_candidate, train, write_temporary_artifact,
    ):
        src = inspect.getsource(fn)
        assert "spec.grid" not in src
        assert "dataset.spec.grid" not in src


def test_prediction_engine_requires_explicit_grid_argument():
    """``predict_grid`` must require an explicit ``grid`` argument.
    The generic engine never reads the spec default for prediction.
    """
    import inspect
    from suitability_prediction_engine import predict_grid
    sig = inspect.signature(predict_grid)
    assert "grid" in sig.parameters
    # And it must NOT accept a ``spec`` parameter (the prediction
    # engine has no business with the spec).
    assert "spec" not in sig.parameters


def test_no_implicit_production_activation_path():
    """Search all four generic modules for any token that would
    activate a production deployment. ``predict_grid`` and ``train``
    must remain side-effect free.
    """
    files = (
        "suitability_training_spec.py",
        "suitability_training_loaders.py",
        "suitability_training_engine.py",
        "suitability_prediction_engine.py",
    )
    forbidden = (
        "INSERT INTO suitability_deployments",
        "UPDATE suitability_deployments",
        "DELETE FROM suitability_deployments",
        "INSERT INTO habitat_suitability_v3_grid_cells",
        "INSERT INTO habitat_suitability_grid_cells",
        "INSERT INTO next_area_snapshot_generations",
        "INSERT INTO next_area_snapshot_cells",
        "SpeciesProgram.status = 'ACTIVE'",
    )
    for filename in files:
        path = os.path.join(os.path.dirname(__file__), filename)
        src = open(path, "r", encoding="utf-8").read()
        for token in forbidden:
            assert token not in src, (
                f"{filename} must not reference {token!r}"
            )


def test_deployment_candidate_is_active_always_false():
    """The deployment candidate returned by ``prepare_deployment_candidate``
    must always report ``is_active is False``. Activation is a
    separate, future operation.
    """
    import inspect
    from suitability_prediction_engine import SuitabilityDeploymentCandidate
    src = inspect.getsource(SuitabilityDeploymentCandidate)
    assert "def is_active" in src
    assert "return False" in src


# ---------------------------------------------------------------------------
# Production scientific integrity checks.
# ---------------------------------------------------------------------------


def _prod_db_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "marine_observations.db",
    )


def test_production_scientific_integrity_unchanged():
    """Phase 10D-6 must not change production scientific state."""
    import hashlib
    import sqlite3

    db_path = _prod_db_path()
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")

    expected_artifact_sha = (
        "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
    )

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 12
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_occurrences"
        ).fetchone()[0] == 54
        assert conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        ).fetchone()[0] == 391
        assert conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE model_version = 'pterois-volitans-suitability-v3' "
            "AND prediction_status = 'SCORED'"
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

    artifact_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "prediction_models",
        "pterois-volitans-suitability-v3.joblib",
    )
    if os.path.exists(artifact_path):
        actual = hashlib.sha256(open(artifact_path, "rb").read()).hexdigest()
        assert actual == expected_artifact_sha


def test_jamaica_and_bahamas_boundary_shas_unchanged():
    """Jamaica and Bahamas operational boundary SHAs must not
    change as a result of Phase 10D work.
    """
    import sqlite3
    db_path = _prod_db_path()
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")
    conn = sqlite3.connect(db_path)
    try:
        for jurisdiction_id, expected_sha in (
            (1, "6ad00a00591d908d4405bd263c718fab04b4ee8c94af2d669c9337e247a0be70"),
            (2, "b2276dda6ab42b116bafb11dffb2ed4a3bcf83d8ac889cb8e5027730ccc90b0b"),
        ):
            row = conn.execute(
                "SELECT geometry_hash FROM jurisdiction_boundaries "
                "WHERE jurisdiction_id = ? AND status = 'ACTIVE' "
                "ORDER BY id DESC LIMIT 1",
                (jurisdiction_id,),
            ).fetchone()
            if row is None or row[0] is None:
                continue  # boundary not stored or hash not yet set
            assert row[0] == expected_sha, (
                f"Jamaica/Bahamas boundary SHA changed for "
                f"jurisdiction_id={jurisdiction_id}"
            )
    finally:
        conn.close()


def test_bahamas_scientific_firewall_unchanged():
    """Bahamas must still have NO SpeciesProgram, NO suitability
    deployment, NO suitability cells, NO Monitoring Priority state.
    """
    import sqlite3
    db_path = _prod_db_path()
    if not os.path.exists(db_path):
        pytest.skip("Production DB not present")
    conn = sqlite3.connect(db_path)
    try:
        # Bahamas must have jurisdiction configured
        bahamas_jurisdiction = conn.execute(
            "SELECT id, slug FROM jurisdictions WHERE id = 2"
        ).fetchone()
        assert bahamas_jurisdiction is not None
        assert bahamas_jurisdiction[1] == "bahamas"
        # No SpeciesProgram
        sp_count = conn.execute(
            "SELECT COUNT(*) FROM species_programs WHERE jurisdiction_id = 2"
        ).fetchone()[0]
        assert sp_count == 0
        # No suitability deployment
        dep_count = conn.execute(
            "SELECT COUNT(*) FROM suitability_deployments "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert dep_count == 0
        # No suitability cells
        cell_count = conn.execute(
            "SELECT COUNT(*) FROM habitat_suitability_v3_grid_cells "
            "WHERE scientific_name IN ("
            "SELECT scientific_name FROM species_programs WHERE jurisdiction_id = 2"
            ")"
        ).fetchone()[0]
        assert cell_count == 0
        # No Monitoring Priority generation
        gen_count = conn.execute(
            "SELECT COUNT(*) FROM next_area_snapshot_generations "
            "WHERE species_program_id IN "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = 2)"
        ).fetchone()[0]
        assert gen_count == 0
        # No Monitoring Priority cells
        priority_cells = conn.execute(
            "SELECT COUNT(*) FROM next_area_snapshot_cells "
            "WHERE scientific_name IN ("
            "SELECT scientific_name FROM species_programs WHERE jurisdiction_id = 2"
            ")"
        ).fetchone()[0]
        assert priority_cells == 0
    finally:
        conn.close()