"""Phase 10D-5: Jamaica v3 reconstruction / reproducibility audit.

This module implements a READ-ONLY checker that determines how
completely the generalized Phase 10D architecture can reconstruct
the scientific context that produced the existing Jamaica ``Pterois
volitans`` suitability-v3 deployment.

The checker distinguishes three kinds of reproducibility:

- ``CONFIGURATION_RECONSTRUCTION``: can we recover the spec /
  parameters / dataset IDs / artifact hash that the deployment
  claims?
- ``SCIENTIFIC_INPUT_RECONSTRUCTION``: can we recover the exact
  occurrence rows and exact environmental rows used as inputs?
- ``BYTE_IDENTICAL_REPRODUCIBILITY``: can we prove the artifact
  bytes are reproducible?

Each field is labelled with one of the following source
classifications:

- ``PERSISTED``: stored directly in the database / artifact
  metadata.
- ``ARTIFACT_DERIVED``: recoverable directly from the existing
  artifact.
- ``SOURCE_CONFIG``: explicitly represented in current source
  code but not persisted historically.
- ``INFERRED``: logically inferred but not explicitly preserved.
- ``MISSING``: cannot be established safely.

A value being present in current source code does NOT mean it was
historically persisted with the training run. The checker reports
this distinction explicitly.

The checker MUST NOT:
- rewrite the production artifact
- insert or modify any database row
- train a new model
- run grid prediction
- create a SuitabilityDeployment
- create a TrainingRun retroactively
- backfill guessed historical metadata
"""


from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants used by the reconstruction.
# ---------------------------------------------------------------------------


# The artifact SHA-256 of the production v3 deployment. The checker
# reads the artifact file and compares; this constant is the expected
# value (independent of file inspection).
PRODUCTION_V3_ARTIFACT_SHA256 = (
    "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
)

# The expected production occurrence count. The historical v3 cohort
# retained 389 PRESENCE rows after complete-case exclusion; the source
# occurrence dataset contains 54 historical occurrences from which the
# 389 PRESENCE sample rows are derived through the v3 grid-resolution
# process. The 54 historical occurrences feed the v3 grid-resolution
# via the prediction_model_samples generation, not directly as model
# inputs.
EXPECTED_OCCURRENCE_DATASET_SLUG = (
    "pterois-volitans-jamaica-obis-iNaturalist-2025-08"
)
EXPECTED_ENVIRONMENTAL_DATASET_SLUG = (
    "pterois-volitans-environmental-caribbean-grid-v2-environment-v1"
)


# Source-classification constants.

SRC_PERSISTED = "PERSISTED"
SRC_ARTIFACT_DERIVED = "ARTIFACT_DERIVED"
SRC_SOURCE_CONFIG = "SOURCE_CONFIG"
SRC_INFERRED = "INFERRED"
SRC_MISSING = "MISSING"
# MIGRATION_VERIFIED was added in Phase 10E-1. It denotes a value
# that was NOT persisted at the original training time but has been
# retroactively established through a verified Phase 10E migration
# on the existing rows. It must NOT be confused with PERSISTED.
SRC_MIGRATION_VERIFIED = "MIGRATION_VERIFIED"

# Reconstruction-status constants.

STATUS_FULL = "FULL"
STATUS_PARTIAL = "PARTIAL"
STATUS_INSUFFICIENT = "INSUFFICIENT"

STATUS_PROVEN = "PROVEN"
STATUS_NOT_PROVEN = "NOT_PROVEN"
STATUS_IMPOSSIBLE = "IMPOSSIBLE_FROM_CURRENT_PROVENANCE"

OCCURRENCE_EXACTLY = "EXACTLY_RECONSTRUCTABLE"
OCCURRENCE_PARTIALLY = "PARTIALLY_RECONSTRUCTABLE"
OCCURRENCE_NOT = "NOT_RECONSTRUCTABLE"


# ---------------------------------------------------------------------------
# Result structures.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconstructionField:
    """A single reconstruction field and its source classification."""

    field_name: str
    value: Any
    source: str  # one of the SRC_* constants
    notes: str = ""


@dataclass(frozen=True)
class SuitabilityReconstructionReport:
    """Immutable audit report for a Jamaica v3 deployment reconstruction."""

    target_species: str
    target_jurisdiction: str
    target_model_version: str
    artifact_path: str
    artifact_sha256_expected: str
    artifact_sha256_observed: str
    artifact_sha256_matches: bool
    field_entries: Tuple[ReconstructionField, ...]
    occurrence_reconstruction: str  # OCCURRENCE_* constant
    environmental_reconstruction: str  # OCCURRENCE_* constant (reused)
    configuration_reconstruction: str  # STATUS_*
    scientific_input_reconstruction: str  # STATUS_*
    byte_identical_reproducibility: str  # STATUS_*
    gaps: Tuple[str, ...]
    warnings: Tuple[str, ...]
    training_geography: Dict[str, Any]
    prediction_grid: Dict[str, Any]

    @property
    def field_dict(self) -> Dict[str, ReconstructionField]:
        return {entry.field_name: entry for entry in self.field_entries}


# ---------------------------------------------------------------------------
# Database-side helpers.
# ---------------------------------------------------------------------------


def _connect(db_path: Optional[str] = None) -> "sqlite3.Connection":
    """Open the production SQLite DB. Caller closes the connection."""
    import sqlite3

    if db_path is None:
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "marine_observations.db",
        )
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    return sqlite3.connect(db_path)


