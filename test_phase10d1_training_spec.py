"""Phase 10D-1: Generalized suitability training specification tests.

Tests cover at minimum:

1. Jamaica + Pterois can be represented explicitly.
2. A hypothetical second species can be represented without creating DB records.
3. A hypothetical second jurisdiction can use a different grid without inheriting Jamaica's grid.
4. Dataset IDs are explicit.
5. Feature configuration is explicit.
6. Random seed/configuration is explicit.
7. Creating the specification performs no training.
8. Creating the specification performs no deployment.
9. Invalid/missing required configuration fails clearly.
10. The existing v3 constants are preserved.
11. The spec is immutable.
12. The spec is idempotent.
13. The spec does not touch the database.
14. The spec survives a round-trip via to_dict.
"""

import dataclasses
import json
import sys
import types

import pytest


# We need to test the module without triggering the heavy BioCLIP ecosystem
# services. The module imports do not pull in BioCLIP, but we make sure we
# can import it directly.
sys.path.insert(0, ".")
from suitability_training_spec import (
    DATASET_ROLE_ENVIRONMENTAL_INPUT,
    DATASET_ROLE_TRAINING_OCCURRENCES,
    PHYSICAL_FEATURES,
    CLIMATE_FEATURES,
    V3_BAND_THRESHOLDS,
    V3_DEPTH_STRATA,
    V3_FEATURES,
    V3_JAMAICA_GRID,
    V3_TRAINING_REGION_BOUNDS,
    ModelCandidateConfig,
    SuitabilityGrid,
    SuitabilityTrainingSpec,
)


# ------------------------------------------------------------------
# 1. Jamaica + Pterois can be represented explicitly.
# ------------------------------------------------------------------

def test_jamaica_pterois_can_be_represented_explicitly():
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    assert spec.species == "Pterois volitans"
    assert spec.geographic_scope == "JURISDICTION"
    assert spec.jurisdiction_id == 1
    assert spec.model_version == "pterois-volitans-suitability-v3"
    assert spec.generation_version == "caribbean-grid-v2"
    assert spec.feature_version == "caribbean-grid-v2-environment-v1"
    assert spec.grid.grid_size_degrees == 0.1
    assert spec.grid.bounds == (-78.6, -75.9, 16.9, 18.7)


# ------------------------------------------------------------------
# 2. A hypothetical second species can be represented without creating DB records.
# ------------------------------------------------------------------

def _minimal_spec_kwargs(**overrides):
    from suitability_training_spec import SuitabilityGrid
    base = {
        "background_extent_bounds": {
            "latitude_min": 9.0,
            "latitude_max": 28.0,
            "longitude_min": -89.0,
            "longitude_max": -59.0,
        },
        "spatial_block_origin": {
            "latitude_origin": 9.0,
            "longitude_origin": -89.0,
        },
        "grid": SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-grid",
        ),
    }
    base.update(overrides)
    return base


