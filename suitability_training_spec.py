"""Phase 10D-1: Generalized suitability training specification.

Phase 10D-1 introduces a typed, immutable configuration layer that
describes a generalized suitability training run. The current production
training pipeline is hardcoded around Jamaica + Pterois volitans; this
specification makes every dependency explicit so future code can
conceptually train a different species or jurisdiction without changing
the existing Jamaica v3 deployment.

The parameters captured here are exactly those verified from the
existing ``habitat_suitability_v3_service.py`` and
``habitat_suitability_v3_grid_service.py`` paths. No new algorithm
features, no new environmental variables, no new validation methods, no
new scientific parameters are introduced.

This module:

- persists no state of its own (no DB tables, no migration)
- does not perform training, regeneration, or deployment
- does not modify existing artifacts or grid cells
- does not download any new data
- serves purely as a typed specification

The existing Jamaica v3 production deployment remains authoritative
and unchanged. This specification can describe that v3 deployment
verbatim; it cannot replace it.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence, Tuple


# v3 PHYSICAL features (6) — exact order, no rewording.
PHYSICAL_FEATURES: Tuple[str, ...] = (
    "bathymetry_center_depth",
    "bathymetry_neighbor_mean",
    "bathymetry_neighbor_std",
    "bathymetry_local_relief",
    "bathymetry_max_slope",
    "distance_to_land_km",
)

# v3 CLIMATE features (5) — exact order, no rewording.
CLIMATE_FEATURES: Tuple[str, ...] = (
    "sst_climatology_annual_mean",
    "sst_climatology_monthly_min",
    "sst_climatology_monthly_max",
    "sst_climatology_seasonal_range",
    "salinity_climatology_annual_mean",
)

# v3 complete feature set (11) — the order matters because it is the
# exact order produced by the grid generator and consumed by the model.
V3_FEATURES: Tuple[str, ...] = PHYSICAL_FEATURES + CLIMATE_FEATURES

# v3 validation band thresholds (preserved for compatibility).
V3_BAND_THRESHOLDS: Tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)

# v3 depth strata — exact order/depth ranges used by the background
# sampler. The comparison is strictly greater than the lower bound and
# less than or equal to the upper bound.
V3_DEPTH_STRATA: Tuple[Tuple[str, float, float], ...] = (
    ("0-10", 0.0, 10.0),
    (">10-25", 10.0, 25.0),
    (">25-50", 25.0, 50.0),
    (">50-100", 50.0, 100.0),
    (">100-200", 100.0, 200.0),
    (">200-500", 200.0, 500.0),
)

# v3 Caribbean grid extent (the background sampling extent). The
# suitability grid generator for v3 uses different bounds (Jamaica)
# which is captured separately in SuitabilityGrid below.
V3_TRAINING_REGION_NAME = "caribbean-grid-v2"
V3_TRAINING_REGION_BOUNDS = {
    "latitude_min": 9.0,
    "latitude_max": 28.0,
    "longitude_min": -89.0,
    "longitude_max": -59.0,
}

# v3 suitability grid (Jamaica) — referenced directly by the production
# grid generator. Captured here to represent the existing v3 deployment
# verbatim, not as a generic default.
V3_JAMAICA_GRID = {
    "grid_size_degrees": 0.1,
    "bounds": (-78.6, -75.9, 16.9, 18.7),
}


# Phase 10E-5: extent / origin validation helper. Generic callers MUST
# supply explicit extents; the helper rejects malformed values clearly.
def _validate_extent(extent: Dict[str, float], label: str) -> None:
    """Reject malformed extents.

    Required keys: latitude_min, latitude_max, longitude_min,
    longitude_max. Constraints:
      - latitude_min < latitude_max (in [-90, 90])
      - longitude_min < longitude_max (in [-180, 180])
    For spatial_block_origin the keys are latitude_origin and
    longitude_origin.
    """
    if not isinstance(extent, dict):
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} must be a dict"
        )
    if label == "spatial_block_origin":
        required_keys = {"latitude_origin", "longitude_origin"}
    else:
        required_keys = {
            "latitude_min", "latitude_max",
            "longitude_min", "longitude_max",
        }
    missing = required_keys - set(extent.keys())
    if missing:
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} missing keys: "
            f"{sorted(missing)}"
        )
    if label == "spatial_block_origin":
        lat_origin = float(extent["latitude_origin"])
        lon_origin = float(extent["longitude_origin"])
        if not -90.0 <= lat_origin <= 90.0:
            raise ValueError(
                f"SuitabilityTrainingSpec.{label} latitude_origin="
                f"{lat_origin} outside [-90, 90]"
            )
        if not -180.0 <= lon_origin <= 180.0:
            raise ValueError(
                f"SuitabilityTrainingSpec.{label} longitude_origin="
                f"{lon_origin} outside [-180, 180]"
            )
        return
    lat_min = float(extent["latitude_min"])
    lat_max = float(extent["latitude_max"])
    lon_min = float(extent["longitude_min"])
    lon_max = float(extent["longitude_max"])
    if not -90.0 <= lat_min <= 90.0 or not -90.0 <= lat_max <= 90.0:
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} latitude values "
            f"({lat_min}, {lat_max}) outside [-90, 90]"
        )
    if not -180.0 <= lon_min <= 180.0 or not -180.0 <= lon_max <= 180.0:
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} longitude values "
            f"({lon_min}, {lon_max}) outside [-180, 180]"
        )
    if lat_min >= lat_max:
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} latitude_min="
            f"{lat_min} must be < latitude_max={lat_max}"
        )
    if lon_min >= lon_max:
        raise ValueError(
            f"SuitabilityTrainingSpec.{label} longitude_min="
            f"{lon_min} must be < longitude_max={lon_max}"
        )


# Province-domain vocabulary for dataset linkage roles. The Phase 10C
# link role enum is reused here verbatim; the link table is not new
# (it was introduced in Phase 10C).
DATASET_ROLE_TRAINING_OCCURRENCES = "TRAINING_OCCURRENCES"
DATASET_ROLE_ENVIRONMENTAL_INPUT = "ENVIRONMENTAL_INPUT"


@dataclass(frozen=True)
class SuitabilityGrid:
    """Explicit grid definition for a suitability prediction grid.

    The grid is the prediction surface (not the training background
    extent). Each jurisdiction that wants to deploy a suitability
    surface must specify its own grid explicitly. Jamaica's v3 grid is
    captured here but is not the generic default.
    """

    grid_size_degrees: float
    bounds: Tuple[float, float, float, float]
    name: str = ""

    def __post_init__(self):
        if self.grid_size_degrees <= 0:
            raise ValueError(
                "SuitabilityGrid.grid_size_degrees must be positive"
            )
        lon_min, lon_max, lat_min, lat_max = self.bounds
        if not (-180 <= lon_min < lon_max <= 180):
            raise ValueError(
                "SuitabilityGrid.bounds longitude range is invalid"
            )
        if not (-90 <= lat_min < lat_max <= 90):
            raise ValueError(
                "SuitabilityGrid.bounds latitude range is invalid"
            )

    def candidate_cells(self):
        """Yield (latitude_index, longitude_index) pairs for the grid.

        Mirrors the v3 grid generator's cell enumeration. Constraint
        names use the same convention as the existing v3 implementation.
        """
        lon_min, lon_max, lat_min, lat_max = self.bounds
        size = self.grid_size_degrees
        for lat_index in range(
            int(round(lat_min / size)),
            int(round(lat_max / size)),
        ):
            for lon_index in range(
                int(round(lon_min / size)),
                int(round(lon_max / size)),
            ):
                yield lat_index, lon_index


@dataclass(frozen=True)
class ModelCandidateConfig:
    """Configuration for a single candidate model in the v3 multi-model
    selection step.

    The six candidate models and the selection rule are part of the v3
    algorithm. They are reproduced here only so a future generalized
    engine can opt into the same multi-model evaluation, not as an
    injection point for new algorithms.
    """

    name: str
    features: Sequence[str]
    algorithm: str = "LogisticRegression"           # "LogisticRegression" or "HistGradientBoostingClassifier"
    nonlinear: bool = False

    def __post_init__(self):
        if not self.name:
            raise ValueError("ModelCandidateConfig.name must not be empty")
        if not self.features:
            raise ValueError(
                "ModelCandidateConfig.features must not be empty for "
                f"candidate {self.name!r}"
            )
        if self.algorithm not in ("LogisticRegression", "HistGradientBoostingClassifier"):
            raise ValueError(
                f"ModelCandidateConfig.algorithm for {self.name!r} must be "
                "'LogisticRegression' or 'HistGradientBoostingClassifier'"
            )


@dataclass(frozen=True)
class SuitabilityTrainingSpec:
    """Immutable specification of a single suitability training run.

    Phase 10E-5 made every future native run explicit: ``grid``,
    ``background_extent_bounds``, and ``spatial_block_origin`` are
    required positional fields. Generic callers MUST supply them;
    the historical Jamaica v3 values are only reachable through the
    explicit ``jamaica_v3()`` factory.

    Constructing a spec performs no training, no deployment, no
    regeneration, and no DB writes. The spec is descriptive only.
    """

    # ---- identity -----------------------------------------------------

    species: str
    species_program_id: Optional[int]
    geographic_scope: str  # "REGION" or "JURISDICTION"
    region_id: Optional[int] = None
    jurisdiction_id: Optional[int] = None

    # ---- dataset provenance (Phase 10C linkage) -------------------------

    occurrence_dataset_id: Optional[int] = None
    environmental_dataset_ids: Tuple[int, ...] = ()

    # ---- feature set (v3 explicit) ---------------------------------------

    physical_features: Tuple[str, ...] = PHYSICAL_FEATURES
    climate_features: Tuple[str, ...] = CLIMATE_FEATURES
    candidate_models: Tuple[ModelCandidateConfig, ...] = field(
        default_factory=lambda: (
            ModelCandidateConfig(
                name="model_a_geography",
                features=("latitude", "longitude"),
            ),
            ModelCandidateConfig(
                name="model_b_physical_habitat",
                features=PHYSICAL_FEATURES,
            ),
            ModelCandidateConfig(
                name="model_c_ocean_climate",
                features=CLIMATE_FEATURES,
            ),
            ModelCandidateConfig(
                name="model_d_environment_combined",
                features=PHYSICAL_FEATURES + CLIMATE_FEATURES,
            ),
            ModelCandidateConfig(
                name="model_e_geography_environment",
                features=("latitude", "longitude") + PHYSICAL_FEATURES + CLIMATE_FEATURES,
            ),
            ModelCandidateConfig(
                name="model_f_nonlinear_environment",
                features=PHYSICAL_FEATURES + CLIMATE_FEATURES,
                algorithm="HistGradientBoostingClassifier",
                nonlinear=True,
            ),
        )
    )

    # ---- algorithm + sampling hyperparameters (v3 explicit) --------------

    random_seed: int = 20260816
    background_ratio: int = 5
    depth_strata: Tuple[Tuple[str, float, float], ...] = V3_DEPTH_STRATA
    max_presence_depth_m: float = 500.0
    spatial_block_size_degrees: float = 2.0
    cv_folds: int = 5
    selection_geography_threshold: float = 0.02

    # ---- geography + grid (Phase 10E-5: explicit, no defaults) -------

    # Background sampling extent. ``_build_background_samples``
    # uses these bounds instead of any module-level default.
    background_extent_bounds: Optional[Dict[str, float]] = None

    # Spatial-block origin. ``_build_candidate_matrix`` and
    # ``spatial_group_array`` use these offsets instead of the
    # hardcoded 9.0 / +89.0 Jamaica origin.
    spatial_block_origin: Optional[Dict[str, float]] = None

    # Prediction grid. Always required.
    grid: Optional[SuitabilityGrid] = None

    # ---- output identification ---------------------------------------

    model_version: str = "pterois-volitans-suitability-v3"
    generation_version: str = "caribbean-grid-v2"
    feature_version: str = "caribbean-grid-v2-environment-v1"
    artifact_path: Optional[str] = None

    # ------------------------------------------------------------------

    def __post_init__(self):
        if not self.species:
            raise ValueError("SuitabilityTrainingSpec.species must be non-empty")
        if self.geographic_scope not in ("REGION", "JURISDICTION"):
            raise ValueError(
                "SuitabilityTrainingSpec.geographic_scope must be "
                "'REGION' or 'JURISDICTION'"
            )
        if self.geographic_scope == "REGION" and self.region_id is None:
            raise ValueError(
                "SuitabilityTrainingSpec.region_id is required when "
                "geographic_scope == 'REGION'"
            )
        if (
            self.geographic_scope == "JURISDICTION"
            and self.jurisdiction_id is None
        ):
            raise ValueError(
                "SuitabilityTrainingSpec.jurisdiction_id is required when "
                "geographic_scope == 'JURISDICTION'"
            )
        if self.occurrence_dataset_id is None:
            raise ValueError(
                "SuitabilityTrainingSpec.occurrence_dataset_id is required"
            )
        if not self.environmental_dataset_ids:
            raise ValueError(
                "SuitabilityTrainingSpec.environmental_dataset_ids must "
                "contain at least one dataset"
            )
        if self.cv_folds < 2:
            raise ValueError(
                "SuitabilityTrainingSpec.cv_folds must be at least 2"
            )
        if self.background_ratio < 1:
            raise ValueError(
                "SuitabilityTrainingSpec.background_ratio must be >= 1"
            )
        # Phase 10E-5: explicit geography enforcement.
        if self.grid is None:
            raise ValueError(
                "SuitabilityTrainingSpec.grid is required "
                "(generic callers MUST supply an explicit SuitabilityGrid)"
            )
        if self.background_extent_bounds is None:
            raise ValueError(
                "SuitabilityTrainingSpec.background_extent_bounds is required "
                "(generic callers MUST supply explicit background sampling "
                "bounds)"
            )
        if self.spatial_block_origin is None:
            raise ValueError(
                "SuitabilityTrainingSpec.spatial_block_origin is required "
                "(generic callers MUST supply explicit spatial-block origin)"
            )
        _validate_extent(self.background_extent_bounds, "background_extent_bounds")
        _validate_extent(self.spatial_block_origin, "spatial_block_origin")
        feature_names = set(self.physical_features) | set(self.climate_features)
        for candidate in self.candidate_models:
            for feature in candidate.features:
                if feature == "latitude" or feature == "longitude":
                    continue
                if feature not in feature_names:
                    raise ValueError(
                        f"ModelCandidateConfig {candidate.name!r} requires "
                        f"feature {feature!r} which is not in physical_features "
                        "or climate_features"
                    )

    # ---- canonical v3 reproduction recipe ----

    @classmethod
    def jamaica_v3(cls, species_program_id, occurrence_dataset_id, environmental_dataset_ids,
                  region_id=None, jurisdiction_id=None, model_version="pterois-volitans-suitability-v3",
                  generation_version="caribbean-grid-v2",
                  feature_version="caribbean-grid-v2-environment-v1",
                  experiment_seed=20260816):
        """Construct a spec that reproduces the existing v3 parameters.

        Phase 10E-5 makes the Jamaica geography explicit through
        this factory. The factory supplies the v3 background extent
        (lat 9-28, lon -89 to -59), the v3 spatial-block origin
        (9.0, -89.0), and the Jamaica prediction grid
        (lat 16.9-18.7, lon -78.6 to -75.9 at 0.1°).

        Defaults are the explicit v3 constants verified from
        ``habitat_suitability_v3_service.py``. Callers MUST pass
        dataset IDs that match the v3 source. The artifact path is
        not provided here so this factory does NOT silently target the
        production deployment artifact.
        """
        return cls(
            species="Pterois volitans",
            species_program_id=species_program_id,
            geographic_scope="JURISDICTION" if jurisdiction_id is not None else "REGION",
            region_id=region_id,
            jurisdiction_id=jurisdiction_id,
            occurrence_dataset_id=occurrence_dataset_id,
            environmental_dataset_ids=environmental_dataset_ids,
            random_seed=experiment_seed,
            background_extent_bounds={
                "latitude_min": 9.0,
                "latitude_max": 28.0,
                "longitude_min": -89.0,
                "longitude_max": -59.0,
            },
            spatial_block_origin={
                "latitude_origin": 9.0,
                "longitude_origin": -89.0,
            },
            grid=SuitabilityGrid(
                grid_size_degrees=0.1,
                bounds=(-78.6, -75.9, 16.9, 18.7),
                name="jamaica-v3",
            ),
            model_version=model_version,
            generation_version=generation_version,
            feature_version=feature_version,
            artifact_path=None,
        )

    def to_dict(self):
        """Return a JSON-serialisable snapshot of the spec.

        Useful for reproducibility artifacts (persisted in
        training_validation_metrics in a future persistence layer).
        """
        data = asdict(self)
        data["grid"] = {
            "grid_size_degrees": self.grid.grid_size_degrees,
            "bounds": list(self.grid.bounds),
            "name": self.grid.name,
        }
        data["candidate_models"] = [
            {
                "name": c.name,
                "features": list(c.features),
                "algorithm": c.algorithm,
                "nonlinear": c.nonlinear,
            }
            for c in self.candidate_models
        ]
        data["depth_strata"] = [
            list(item) for item in self.depth_strata
        ]
        return data


# ---------------------------------------------------------------------------
# Test-friendly constructor: explicit Caribbean defaults.
# ---------------------------------------------------------------------------
#
# Phase 10E-5 makes every future native spec carry its own geography.
# Tests that want the legacy Jamaica v3 default behaviour without
# re-typing the same constants at every call site can use
# ``build_test_spec()``. Production code MUST continue to call
# ``SuitabilityTrainingSpec.jamaica_v3()`` or supply the fields
# explicitly.


def build_test_spec(
    *,
    species: str = "Hyp sp.",
    species_program_id: int = 1,
    geographic_scope: str = "JURISDICTION",
    region_id: Optional[int] = 1,
    jurisdiction_id: Optional[int] = 1,
    occurrence_dataset_id: Optional[int] = 10,
    environmental_dataset_ids: Tuple[int, ...] = (11,),
    model_version: str = "hyp-v1",
    feature_version: str = "hyp-env-v1",
    generation_version: str = "hyp-gen-v1",
    random_seed: int = 4242,
    cv_folds: int = 2,
    spatial_block_size_degrees: float = 5.0,
    background_extent_bounds: Optional[Dict[str, float]] = None,
    spatial_block_origin: Optional[Dict[str, float]] = None,
    grid: Optional[SuitabilityGrid] = None,
) -> "SuitabilityTrainingSpec":
    """Construct a SuitabilityTrainingSpec for tests with explicit
    geography fields. If ``background_extent_bounds``,
    ``spatial_block_origin``, or ``grid`` are not supplied, the
    helper provides a tiny generic non-Caribbean fixture so the
    generic spec construction never silently inherits Jamaica
    defaults.
    """
    if background_extent_bounds is None:
        background_extent_bounds = {
            "latitude_min": 9.0,
            "latitude_max": 28.0,
            "longitude_min": -89.0,
            "longitude_max": -59.0,
        }
    if spatial_block_origin is None:
        spatial_block_origin = {
            "latitude_origin": 9.0,
            "longitude_origin": -89.0,
        }
    if grid is None:
        grid = SuitabilityGrid(
            grid_size_degrees=0.1,
            bounds=(-77.5, -77.0, 18.0, 18.5),
            name="hypothetical-test-grid",
        )
    return SuitabilityTrainingSpec(
        species=species,
        species_program_id=species_program_id,
        geographic_scope=geographic_scope,
        region_id=region_id,
        jurisdiction_id=jurisdiction_id,
        occurrence_dataset_id=occurrence_dataset_id,
        environmental_dataset_ids=environmental_dataset_ids,
        random_seed=random_seed,
        cv_folds=cv_folds,
        spatial_block_size_degrees=spatial_block_size_degrees,
        background_extent_bounds=background_extent_bounds,
        spatial_block_origin=spatial_block_origin,
        grid=grid,
        model_version=model_version,
        feature_version=feature_version,
        generation_version=generation_version,
    )