def _fetch_species_program(conn, scientific_name: str) -> Optional[Dict[str, Any]]:
    """Resolve a SpeciesProgram row joined to its jurisdiction + region."""
    cursor = conn.execute(
        "SELECT sp.id, sp.scientific_name, sp.common_name, sp.status, "
        "sp.species_id, sp.jurisdiction_id, j.name, j.slug, j.country_code, "
        "j.region_id, r.name, r.slug "
        "FROM species_programs sp "
        "JOIN jurisdictions j ON j.id = sp.jurisdiction_id "
        "JOIN regions r ON r.id = j.region_id "
        "WHERE sp.scientific_name = ? "
        "ORDER BY sp.id LIMIT 1",
        (scientific_name,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "species_program_id": row[0],
        "scientific_name": row[1],
        "common_name": row[2],
        "status": row[3],
        "species_id": row[4],
        "jurisdiction_id": row[5],
        "jurisdiction_name": row[6],
        "jurisdiction_slug": row[7],
        "country_code": row[8],
        "region_id": row[9],
        "region_name": row[10],
        "region_slug": row[11],
    }


def _fetch_habitat_suitability_model(
    conn,
    scientific_name: str,
    model_version: str,
) -> Optional[Dict[str, Any]]:
    """Resolve the HabitatSuitabilityModel row.

    Returns the parsed fields plus the parsed validation_metrics_json
    (which carries historical v3 algorithm hyperparameters).
    """
    cursor = conn.execute(
        "SELECT id, model_version, scientific_name, algorithm, "
        "feature_list_json, training_generation_version, "
        "training_sample_count, eligible_presence_count, "
        "eligible_background_count, spatial_block_count, "
        "validation_metrics_json, coefficients_json, artifact_path, "
        "trained_at "
        "FROM habitat_suitability_models WHERE model_version = ? "
        "AND scientific_name = ?",
        (model_version, scientific_name),
    )
    row = cursor.fetchone()
    if not row:
        return None
    try:
        validation = json.loads(row[10])
    except (TypeError, ValueError):
        validation = None
    try:
        feature_list = json.loads(row[4])
    except (TypeError, ValueError):
        feature_list = []
    try:
        coefficients = json.loads(row[11])
    except (TypeError, ValueError):
        coefficients = {}
    return {
        "id": row[0],
        "model_version": row[1],
        "scientific_name": row[2],
        "algorithm": row[3],
        "feature_list": feature_list,
        "training_generation_version": row[5],
        "training_sample_count": row[6],
        "eligible_presence_count": row[7],
        "eligible_background_count": row[8],
        "spatial_block_count": row[9],
        "validation": validation,
        "coefficients": coefficients,
        "artifact_path": row[12],
        "trained_at": row[13],
    }


def _fetch_suitability_deployment(
    conn,
    model_version: str,
    species_program_id: int,
) -> Optional[Dict[str, Any]]:
    """Resolve the SuitabilityDeployment row."""
    cursor = conn.execute(
        "SELECT id, species_program_id, habitat_suitability_model_id, "
        "model_version, status, artifact_hash, generated_at, "
        "activated_at "
        "FROM suitability_deployments WHERE model_version = ? "
        "AND species_program_id = ?",
        (model_version, species_program_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "species_program_id": row[1],
        "habitat_suitability_model_id": row[2],
        "model_version": row[3],
        "status": row[4],
        "artifact_hash": row[5],
        "generated_at": row[6],
        "activated_at": row[7],
    }


def _fetch_scientific_datasets_for_deployment(
    conn,
    deployment_id: int,
) -> List[Dict[str, Any]]:
    """Resolve ScientificDataset rows linked to the deployment via the
    scientific_dataset_deployments join table."""
    cursor = conn.execute(
        "SELECT sd.id, sd.slug, sd.name, sd.dataset_type, sd.status, "
        "sd.geographic_scope_type, sd.region_id, sd.jurisdiction_id, "
        "sd.species_id, sd.species_program_id, sd.source_name, "
        "sd.source_type, sd.source_reference, sd.source_version, "
        "sd.record_count, sd.artifact_sha256, sdd.role "
        "FROM scientific_dataset_deployments sdd "
        "JOIN scientific_datasets sd ON sd.id = sdd.scientific_dataset_id "
        "WHERE sdd.suitability_deployment_id = ? "
        "ORDER BY sd.id",
        (deployment_id,),
    )
    rows = cursor.fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append({
            "id": row[0],
            "slug": row[1],
            "name": row[2],
            "dataset_type": row[3],
            "status": row[4],
            "geographic_scope_type": row[5],
            "region_id": row[6],
            "jurisdiction_id": row[7],
            "species_id": row[8],
            "species_program_id": row[9],
            "source_name": row[10],
            "source_type": row[11],
            "source_reference": row[12],
            "source_version": row[13],
            "record_count": row[14],
            "artifact_sha256": row[15],
            "role": row[16],
        })
    return out


def _fetch_dataset_generation(
    conn,
    generation_version: str,
    scientific_name: str,
) -> Optional[Dict[str, Any]]:
    """Resolve the PredictionModelDatasetGeneration row."""
    cursor = conn.execute(
        "SELECT id, generation_version, generation_seed, "
        "background_ratio, grid_size, training_region, "
        "marine_filter_source, terrestrial_candidates_rejected, "
        "unavailable_candidates_rejected, "
        "presence_candidates_rejected, candidates_evaluated "
        "FROM prediction_model_dataset_generations "
        "WHERE generation_version = ? AND scientific_name = ?",
        (generation_version, scientific_name),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "generation_version": row[1],
        "generation_seed": row[2],
        "background_ratio": row[3],
        "grid_size": row[4],
        "training_region": row[5],
        "marine_filter_source": row[6],
        "terrestrial_candidates_rejected": row[7],
        "unavailable_candidates_rejected": row[8],
        "presence_candidates_rejected": row[9],
        "candidates_evaluated": row[10],
    }


def _fetch_historical_occurrence_count(conn, dataset_id: int) -> int:
    cursor = conn.execute(
        "SELECT COUNT(*) FROM historical_occurrences WHERE dataset_id = ?",
        (dataset_id,),
    )
    return int(cursor.fetchone()[0])


def _fetch_environmental_feature_counts(
    conn,
    feature_version: str,
    scientific_dataset_id: Optional[int] = None,
) -> Dict[str, int]:
    """Count environmental rows by feature_version (and optionally
    by ``scientific_dataset_id`` once Phase 10E-1 has been applied)."""
    if scientific_dataset_id is not None:
        cursor = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT prediction_model_sample_id) "
            "FROM prediction_sample_environmental_features "
            "WHERE feature_version = ? AND scientific_dataset_id = ?",
            (feature_version, scientific_dataset_id),
        )
    else:
        cursor = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT prediction_model_sample_id) "
            "FROM prediction_sample_environmental_features "
            "WHERE feature_version = ?",
            (feature_version,),
        )
    row = cursor.fetchone()
    return {
        "row_count": int(row[0]),
        "sample_count": int(row[1]),
    }


def _has_scientific_dataset_id_column(conn) -> bool:
    cursor = conn.execute(
        "PRAGMA table_info(prediction_sample_environmental_features)"
    )
    return any(row[1] == "scientific_dataset_id" for row in cursor.fetchall())