def test_hypothetical_second_species_no_db_records():
    spec = SuitabilityTrainingSpec(
        species="Sparisoma viride",
        species_program_id=999,
        geographic_scope="JURISDICTION",
        jurisdiction_id=1,
        occurrence_dataset_id=42,
        environmental_dataset_ids=(43,),
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

    assert spec.species == "Sparisoma viride"
    # The spec must not hold any engine/session reference.
    engine_refs = [
        attr for attr in dir(spec)
        if "engine" in attr.lower() or "session" in attr.lower()
    ]
    assert not engine_refs, (
        f"SuitabilityTrainingSpec must not reference DB engines/sessions, "
        f"found: {engine_refs}"
    )


# ------------------------------------------------------------------
# 3. A hypothetical second jurisdiction can use a different grid.
# ------------------------------------------------------------------

def test_hypothetical_second_jurisdiction_different_grid():
    spec = SuitabilityTrainingSpec(
        species="Pterois volitans",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        jurisdiction_id=2,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        background_extent_bounds={
            "latitude_min": 22.0, "latitude_max": 28.0,
            "longitude_min": -79.0, "longitude_max": -72.0,
        },
         spatial_block_origin={
             "latitude_origin": 22.0, "longitude_origin": -79.0,
         },
         grid=SuitabilityGrid(
             grid_size_degrees=0.1,
             bounds=(-79.0, -72.0, 22.0, 28.0),
             name="bahareas-prototype",
         ),
     )
    assert spec.grid.bounds == (-79.0, -72.0, 22.0, 28.0)
    assert spec.grid.name == "bahareas-prototype"
    # The Jamaica default is NOT used.
    assert spec.grid.bounds != V3_JAMAICA_GRID["bounds"]


# ------------------------------------------------------------------
# 4. Dataset IDs are explicit.
# ------------------------------------------------------------------

def test_dataset_ids_are_explicit():
    spec = SuitabilityTrainingSpec(
        species="Pterois volitans",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        jurisdiction_id=1,
        occurrence_dataset_id=7,
        environmental_dataset_ids=(8, 9),
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

    assert spec.occurrence_dataset_id == 7
    assert spec.environmental_dataset_ids == (8, 9)


# ------------------------------------------------------------------
# 5. Feature configuration is explicit.
# ------------------------------------------------------------------

def test_feature_configuration_is_explicit_and_v3_default():
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    assert spec.physical_features == PHYSICAL_FEATURES
    assert spec.climate_features == CLIMATE_FEATURES
    assert spec.physical_features + spec.climate_features == V3_FEATURES
    assert len(spec.candidate_models) == 6
    names = [c.name for c in spec.candidate_models]
    assert names == [
        "model_a_geography",
        "model_b_physical_habitat",
        "model_c_ocean_climate",
        "model_d_environment_combined",
        "model_e_geography_environment",
        "model_f_nonlinear_environment",
    ]
    # The v3 selection rule is preserved via the configuration
    # attributes (CV folds, block size, depth strata).
    assert spec.cv_folds == 5
    assert spec.spatial_block_size_degrees == 2.0
    assert spec.depth_strata == V3_DEPTH_STRATA
    assert spec.max_presence_depth_m == 500.0
    assert spec.selection_geography_threshold == 0.02
    assert spec.background_ratio == 5


# ------------------------------------------------------------------
# 5b. Custom features override default.

def test_custom_features_override_default():
    spec = SuitabilityTrainingSpec(
        species="X",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        jurisdiction_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        physical_features=("depth",),
        climate_features=("sst_climatology_annual_mean",),
        candidate_models=(
            ModelCandidateConfig(name="model_custom", features=("depth", "sst_climatology_annual_mean")),
        ),
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

    assert spec.physical_features == ("depth",)
    assert spec.climate_features == ("sst_climatology_annual_mean",)


# ------------------------------------------------------------------
# 6. Random seed/configuration is explicit.
# ------------------------------------------------------------------

def test_random_seed_is_explicit():
    spec = SuitabilityTrainingSpec(
        species="X",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        jurisdiction_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        random_seed=424242,
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

    assert spec.random_seed == 424242


# ------------------------------------------------------------------
# 7. Creating the specification performs no training.
# ------------------------------------------------------------------

def test_no_training_performed(monkeypatch):
    """Constructing a spec must never trigger a model fit or DB write.

    The module has no external imports; just constructing instances
    must be safe. We check that no DB engine or session is held by
    inspect.getsourcefile origin.
    """
    monkeypatch.setattr(sys, "modules", dict(sys.modules))
    spec = SuitabilityTrainingSpec(
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    # Module does not reference any DB engine at runtime.
    import suitability_training_spec as mod
    assert "engine" not in mod.__dict__
    assert "session" not in mod.__dict__
    # Spec object must not reference engine/session proxies.
    for attr in dir(spec):
        v = getattr(spec, attr, None)
        if v is None:
            continue
        cls_name = type(v).__name__
        if "Engine" in cls_name or "Session" in cls_name:
            raise AssertionError(
                f"SuitabilityTrainingSpec attribute {attr!r} references "
                f"a DB engine or session: {cls_name}"
            )


# ------------------------------------------------------------------
# 8. Creating the specification performs no deployment.
# ------------------------------------------------------------------

def test_no_deployment_side_effect(monkeypatch):
    """Construction must not touch the SuitabilityDeployment model.

    We do not import api (no DB), but we also verify that no DB
    Session/Engine import exists in the module.
    """
    import suitability_training_spec as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    assert "SuitabilityDeployment" not in src
    assert "create_engine" not in src
    assert "sessionmaker" not in src
    # Construction succeeds without any DB.
    spec = SuitabilityTrainingSpec(
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    assert spec is not None


# ------------------------------------------------------------------
# 9. Invalid/missing required configuration fails clearly.
# ------------------------------------------------------------------

def test_empty_species_rejected():
    with pytest.raises(ValueError, match="species must be non-empty"):
        SuitabilityTrainingSpec(
            species="",
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))



def test_invalid_scope_rejected():
    with pytest.raises(ValueError, match="geographic_scope"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="INVALID",
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))



def test_region_scope_requires_region_id():
    with pytest.raises(ValueError, match="region_id is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="REGION",
            region_id=None,
            jurisdiction_id=None,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
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



def test_jurisdiction_scope_requires_jurisdiction_id():
    with pytest.raises(ValueError, match="jurisdiction_id is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=None,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
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



def test_missing_occurrence_dataset_id_rejected():
    with pytest.raises(ValueError, match="occurrence_dataset_id is required"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=None,
            environmental_dataset_ids=(2,),
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



def test_empty_environmental_dataset_ids_rejected():
    with pytest.raises(ValueError, match="environmental_dataset_ids"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(),
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



def test_unknown_candidate_feature_rejected():
    with pytest.raises(ValueError, match="is not in physical_features"):
        SuitabilityTrainingSpec(
            species="X",
            species_program_id=1,
            geographic_scope="JURISDICTION",
            jurisdiction_id=1,
            occurrence_dataset_id=1,
            environmental_dataset_ids=(2,),
            candidate_models=(
                ModelCandidateConfig(
                    name="model_x_illegal",
                    features=("bogus_feature",),
                ),
            ),
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



# ------------------------------------------------------------------
# 10. V3 constants are preserved.
# ------------------------------------------------------------------

def test_v3_constants_preserved():
    """Explicitly check that v3 source-derived constants are byte-identical
    to what the existing v3 service uses."""
    assert V3_FEATURES == (
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
    assert V3_DEPTH_STRATA == (
        ("0-10", 0.0, 10.0),
        (">10-25", 10.0, 25.0),
        (">25-50", 25.0, 50.0),
        (">50-100", 50.0, 100.0),
        (">100-200", 100.0, 200.0),
        (">200-500", 200.0, 500.0),
    )
    assert V3_BAND_THRESHOLDS == (0.2, 0.4, 0.6, 0.8)


# ------------------------------------------------------------------
# 11. Spec is immutable.
# ------------------------------------------------------------------

def test_spec_is_frozen():
    spec = SuitabilityTrainingSpec(
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.species = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.physical_features = ()


# ------------------------------------------------------------------
# 12. Spec is idempotent.
# ------------------------------------------------------------------

def test_spec_idempotent():
    a = SuitabilityTrainingSpec(
        species="Pterois volitans",
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    b = SuitabilityTrainingSpec(
        species="Pterois volitans",
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
        grid=SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        ))

    assert a == b
    assert a.to_dict() == b.to_dict()


# ------------------------------------------------------------------
# 13. Spec does not touch the database.
# ------------------------------------------------------------------

def test_module_does_not_touch_database():
    import suitability_training_spec as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    forbidden = (
        "Base", "Session", "sessionmaker", "create_engine",
        "db.commit", "db.add", "db.flush",
        "from models import",
        "from database import",
    )
    for token in forbidden:
        assert token not in src, (
            f"suitability_training_spec.py must not mention {token!r}"
        )


# ------------------------------------------------------------------
# 14. Spec survives a round-trip via to_dict.
# ------------------------------------------------------------------

def test_to_dict_round_trip():
    spec = SuitabilityTrainingSpec.jamaica_v3(
        species_program_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        jurisdiction_id=1,
    )
    data = spec.to_dict()
    # Must be JSON-serialisable.
    raw = json.dumps(data, default=str, sort_keys=True)
    parsed = json.loads(raw)
    assert parsed["species"] == "Pterois volitans"
    assert parsed["model_version"] == "pterois-volitans-suitability-v3"
    assert parsed["generation_version"] == "caribbean-grid-v2"
    assert parsed["feature_version"] == "caribbean-grid-v2-environment-v1"
    assert parsed["random_seed"] == 20260816
    assert parsed["background_ratio"] == 5
    assert parsed["cv_folds"] == 5
    assert parsed["spatial_block_size_degrees"] == 2.0
    assert parsed["max_presence_depth_m"] == 500.0
    assert parsed["selection_geography_threshold"] == 0.02
    assert isinstance(parsed["candidate_models"], list)
    assert isinstance(parsed["depth_strata"], list)
    assert isinstance(parsed["grid"], dict)
    assert parsed["grid"]["grid_size_degrees"] == 0.1
    assert parsed["grid"]["bounds"] == [-78.6, -75.9, 16.9, 18.7]


# ------------------------------------------------------------------
# 15. Dataset linkage roles are referenced (Phase 10C integration).
# ------------------------------------------------------------------

def test_role_constants_align_with_phase_10c():
    assert DATASET_ROLE_TRAINING_OCCURRENCES == "TRAINING_OCCURRENCES"
    assert DATASET_ROLE_ENVIRONMENTAL_INPUT == "ENVIRONMENTAL_INPUT"


# ------------------------------------------------------------------
# 16. Grid is a first-class spec object (not a tuple).
# ------------------------------------------------------------------

def test_grid_is_explicit_object():
    spec = SuitabilityTrainingSpec(
        species="X",
        species_program_id=1,
        geographic_scope="JURISDICTION",
        jurisdiction_id=1,
        occurrence_dataset_id=1,
        environmental_dataset_ids=(2,),
        grid=SuitabilityGrid(grid_size_degrees=0.05, bounds=(1.0, 2.0, 3.0, 4.0), name="custom"),
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        }
    )

    assert isinstance(spec.grid, SuitabilityGrid)
    assert spec.grid.name == "custom"
    assert spec.grid.grid_size_degrees == 0.05


# ------------------------------------------------------------------
# 17. ModelCandidateConfig is frozen and explicit.
# ------------------------------------------------------------------

def test_model_candidate_config_is_frozen():
    config = ModelCandidateConfig(
        name="model_test",
        features=("a", "b"),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.name = "x"
    with pytest.raises(Exception):
        ModelCandidateConfig(name="", features=("a",))
    with pytest.raises(Exception):
        ModelCandidateConfig(name="x", features=())
    with pytest.raises(Exception):
        ModelCandidateConfig(
            name="x",
            features=("a",),
            algorithm="NotAnAlgorithm",
        )