def _fetch_environmental_ownership(
    conn,
    feature_version: str,
) -> Dict[str, Any]:
    """Return a small dict describing whether the Phase 10E-1
    ownership column is present and what dataset_id is associated
    with the feature_version rows.
    """
    cursor = conn.execute(
        "SELECT COUNT(*) FROM prediction_sample_environmental_features "
        "WHERE feature_version = ? AND scientific_dataset_id IS NULL",
        (feature_version,),
    )
    null_count = int(cursor.fetchone()[0])
    cursor = conn.execute(
        "SELECT scientific_dataset_id, COUNT(*) "
        "FROM prediction_sample_environmental_features "
        "WHERE feature_version = ? AND scientific_dataset_id IS NOT NULL "
        "GROUP BY scientific_dataset_id",
        (feature_version,),
    )
    ownership_rows = cursor.fetchall()
    return {
        "null_count": null_count,
        "dataset_id_counts": [
            {"dataset_id": int(row[0]), "row_count": int(row[1])}
            for row in ownership_rows
        ],
    }


def _fetch_scientific_dataset_by_id(
    conn,
    dataset_id: int,
) -> Optional[Dict[str, Any]]:
    cursor = conn.execute(
        "SELECT id, slug, name, dataset_type, status, "
        "geographic_scope_type, region_id, jurisdiction_id, "
        "species_id, species_program_id, source_name, "
        "source_type, source_reference, source_version, "
        "record_count, artifact_sha256 "
        "FROM scientific_datasets WHERE id = ?",
        (dataset_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "slug": row[1],
        "name": row[2],
        "dataset_type": row[3],
        "status": row[4],
        "geographic_scope_type": row[5],
        "region_id": row[6],
        "jurisdiction_id": row[7],
        "species_id": row[8],
        "species_program_id": row[9],
        "source_name": row[10],
        "source_type": row[11],
        "source_reference": row[12],
        "source_version": row[13],
        "record_count": row[14],
        "artifact_sha256": row[15],
    }


# ---------------------------------------------------------------------------
# Artifact-side helpers.
# ---------------------------------------------------------------------------


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_artifact(path: str) -> Dict[str, Any]:
    """Return safe metadata extracted from the artifact.

    Inspects only attributes that the existing artifact provably
    exposes. Does not rewrite the artifact.
    """
    try:
        import joblib
    except ImportError:
        return {"available": False, "reason": "joblib not importable"}
    model = joblib.load(path)
    info: Dict[str, Any] = {
        "available": True,
        "estimator_type": type(model).__name__,
        "n_features_in_": getattr(model, "n_features_in_", None),
        "random_state": getattr(model, "random_state", None),
        "classes_": list(getattr(model, "classes_", [])),
        "has_feature_names_in_": hasattr(model, "feature_names_in_"),
    }
    if info["has_feature_names_in_"]:
        info["feature_names_in_"] = list(model.feature_names_in_)
    for attr in ("max_iter", "learning_rate", "max_leaf_nodes",
                 "min_samples_leaf", "l2_regularization", "loss",
                 "max_depth", "class_weight", "n_iter_"):
        if hasattr(model, attr):
            info[attr] = getattr(model, attr)
    return info


# ---------------------------------------------------------------------------
# Spec-reconstruction constants.
# ---------------------------------------------------------------------------


# Constants for the v3 training extent (lat 9-28, lon -89 to -59).
# These are SOURCE_CONFIG (declared in current compatibility code,
# not persisted historically with the training run).
V3_TRAINING_LATITUDE_MIN = 9.0
V3_TRAINING_LATITUDE_MAX = 28.0
V3_TRAINING_LONGITUDE_MIN = -89.0
V3_TRAINING_LONGITUDE_MAX = -59.0

# Constants for the Jamaica prediction grid. These are SOURCE_CONFIG.
V3_JAMAICA_GRID_BOUNDS = (-78.6, -75.9, 16.9, 18.7)
V3_JAMAICA_GRID_SIZE_DEGREES = 0.1

# The v3 algorithm hyperparameters. SOURCE_CONFIG: declared in
# habitat_suitability_v3_service.py. The artifact stores the fitted
# result of these hyperparameters; the hyperparameters themselves
# are NOT persisted with the run.
V3_LOGISTIC_HYPERPARAMETERS = {
    "class_weight": "balanced",
    "max_iter": 1000,
    "scaler": "StandardScaler",
    "estimator_family": "LogisticRegression",
}

V3_NONLINEAR_HYPERPARAMETERS = {
    "estimator_family": "HistGradientBoostingClassifier",
    "learning_rate": 0.08,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "l2_regularization": 1.0,
}

# The six v3 candidate definitions and their feature subsets.
# SOURCE_CONFIG: declared in habitat_suitability_v3_service.py.
V3_CANDIDATE_MODELS: Dict[str, List[str]] = {
    "model_a_geography": ["latitude", "longitude"],
    "model_b_physical_habitat": [
        "bathymetry_center_depth",
        "bathymetry_neighbor_mean",
        "bathymetry_neighbor_std",
        "bathymetry_local_relief",
        "bathymetry_max_slope",
        "distance_to_land_km",
    ],
    "model_c_ocean_climate": [
        "sst_climatology_annual_mean",
        "sst_climatology_monthly_min",
        "sst_climatology_monthly_max",
        "sst_climatology_seasonal_range",
        "salinity_climatology_annual_mean",
    ],
    "model_d_environment_combined": [
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
    ],
    "model_e_geography_environment": [
        "latitude", "longitude",
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
    ],
    "model_f_nonlinear_environment": [
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
    ],
}

V3_SELECTION_RULE_TEXT = (
    "Prefer the stronger environment-only model unless geography+environment "
    "improves both mean ROC AUC and mean average precision by more than 0.02."
)
V3_SELECTION_GEOGRAPHY_THRESHOLD = 0.02

# The v3 spatial block is 2 degrees (per the v3 service code and per
# the validation_metrics_json ``spatial_validation.block_size_degrees``).
V3_SPATIAL_BLOCK_DEGREES = 2.0
V3_CV_FOLDS = 5

# Depth strata and max depth. SOURCE_CONFIG.
V3_DEPTH_STRATA = (
    ("0-10", 0.0, 10.0),
    (">10-25", 10.0, 25.0),
    (">25-50", 25.0, 50.0),
    (">50-100", 50.0, 100.0),
    (">100-200", 100.0, 200.0),
    (">200-500", 200.0, 500.0),
)
V3_MAX_PRESENCE_DEPTH_M = 500.0

# Suitability band thresholds.
SUITABILITY_BAND_THRESHOLDS = (0.2, 0.4, 0.6, 0.8)


# ---------------------------------------------------------------------------
# Reconstruction entry point.
# ---------------------------------------------------------------------------


def reconstruct_jamaica_v3(
    db_path: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> SuitabilityReconstructionReport:
    """Run the Jamaica v3 reconstruction audit.

    Performs only SELECT queries against the database and a single
    joblib.load on the existing artifact. Does not mutate any state.
    """
    scientific_name = "Pterois volitans"
    model_version = "pterois-volitans-suitability-v3"

    conn = _connect(db_path)
    try:
        species_program = _fetch_species_program(conn, scientific_name)
        if species_program is None:
            raise ValueError(
                f"SpeciesProgram not found for {scientific_name!r}"
            )

        habitat_model = _fetch_habitat_suitability_model(
            conn, scientific_name, model_version,
        )
        if habitat_model is None:
            raise ValueError(
                f"HabitatSuitabilityModel not found for {model_version!r}"
            )

        deployment = _fetch_suitability_deployment(
            conn, model_version, species_program["species_program_id"],
        )
        if deployment is None:
            raise ValueError(
                "SuitabilityDeployment not found for "
                f"{model_version!r} on SpeciesProgram "
                f"{species_program['species_program_id']}"
            )

        scientific_datasets = _fetch_scientific_datasets_for_deployment(
            conn, deployment["id"],
        )

        occurrence_dataset = next(
            (
                row for row in scientific_datasets
                if row["role"] == "TRAINING_OCCURRENCES"
            ),
            None,
        )
        environmental_dataset = next(
            (
                row for row in scientific_datasets
                if row["role"] == "ENVIRONMENTAL_INPUT"
            ),
            None,
        )

        dataset_generation = _fetch_dataset_generation(
            conn,
            habitat_model["training_generation_version"],
            scientific_name,
        )

        occurrence_count = (
            _fetch_historical_occurrence_count(conn, occurrence_dataset["id"])
            if occurrence_dataset is not None
            else 0
        )
        # Determine whether Phase 10E-1 migration has been applied.
        ownership_column_present = _has_scientific_dataset_id_column(conn)
        if habitat_model.get("validation") and environmental_dataset is not None:
            if ownership_column_present:
                environmental_counts = _fetch_environmental_feature_counts(
                    conn,
                    habitat_model["validation"]["feature_version"],
                    scientific_dataset_id=environmental_dataset["id"],
                )
                environmental_ownership = _fetch_environmental_ownership(
                    conn,
                    habitat_model["validation"]["feature_version"],
                )
            else:
                environmental_counts = _fetch_environmental_feature_counts(
                    conn,
                    habitat_model["validation"]["feature_version"],
                )
                environmental_ownership = None
        else:
            environmental_counts = {}
            environmental_ownership = None
    finally:
        conn.close()

    # Artifact inspection (without rewrite).
    if artifact_path is None:
        artifact_path = habitat_model["artifact_path"]
    artifact_sha_observed = _sha256(artifact_path)
    artifact_info = _inspect_artifact(artifact_path)

    # ------------------------------------------------------------------
    # Field-by-field reconstruction entries.
    # ------------------------------------------------------------------

    entries: List[ReconstructionField] = []

    entries.append(ReconstructionField(
        field_name="canonical_species",
        value=scientific_name,
        source=SRC_PERSISTED,
        notes="species_programs.scientific_name",
    ))
    entries.append(ReconstructionField(
        field_name="species_program_id",
        value=species_program["species_program_id"],
        source=SRC_PERSISTED,
        notes="species_programs.id",
    ))
    entries.append(ReconstructionField(
        field_name="jurisdiction",
        value=species_program["jurisdiction_name"],
        source=SRC_PERSISTED,
        notes=f"jurisdiction_id={species_program['jurisdiction_id']}",
    ))
    entries.append(ReconstructionField(
        field_name="region",
        value=species_program["region_name"],
        source=SRC_PERSISTED,
        notes=f"region_id={species_program['region_id']}",
    ))

    if occurrence_dataset is not None:
        entries.append(ReconstructionField(
            field_name="occurrence_scientific_dataset_id",
            value=occurrence_dataset["id"],
            source=SRC_PERSISTED,
            notes="scientific_datasets.id linked via scientific_dataset_deployments.role=TRAINING_OCCURRENCES",
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_scientific_dataset_slug",
            value=occurrence_dataset["slug"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_geographic_ownership",
            value=occurrence_dataset["geographic_scope_type"],
            source=SRC_PERSISTED,
            notes=(
                f"region_id={occurrence_dataset['region_id']} "
                f"jurisdiction_id={occurrence_dataset['jurisdiction_id']}"
            ),
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_species_ownership",
            value=occurrence_dataset["species_id"],
            source=SRC_PERSISTED,
            notes="scientific_datasets.species_id",
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_source_reference",
            value=occurrence_dataset["source_reference"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_source_version",
            value=occurrence_dataset["source_version"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_record_count_dataset",
            value=occurrence_dataset["record_count"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="occurrence_artifact_sha256",
            value=occurrence_dataset["artifact_sha256"],
            source=SRC_PERSISTED,
            notes="scientific_datasets.artifact_sha256 (NULL in production)",
        ))
        entries.append(ReconstructionField(
            field_name="historical_occurrence_rows_resolved",
            value=occurrence_count,
            source=SRC_PERSISTED,
            notes=(
                "count of historical_occurrences rows with dataset_id="
                f"{occurrence_dataset['id']}"
            ),
        ))
    else:
        for field_name in (
            "occurrence_scientific_dataset_id",
            "occurrence_scientific_dataset_slug",
            "occurrence_geographic_ownership",
            "occurrence_species_ownership",
            "occurrence_source_reference",
            "occurrence_source_version",
            "occurrence_record_count_dataset",
            "occurrence_artifact_sha256",
            "historical_occurrence_rows_resolved",
        ):
            entries.append(ReconstructionField(
                field_name=field_name,
                value=None,
                source=SRC_MISSING,
                notes="scientific_dataset_deployments has no TRAINING_OCCURRENCES row",
            ))

    if environmental_dataset is not None:
        entries.append(ReconstructionField(
            field_name="environmental_scientific_dataset_id",
            value=environmental_dataset["id"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="environmental_scientific_dataset_slug",
            value=environmental_dataset["slug"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="environmental_geographic_ownership",
            value=environmental_dataset["geographic_scope_type"],
            source=SRC_PERSISTED,
            notes=(
                f"region_id={environmental_dataset['region_id']} "
                f"jurisdiction_id={environmental_dataset['jurisdiction_id']}"
            ),
        ))
        entries.append(ReconstructionField(
            field_name="environmental_source_reference",
            value=environmental_dataset["source_reference"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="environmental_source_version",
            value=environmental_dataset["source_version"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="environmental_record_count_dataset",
            value=environmental_dataset["record_count"],
            source=SRC_PERSISTED,
        ))
        entries.append(ReconstructionField(
            field_name="environmental_feature_version",
            value=(
                habitat_model["validation"]["feature_version"]
                if habitat_model.get("validation") else None
            ),
            source=SRC_PERSISTED,
            notes="validation_metrics_json.feature_version",
        ))
        entries.append(ReconstructionField(
            field_name="environmental_feature_rows_total",
            value=environmental_counts.get("row_count"),
            source=SRC_PERSISTED,
            notes=(
                "count of prediction_sample_environmental_features rows with "
                "feature_version matching the validation_metrics_json.feature_version"
            ),
        ))
        entries.append(ReconstructionField(
            field_name="environmental_feature_samples_total",
            value=environmental_counts.get("sample_count"),
            source=SRC_PERSISTED,
            notes="distinct prediction_model_sample_id values",
        ))
        entries.append(ReconstructionField(
            field_name="environmental_dataset_row_ownership",
            value=environmental_dataset["id"] if environmental_ownership
            and environmental_ownership.get("null_count", -1) == 0
            and len(environmental_ownership.get("dataset_id_counts", [])) == 1
            and environmental_ownership["dataset_id_counts"][0]["dataset_id"]
            == environmental_dataset["id"]
            else (
                environmental_ownership["dataset_id_counts"][0]["dataset_id"]
                if environmental_ownership
                and environmental_ownership.get("null_count", -1) == 0
                and len(environmental_ownership.get("dataset_id_counts", [])) >= 1
                else None
            ),
            source=(
                SRC_MIGRATION_VERIFIED
                if environmental_ownership is not None
                and environmental_ownership.get("null_count", -1) == 0
                and len(environmental_ownership.get("dataset_id_counts", [])) >= 1
                else SRC_MISSING
            ),
            notes=(
                "Phase 10E-1 retroactive ownership. The "
                "scientific_dataset_id FK was NOT persisted at the "
                "original 2026-08-16 training time; it was retroactively "
                "established by the Phase 10E-1 migration using the "
                "scientific_dataset_deployments.role='ENVIRONMENTAL_INPUT' "
                "link and the slug-feature_version correspondence. The "
                "scientific feature values are byte-identical before and "
                "after the migration; only the ownership metadata changed. "
                "MIGRATION_VERIFIED must NOT be confused with PERSISTED."
            )
            if environmental_ownership is not None
            and environmental_ownership.get("null_count", -1) == 0
            else (
                "prediction_sample_environmental_features does NOT have a "
                "scientific_dataset_id foreign key. Rows are selected by "
                "feature_version, which is ambiguous across datasets. "
                "Historical per-dataset ownership cannot be proven."
            ),
        ))
    else:
        for field_name in (
            "environmental_scientific_dataset_id",
            "environmental_scientific_dataset_slug",
            "environmental_geographic_ownership",
            "environmental_source_reference",
            "environmental_source_version",
            "environmental_record_count_dataset",
            "environmental_feature_version",
            "environmental_feature_rows_total",
            "environmental_feature_samples_total",
            "environmental_dataset_row_ownership",
        ):
            entries.append(ReconstructionField(
                field_name=field_name,
                value=None,
                source=SRC_MISSING,
                notes="scientific_dataset_deployments has no ENVIRONMENTAL_INPUT row",
            ))

    entries.append(ReconstructionField(
        field_name="feature_list",
        value=tuple(habitat_model["feature_list"]),
        source=SRC_PERSISTED,
        notes="habitat_suitability_models.feature_list_json",
    ))
    entries.append(ReconstructionField(
        field_name="feature_version",
        value=(
            habitat_model["validation"]["feature_version"]
            if habitat_model.get("validation") else None
        ),
        source=SRC_PERSISTED,
        notes="validation_metrics_json.feature_version",
    ))
    entries.append(ReconstructionField(
        field_name="model_version",
        value=habitat_model["model_version"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="generation_version",
        value=habitat_model["training_generation_version"],
        source=SRC_PERSISTED,
        notes="habitat_suitability_models.training_generation_version",
    ))

    # Candidate models: SOURCE_CONFIG. We expose them as a known
    # reference but do not pretend the run persisted them.
    entries.append(ReconstructionField(
        field_name="candidate_models",
        value=V3_CANDIDATE_MODELS,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in habitat_suitability_v3_service.GROUPS. Not "
            "persisted as a separate historical record. Selected "
            "candidate name is persisted via the validation_metrics_json."
        ),
    ))

    if habitat_model.get("validation") and "selection" in habitat_model["validation"]:
        entries.append(ReconstructionField(
            field_name="selected_candidate",
            value=habitat_model["validation"]["selection"].get("selected_model"),
            source=SRC_PERSISTED,
            notes="validation_metrics_json.selection.selected_model",
        ))
    else:
        entries.append(ReconstructionField(
            field_name="selected_candidate",
            value=None,
            source=SRC_MISSING,
            notes="validation_metrics_json.selection not present",
        ))

    entries.append(ReconstructionField(
        field_name="algorithm",
        value=habitat_model["algorithm"],
        source=SRC_PERSISTED,
        notes="habitat_suitability_models.algorithm",
    ))

    # Logistic hyperparameters: SOURCE_CONFIG (declared in v3 service).
    entries.append(ReconstructionField(
        field_name="logistic_hyperparameters",
        value=V3_LOGISTIC_HYPERPARAMETERS,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in habitat_suitability_v3_service.HabitatSuitabilityV3Service._logistic. "
            "Not persisted with the training run."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="nonlinear_hyperparameters",
        value=V3_NONLINEAR_HYPERPARAMETERS,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in habitat_suitability_v3_service.HabitatSuitabilityV3Service._nonlinear. "
            "Not persisted with the training run. The fitted hyperparameters "
            "are recoverable from the artifact for the selected estimator only."
        ),
    ))
    if artifact_info.get("available"):
        entries.append(ReconstructionField(
            field_name="artifact_random_state",
            value=artifact_info.get("random_state"),
            source=SRC_ARTIFACT_DERIVED,
            notes="artifact random_state attribute",
        ))
        entries.append(ReconstructionField(
            field_name="artifact_n_features_in_",
            value=artifact_info.get("n_features_in_"),
            source=SRC_ARTIFACT_DERIVED,
        ))
        entries.append(ReconstructionField(
            field_name="artifact_hyperparameters",
            value={
                key: artifact_info.get(key)
                for key in (
                    "max_iter", "learning_rate", "max_leaf_nodes",
                    "min_samples_leaf", "l2_regularization", "loss",
                    "max_depth", "class_weight", "n_iter_",
                )
                if artifact_info.get(key) is not None
            },
            source=SRC_ARTIFACT_DERIVED,
            notes="fitted estimator hyperparameters",
        ))
        entries.append(ReconstructionField(
            field_name="artifact_feature_names_embedded",
            value=artifact_info.get("has_feature_names_in_"),
            source=SRC_ARTIFACT_DERIVED,
            notes=(
                "Whether the artifact exposes feature_names_in_. The v3 "
                "artifact does not embed the feature name list."
            ),
        ))
    else:
        for name in (
            "artifact_random_state",
            "artifact_n_features_in_",
            "artifact_hyperparameters",
            "artifact_feature_names_embedded",
        ):
            entries.append(ReconstructionField(
                field_name=name,
                value=None,
                source=SRC_MISSING,
                notes="artifact not available for inspection",
            ))

    # Random seed: SOURCE_CONFIG (in current source). Also recoverable
    # from the artifact for the selected estimator (ARTIFACT_DERIVED).
    # We label the seed itself as SOURCE_CONFIG; the artifact's
    # random_state is ARTIFACT_DERIVED.
    entries.append(ReconstructionField(
        field_name="random_seed",
        value=20260816,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared as SEED in habitat_suitability_v3_service.py and "
            "matching prediction_model_dataset_v2_service.SEED. The "
            "training run did not persist a TrainingRun record with the "
            "seed, but the artifact's random_state is equal to 20260816."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="background_ratio",
        value=(
            dataset_generation["background_ratio"]
            if dataset_generation is not None else None
        ),
        source=SRC_PERSISTED if dataset_generation is not None else SRC_MISSING,
        notes=(
            "prediction_model_dataset_generations.background_ratio for "
            f"generation_version={habitat_model['training_generation_version']}"
        ),
    ))
    entries.append(ReconstructionField(
        field_name="depth_strata",
        value=V3_DEPTH_STRATA,
        source=SRC_SOURCE_CONFIG,
        notes="Declared in prediction_model_dataset_v2_service.DEPTH_STRATA.",
    ))
    entries.append(ReconstructionField(
        field_name="max_presence_depth_m",
        value=V3_MAX_PRESENCE_DEPTH_M,
        source=SRC_SOURCE_CONFIG,
        notes="Declared in prediction_model_dataset_v2_service.MAX_DEPTH.",
    ))
    entries.append(ReconstructionField(
        field_name="spatial_block_size_degrees",
        value=(
            habitat_model["validation"]["spatial_validation"]["block_size_degrees"]
            if habitat_model.get("validation") else V3_SPATIAL_BLOCK_DEGREES
        ),
        source=(
            SRC_PERSISTED if habitat_model.get("validation") else SRC_SOURCE_CONFIG
        ),
        notes=(
            "validation_metrics_json.spatial_validation.block_size_degrees "
            "OR the SOURCE_CONFIG default 2.0 from habitat_suitability_v3_service."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="cv_folds",
        value=(
            habitat_model["validation"]["spatial_validation"]["fold_count"]
            if habitat_model.get("validation") else V3_CV_FOLDS
        ),
        source=(
            SRC_PERSISTED if habitat_model.get("validation") else SRC_SOURCE_CONFIG
        ),
        notes=(
            "validation_metrics_json.spatial_validation.fold_count OR "
            "the SOURCE_CONFIG default 5 from habitat_suitability_v3_service."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="selection_geography_threshold",
        value=V3_SELECTION_GEOGRAPHY_THRESHOLD,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in habitat_suitability_v3_service._select_candidate. "
            "Not persisted as a separate field. The validation_metrics_json "
            "selection payload reports whether geography_material_improvement "
            "was true/false."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="selection_rule_text",
        value=V3_SELECTION_RULE_TEXT,
        source=SRC_SOURCE_CONFIG,
    ))
    entries.append(ReconstructionField(
        field_name="geography_material_improvement",
        value=(
            habitat_model["validation"]["selection"].get(
                "geography_material_improvement"
            )
            if habitat_model.get("validation") else None
        ),
        source=(
            SRC_PERSISTED if habitat_model.get("validation") else SRC_MISSING
        ),
        notes="validation_metrics_json.selection.geography_material_improvement",
    ))

    entries.append(ReconstructionField(
        field_name="training_geography_bounds",
        value={
            "latitude_min": V3_TRAINING_LATITUDE_MIN,
            "latitude_max": V3_TRAINING_LATITUDE_MAX,
            "longitude_min": V3_TRAINING_LONGITUDE_MIN,
            "longitude_max": V3_TRAINING_LONGITUDE_MAX,
        },
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in prediction_model_dataset_v2_service.LATITUDE_MIN/MAX "
            "and LONGITUDE_MIN/MAX. Not stored on the deployment."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="training_grid_size_degrees",
        value=(
            dataset_generation["grid_size"]
            if dataset_generation is not None else None
        ),
        source=(
            SRC_PERSISTED if dataset_generation is not None else SRC_MISSING
        ),
        notes=(
            "prediction_model_dataset_generations.grid_size for "
            f"generation_version={habitat_model['training_generation_version']}"
        ),
    ))
    entries.append(ReconstructionField(
        field_name="training_seed_persisted",
        value=(
            dataset_generation["generation_seed"]
            if dataset_generation is not None else None
        ),
        source=(
            SRC_PERSISTED if dataset_generation is not None else SRC_MISSING
        ),
        notes="prediction_model_dataset_generations.generation_seed",
    ))
    entries.append(ReconstructionField(
        field_name="training_region_name",
        value=(
            dataset_generation["training_region"]
            if dataset_generation is not None else None
        ),
        source=(
            SRC_PERSISTED if dataset_generation is not None else SRC_MISSING
        ),
        notes="prediction_model_dataset_generations.training_region",
    ))
    entries.append(ReconstructionField(
        field_name="training_candidates_evaluated",
        value=(
            dataset_generation["candidates_evaluated"]
            if dataset_generation is not None else None
        ),
        source=(
            SRC_PERSISTED if dataset_generation is not None else SRC_MISSING
        ),
    ))

    entries.append(ReconstructionField(
        field_name="prediction_grid_bounds",
        value=list(V3_JAMAICA_GRID_BOUNDS),
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared as JAMAICA_BOUNDS in habitat_suitability_service.py "
            "and used by habitat_suitability_v3_grid_service.py. Not "
            "persisted on the deployment."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="prediction_grid_size_degrees",
        value=V3_JAMAICA_GRID_SIZE_DEGREES,
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared as GRID_SIZE in habitat_suitability_service.py. "
            "The actual stored cells use the same 0.1 degrees; the "
            "value is not persisted on the deployment."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="prediction_grid_cell_count",
        value=(
            habitat_model["validation"]["spatial_validation"].get(
                "spatial_group_count"
            )
            if habitat_model.get("validation") else None
        ),
        source=(
            SRC_PERSISTED if habitat_model.get("validation") else SRC_MISSING
        ),
        notes=(
            "validation_metrics_json.spatial_validation.spatial_group_count "
            "carries the count of spatial groups in the training cohort, "
            "not the count of Jamaica prediction cells. The production "
            "habitat_suitability_v3_grid_cells table holds 391 cells."
        ),
    ))
    entries.append(ReconstructionField(
        field_name="suitability_band_thresholds",
        value=list(SUITABILITY_BAND_THRESHOLDS),
        source=SRC_SOURCE_CONFIG,
        notes=(
            "Declared in habitat_suitability_v3_grid_service._band. "
            "Not persisted as a separate field; implied by the stored "
            "suitability_band labels."
        ),
    ))

    entries.append(ReconstructionField(
        field_name="artifact_path",
        value=habitat_model["artifact_path"],
        source=SRC_PERSISTED,
        notes="habitat_suitability_models.artifact_path",
    ))
    entries.append(ReconstructionField(
        field_name="artifact_sha256_expected",
        value=PRODUCTION_V3_ARTIFACT_SHA256,
        source=SRC_ARTIFACT_DERIVED,
        notes="constant in this checker; matches the deployment row",
    ))
    entries.append(ReconstructionField(
        field_name="artifact_sha256_observed",
        value=artifact_sha_observed,
        source=SRC_ARTIFACT_DERIVED,
        notes="recomputed from the artifact file at audit time",
    ))
    entries.append(ReconstructionField(
        field_name="artifact_sha256_persisted",
        value=deployment["artifact_hash"],
        source=SRC_PERSISTED,
        notes="suitability_deployments.artifact_hash",
    ))
    entries.append(ReconstructionField(
        field_name="deployment_status",
        value=deployment["status"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="deployment_generated_at",
        value=deployment["generated_at"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="deployment_activated_at",
        value=deployment["activated_at"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="training_sample_count_persisted",
        value=habitat_model["training_sample_count"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="eligible_presence_count_persisted",
        value=habitat_model["eligible_presence_count"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="eligible_background_count_persisted",
        value=habitat_model["eligible_background_count"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="spatial_block_count_persisted",
        value=habitat_model["spatial_block_count"],
        source=SRC_PERSISTED,
    ))
    entries.append(ReconstructionField(
        field_name="coefficients_persisted",
        value=habitat_model["coefficients"],
        source=SRC_PERSISTED,
        notes="habitat_suitability_models.coefficients_json",
    ))

    # ------------------------------------------------------------------
    # Reconstruction status decisions.
    # ------------------------------------------------------------------

    if occurrence_dataset is None:
        occurrence_status = OCCURRENCE_NOT
        occurrence_notes = (
            "No ScientificDataset is linked to the deployment via the "
            "scientific_dataset_deployments.role=TRAINING_OCCURRENCES row."
        )
    elif occurrence_count == 54:
        occurrence_status = OCCURRENCE_EXACTLY
        occurrence_notes = (
            f"All 54 historical_occurrences rows with dataset_id="
            f"{occurrence_dataset['id']} resolve from the production DB."
        )
    else:
        occurrence_status = OCCURRENCE_PARTIALLY
        occurrence_notes = (
            f"Historical occurrences table contains {occurrence_count} rows "
            f"for dataset_id={occurrence_dataset['id']}; the expected v3 "
            "snapshot count is 54."
        )

    if environmental_dataset is None:
        environmental_status = OCCURRENCE_NOT
        environmental_notes = (
            "No ScientificDataset is linked to the deployment via the "
            "scientific_dataset_deployments.role=ENVIRONMENTAL_INPUT row."
        )
    else:
        # Phase 10E-1 added an explicit scientific_dataset_id FK to
        # prediction_sample_environmental_features and backfilled the
        # historical rows. When the migration has been applied AND the
        # backfill is unambiguous (single dataset_id, zero NULLs), the
        # exact owned row set can be reconstructed; this is
        # EXACTLY_RECONSTRUCTABLE in the migration-verified sense.
        # Otherwise we fall back to the legacy PARTIALLY_RECONSTRUCTABLE
        # verdict.
        if (
            environmental_ownership is not None
            and environmental_ownership.get("null_count", -1) == 0
            and len(environmental_ownership.get("dataset_id_counts", [])) == 1
            and environmental_ownership["dataset_id_counts"][0]["dataset_id"]
            == environmental_dataset["id"]
        ):
            environmental_status = OCCURRENCE_EXACTLY
            environmental_notes = (
                "Phase 10E-1 migration applied. Environmental "
                "ScientificDataset identity, source, version, and "
                "feature_version are persisted. Per-dataset row "
                "ownership is now provable via the scientific_dataset_id "
                "FK (MIGRATION_VERIFIED -- NOT historically persisted; "
                "retroactively established by the Phase 10E-1 "
                "migration on byte-identical scientific values)."
            )
        else:
            # The schema did not store scientific_dataset_id on
            # prediction_sample_environmental_features. Rows are
            # selected by feature_version only. The exact set of rows
            # used as inputs to the historical run is therefore not
            # provable; this is partial reconstruction at best.
            environmental_status = OCCURRENCE_PARTIALLY
            environmental_notes = (
                "Environmental ScientificDataset identity, source, version "
                "and feature_version are persisted. The exact per-dataset "
                "row ownership is NOT persisted: the "
                "prediction_sample_environmental_features table has no "
                "scientific_dataset_id foreign key, so feature_version "
                "filtering alone is ambiguous across datasets."
            )

    configuration_status = STATUS_PARTIAL
    configuration_notes = (
        "CONFIGURATION_RECONSTRUCTION is PARTIAL: the deployment row, "
        "the HabitatSuitabilityModel row, the ScientificDataset rows, "
        "the dataset-generation row, and the artifact SHA are persisted. "
        "The training extent, the candidate definitions, the algorithm "
        "hyperparameters, the selection rule, the depth strata, and the "
        "Jamaica prediction grid bounds are SOURCE_CONFIG (declared in "
        "current compatibility code, not persisted with the historical run)."
    )

    if environmental_status == OCCURRENCE_EXACTLY:
        scientific_input_status = STATUS_PARTIAL
        scientific_input_notes = (
            "SCIENTIFIC_INPUT_RECONSTRUCTION is PARTIAL after Phase 10E-1: "
            "historical occurrence rows resolve exactly via dataset_id, and "
            "the exact owned environmental row set can now be identified via "
            "the scientific_dataset_id FK (MIGRATION_VERIFIED). The original "
            "training run did NOT persist the FK; the ownership is "
            "retroactively established. Training-cohort-level counts "
            "(presence=389, background=1893) are persisted."
        )
    else:
        scientific_input_status = STATUS_PARTIAL
        scientific_input_notes = (
            "SCIENTIFIC_INPUT_RECONSTRUCTION is PARTIAL: historical "
            "occurrence rows resolve exactly via dataset_id, but the exact "
            "set of environmental rows that fed the historical training run "
            "cannot be proven because the environmental table is keyed by "
            "feature_version rather than dataset_id. Training-cohort-level "
            "counts (presence=389, background=1893) are persisted."
        )

    byte_identical_status = STATUS_IMPOSSIBLE
    byte_identical_notes = (
        "BYTE_IDENTICAL_REPRODUCIBILITY is IMPOSSIBLE_FROM_CURRENT_PROVENANCE: "
        "the exact set of environmental rows used historically is not "
        "deterministically recoverable, the persisted coefficients only "
        "cover the linear candidates, and the random_state of the fitted "
        "artifact matches the source-config seed but the dataset rows it "
        "was fit on are not fully reconstructable. The artifact SHA can be "
        "matched against the deployment row, but the artifact bytes cannot "
        "be reproduced from the currently persisted provenance alone."
    )

    gaps: List[str] = []
    warnings: List[str] = []

    if environmental_status != OCCURRENCE_EXACTLY:
        gaps.append(
            "Environmental feature rows have no scientific_dataset_id foreign "
            "key. Future provenance must record which ScientificDataset owned "
            "each prediction_sample_environmental_features row at training time."
        )
    gaps.append(
        "No TrainingRun table exists. The historical run record is "
        "synthesized from HabitatSuitabilityModel + SuitabilityDeployment "
        "+ PredictionModelDatasetGeneration. A dedicated TrainingRun table "
        "should persist seed, candidate selection, complete-case "
        "exclusions, and CV splits explicitly."
    )
    gaps.append(
        "Algorithm hyperparameters are not persisted as a separate "
        "record. They are recoverable from current source_config or from "
        "the artifact's fitted attributes for the selected estimator only."
    )

    warnings.append(
        "SOURCE_CONFIG labels (training extent, candidate definitions, "
        "selection rule, hyperparameters, Jamaica grid bounds) reflect "
        "current source code; they were not historically persisted with "
        "the training run. A schema migration is required to make these "
        "first-class persisted fields."
    )
    if artifact_info.get("has_feature_names_in_"):
        warnings.append(
            "Artifact embeds feature names; do not assume v3 artifacts do "
            "not embed them. The current production artifact does NOT "
            "embed feature names, but the schema does not prevent it."
        )

    training_geography = {
        "latitude_min": V3_TRAINING_LATITUDE_MIN,
        "latitude_max": V3_TRAINING_LATITUDE_MAX,
        "longitude_min": V3_TRAINING_LONGITUDE_MIN,
        "longitude_max": V3_TRAINING_LONGITUDE_MAX,
        "source": SRC_SOURCE_CONFIG,
    }
    prediction_grid = {
        "bounds": list(V3_JAMAICA_GRID_BOUNDS),
        "grid_size_degrees": V3_JAMAICA_GRID_SIZE_DEGREES,
        "source": SRC_SOURCE_CONFIG,
    }

    return SuitabilityReconstructionReport(
        target_species=scientific_name,
        target_jurisdiction=species_program["jurisdiction_name"],
        target_model_version=model_version,
        artifact_path=artifact_path,
        artifact_sha256_expected=PRODUCTION_V3_ARTIFACT_SHA256,
        artifact_sha256_observed=artifact_sha_observed,
        artifact_sha256_matches=(
            artifact_sha_observed == PRODUCTION_V3_ARTIFACT_SHA256
        ),
        field_entries=tuple(entries),
        occurrence_reconstruction=occurrence_status,
        environmental_reconstruction=environmental_status,
        configuration_reconstruction=configuration_status,
        scientific_input_reconstruction=scientific_input_status,
        byte_identical_reproducibility=byte_identical_status,
        gaps=tuple(gaps),
        warnings=tuple(warnings),
        training_geography=training_geography,
        prediction_grid=prediction_grid,
    )


__all__ = [
    "SuitabilityReconstructionReport",
    "ReconstructionField",
    "reconstruct_jamaica_v3",
    "PRODUCTION_V3_ARTIFACT_SHA256",
    "STATUS_FULL",
    "STATUS_PARTIAL",
    "STATUS_INSUFFICIENT",
    "STATUS_PROVEN",
    "STATUS_NOT_PROVEN",
    "STATUS_IMPOSSIBLE",
    "OCCURRENCE_EXACTLY",
    "OCCURRENCE_PARTIALLY",
    "OCCURRENCE_NOT",
    "SRC_PERSISTED",
    "SRC_ARTIFACT_DERIVED",
    "SRC_SOURCE_CONFIG",
    "SRC_INFERRED",
    "SRC_MISSING",
    "SRC_MIGRATION_VERIFIED",
]