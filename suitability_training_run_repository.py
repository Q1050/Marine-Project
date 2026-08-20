"""Phase 10E-2 TrainingRun provenance repository.

This module implements the explicit persistence boundary for
TrainingRun records. It does NOT modify the training engine's
behaviour: ``SuitabilityTrainingEngine.train()`` remains side-effect
free with respect to the database. Persisting a TrainingRun is an
explicit caller decision.

Public API:

- ``create_training_run(db, spec, datasets)``
  Creates a TrainingRun row with status=BUILDING and a
  configuration snapshot derived from the spec. Returns the new
  TrainingRun ORM object (not yet committed).

- ``record_training_completion(db, run, training_result, artifact_path=None)``
  Transitions the run to COMPLETED, persists selected_candidate,
  validation metrics, artifact_path/sha, sample counts, and
  warnings. Computes the artifact_sha256 from disk if not supplied.

- ``record_training_failure(db, run, reason, warnings=None)``
  Transitions the run to FAILED, retains diagnostic context.

- ``assert_training_run_immutable(db, run, attempted_field)``
  Application-level guard that raises ``ValueError`` when an
  attempt is made to silently edit the scientific provenance of a
  COMPLETED run.

- ``link_dataset(db, run, dataset, role)``
  Attaches a ScientificDataset to a TrainingRun with an explicit
  role. Idempotent.

- ``canonical_configuration_json(snapshot)``
  Deterministic JSON encoding for snapshots.

- ``compute_configuration_sha256(snapshot)``
  SHA-256 over the canonical configuration JSON.

- ``validate_native_completion(db, run, training_result)``
  Enforce completeness / consistency invariants for native
  COMPLETED runs.

Phase 10E-3 changes:

- The configuration snapshot is now schema_version=2 and includes
  every scientific configuration actually used by the training
  and prediction engines.
- The snapshot is serialized canonically (stable JSON ordering)
  and SHA-256-hashed; the hash is persisted in
  ``TrainingRun.configuration_sha256``.
- The COMPLETED-run immutability guard now also covers
  ``configuration_sha256`` and the dataset links.
- ``record_training_completion`` validates that the dataset links
  match the configuration and that the selected candidate exists
  in the configured candidates for NATIVE runs.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import (
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
    TrainingRunDataset,
)
from suitability_training_engine import (
    SuitabilityTrainingResult,
    SuitabilityTrainingSpec,
)


logger = logging.getLogger(__name__)


# Status constants.
STATUS_BUILDING = "BUILDING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

# Provenance origin constants.
ORIGIN_NATIVE = "NATIVE"
ORIGIN_LEGACY_RECONSTRUCTED = "LEGACY_RECONSTRUCTED"

# Role vocabulary (reuses Phase 10C labels).
ROLE_TRAINING_OCCURRENCES = "TRAINING_OCCURRENCES"
ROLE_ENVIRONMENTAL_INPUT = "ENVIRONMENTAL_INPUT"
ROLE_VALIDATION_INPUT = "VALIDATION_INPUT"

# Configuration schema version. Phase 10E-3 bumped this from 1 to 2
# to include the expanded scientific coverage (estimator
# hyperparameters, CV method, background extent, band thresholds,
# permutation importance, etc.).
CONFIGURATION_SCHEMA_VERSION_NATIVE = 2
CONFIGURATION_SCHEMA_VERSION_LEGACY = 1

# Phase 10E-5 removed the module-level DEFAULT_BACKGROUND_REGION_BOUNDS
# and SPATIAL_BLOCK_ORIGIN constants as fallbacks. Future native
# TrainingRuns MUST carry their own geography via
# ``spec.background_extent_bounds`` and ``spec.spatial_block_origin``.
# The legacy Jamaica v3 values are still used for the
# LEGACY_RECONSTRUCTED backfill (Phase 10E-2) where they are read
# from the persisted snapshot rather than from this module.

# CV strategy constants used by the engine.
CV_STRATEGY_METHOD = "StratifiedGroupKFold"
CV_STRATEGY_SHUFFLE = True
PRIMARY_SELECTION_METRICS = ("roc_auc", "average_precision")

# Logistic hyperparameters used by _logistic_pipeline.
LOGISTIC_HYPERPARAMETERS = {
    "estimator_family": "LogisticRegression",
    "transformer": "StandardScaler",
    "classifier_class_weight": "balanced",
    "classifier_max_iter": 1000,
}

# Nonlinear hyperparameters used by _nonlinear_pipeline.
NONLINEAR_HYPERPARAMETERS = {
    "estimator_family": "HistGradientBoostingClassifier",
    "learning_rate": 0.08,
    "max_iter": 200,
    "max_leaf_nodes": 15,
    "l2_regularization": 1.0,
    "permutation_importance_n_repeats": 10,
    "use_balanced_sample_weight": True,
}

# Suitability band thresholds (current v3 grid generator).
SUITABILITY_BAND_THRESHOLDS = (0.2, 0.4, 0.6, 0.8)

# Artifact serialization format.
ARTIFACT_FORMAT = "joblib"


# ---------------------------------------------------------------------------
# Canonical serialization.
# ---------------------------------------------------------------------------


def _stable_json_dumps(value: Any) -> str:
    """Deterministic JSON encoding.

    - Sorts dict keys.
    - Preserves list/tuple ordering (the engine uses ordered
      sequences for feature lists and depth strata).
    - Converts sets to sorted lists (sets are not natively
      JSON-serializable; we use sorted lists for stability).
    """
    if isinstance(value, dict):
        items = []
        for k in sorted(value.keys()):
            items.append((k, _stable_json_dumps(value[k])))
        return "{" + ",".join(k + ":" + v for k, v in items) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_stable_json_dumps(v) for v in value) + "]"
    if isinstance(value, tuple):
        # Tuples serialize as JSON arrays; their ordering is preserved.
        return "[" + ",".join(_stable_json_dumps(v) for v in value) + "]"
    if isinstance(value, set):
        items = sorted(_stable_json_dumps(v) for v in value)
        return "[" + ",".join(items) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # Use json.dumps for proper string escaping.
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(
        f"canonical_configuration_json does not support value of type {type(value).__name__}"
    )


def canonical_configuration_json(snapshot: Dict[str, Any]) -> str:
    """Return a deterministic JSON string encoding of the snapshot."""
    return _stable_json_dumps(snapshot)


def compute_configuration_sha256(snapshot: Dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical configuration JSON."""
    encoded = canonical_configuration_json(snapshot).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Configuration snapshot builders.
# ---------------------------------------------------------------------------


def _as_jsonable(value: Any) -> Any:
    """Convert dataclass / tuple values into JSON-friendly primitives.

    Used only by the legacy builder. The native builder uses
    canonical_configuration_json for its serialization to ensure
    deterministic output.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_jsonable(item) for item in value]
    if dataclasses.is_dataclass(value):
        return {
            f.name: _as_jsonable(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    return str(value)


def _ordered_features(physical: Tuple[str, ...], climate: Tuple[str, ...]) -> List[str]:
    """Return the canonical feature ordering used by the matrix
    builder. The engine builds ``physical_features +
    climate_features`` in that order.
    """
    return list(physical) + list(climate)


def build_configuration_snapshot(
    spec: SuitabilityTrainingSpec,
    *,
    provenance_classification: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build an immutable configuration snapshot from a
    SuitabilityTrainingSpec.

    Phase 10E-3 expands the snapshot to schema_version=2 with
    every scientific configuration used by the training and
    prediction engines, so future native runs do not depend on
    current source constants.

    ``provenance_classification`` is an optional dict mapping
    field_name -> source classification (PERSISTED / SOURCE_CONFIG
    / MIGRATION_VERIFIED / MISSING). The mapping is preserved in
    the snapshot so future audits cannot mistake one classification
    for another.
    """
    grid = spec.grid
    feature_order = _ordered_features(spec.physical_features, spec.climate_features)
    snapshot: Dict[str, Any] = {
        # Schema / provenance metadata.
        "schema_version": CONFIGURATION_SCHEMA_VERSION_NATIVE,
        # Identification.
        "species": spec.species,
        "species_program_id": spec.species_program_id,
        "geographic_scope": spec.geographic_scope,
        "region_id": spec.region_id,
        "jurisdiction_id": spec.jurisdiction_id,
        # Datasets.
        "occurrence_dataset_id": spec.occurrence_dataset_id,
        "environmental_dataset_ids": list(spec.environmental_dataset_ids),
        # Features (with canonical ordering).
        "physical_features": list(spec.physical_features),
        "climate_features": list(spec.climate_features),
        "feature_order": feature_order,
        # Candidate models.
        "candidate_models": [
            {
                "name": c.name,
                "features": list(c.features),
                "algorithm": c.algorithm,
                "nonlinear": c.nonlinear,
            }
            for c in spec.candidate_models
        ],
        # Estimator hyperparameters (preserved verbatim from the
        # engine helpers).
        "logistic_hyperparameters": dict(LOGISTIC_HYPERPARAMETERS),
        "nonlinear_hyperparameters": dict(NONLINEAR_HYPERPARAMETERS),
        # Sampling.
        "random_seed": spec.random_seed,
        "background_ratio": spec.background_ratio,
        # Phase 10E-5: background_extent and training_extent read
        # directly from the spec. Generic callers MUST supply
        # ``spec.background_extent_bounds`` explicitly. The legacy
        # Jamaica v3 values come from the ``jamaica_v3()`` factory.
        "background_extent": dict(spec.background_extent_bounds)
        if spec.background_extent_bounds is not None else None,
        "depth_strata": [
            {"name": name, "lower": lower, "upper": upper}
            for (name, lower, upper) in spec.depth_strata
        ],
        "max_presence_depth_m": spec.max_presence_depth_m,
        # Spatial blocking.
        "spatial_block_size_degrees": spec.spatial_block_size_degrees,
        "spatial_block_origin": dict(spec.spatial_block_origin)
        if spec.spatial_block_origin is not None else None,
        # Cross-validation.
        "cv_folds": spec.cv_folds,
        "cv_strategy": {
            "method": CV_STRATEGY_METHOD,
            "shuffle": CV_STRATEGY_SHUFFLE,
            "random_state_source": "spec.random_seed",
        },
        "primary_selection_metrics": list(PRIMARY_SELECTION_METRICS),
        # Model selection.
        "selection_geography_threshold": spec.selection_geography_threshold,
        "selection_rule_text": (
            "Prefer the stronger environment-only model unless "
            "geography+environment improves both mean ROC AUC and "
            "mean average precision by more than the threshold."
        ),
        # Training extent. Phase 10E-5 reads this from
        # ``spec.background_extent_bounds`` (same domain).
        "training_extent": dict(spec.background_extent_bounds)
        if spec.background_extent_bounds is not None else None,
        # Prediction grid.
        "prediction_grid": {
            "name": grid.name,
            "bounds": list(grid.bounds),
            "grid_size_degrees": grid.grid_size_degrees,
        },
        "grid": {
            "name": grid.name,
            "bounds": list(grid.bounds),
            "grid_size_degrees": grid.grid_size_degrees,
        },
        # Suitability band thresholds.
        "suitability_band_thresholds": list(SUITABILITY_BAND_THRESHOLDS),
        # Versions.
        "model_version": spec.model_version,
        "generation_version": spec.generation_version,
        "feature_version": spec.feature_version,
        # Artifact.
        "artifact_path": spec.artifact_path,
        "artifact_format": ARTIFACT_FORMAT,
    }
    if provenance_classification:
        snapshot["_provenance_classification"] = dict(
            provenance_classification
        )
    return snapshot


def build_legacy_configuration_snapshot(
    species_program_id: int,
    model_version: str,
    feature_version: str,
    generation_version: str,
    dataset_ids: Dict[str, int],
    *,
    artifact_sha256: str,
    random_seed: int,
    background_ratio: int,
    block_size_degrees: float,
    cv_folds: int,
    selection_threshold: float,
    training_extent: Dict[str, float],
    grid: Dict[str, Any],
    selection_rule_text: str,
    sample_counts: Dict[str, int],
    provenance_classification: Dict[str, str],
) -> Dict[str, Any]:
    """Build a configuration snapshot for a LEGACY_RECONSTRUCTED
    TrainingRun. Every field's source classification is recorded
    so the Phase 10D-5 distinction between PERSISTED / SOURCE_CONFIG
    / MIGRATION_VERIFIED / MISSING is preserved.

    Legacy snapshots use schema_version=1 (Phase 10E-2 format) so
    future schema migrations can detect legacy rows by version.
    """
    return {
        "schema_version": CONFIGURATION_SCHEMA_VERSION_LEGACY,
        "provenance_origin": ORIGIN_LEGACY_RECONSTRUCTED,
        "species_program_id": species_program_id,
        "model_version": model_version,
        "feature_version": feature_version,
        "generation_version": generation_version,
        "dataset_ids": dataset_ids,
        "random_seed": random_seed,
        "background_ratio": background_ratio,
        "spatial_block_size_degrees": block_size_degrees,
        "cv_folds": cv_folds,
        "selection_geography_threshold": selection_threshold,
        "selection_rule_text": selection_rule_text,
        "training_extent": training_extent,
        "grid": grid,
        "artifact_sha256": artifact_sha256,
        "sample_counts": sample_counts,
        "_provenance_classification": dict(provenance_classification),
    }


# ---------------------------------------------------------------------------
# Persistence boundary.
# ---------------------------------------------------------------------------


def create_training_run(
    db: Session,
    spec: SuitabilityTrainingSpec,
    *,
    datasets: Optional[Iterable[Tuple[ScientificDataset, str]]] = None,
    started_at: Optional[datetime] = None,
    provenance_origin: str = ORIGIN_NATIVE,
) -> TrainingRun:
    """Create a TrainingRun row with status=BUILDING and an
    immutable configuration snapshot.

    The configuration snapshot is serialized canonically and the
    SHA-256 of that canonical form is persisted as
    ``configuration_sha256``.

    ``datasets`` is an optional iterable of
    ``(ScientificDataset, role)`` tuples. If provided, the
    relationships are persisted in the same transaction.

    The returned object is not yet committed.
    """
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    config_snapshot = build_configuration_snapshot(spec)
    config_sha = compute_configuration_sha256(config_snapshot)
    run = TrainingRun(
        species_program_id=spec.species_program_id,
        model_version=spec.model_version,
        status=STATUS_BUILDING,
        provenance_origin=provenance_origin,
        started_at=started_at,
        random_seed=spec.random_seed,
        configuration_json=json.dumps(config_snapshot),
        configuration_sha256=config_sha,
        training_sample_count=None,
        presence_count=None,
        background_count=None,
    )
    db.add(run)
    db.flush()
    if datasets is not None:
        for dataset, role in datasets:
            link_training_run_dataset(db, run, dataset, role)
    return run


def link_training_run_dataset(
    db: Session,
    run: TrainingRun,
    dataset: ScientificDataset,
    role: str,
) -> Optional[TrainingRunDataset]:
    """Attach a ScientificDataset to a TrainingRun with a role.

    Idempotent: if the (run, dataset, role) tuple already exists,
    no new row is created.
    """
    if run.status == STATUS_COMPLETED:
        raise ValueError(
            f"TrainingRun {run.id} is COMPLETED; dataset links "
            f"are immutable."
        )
    existing = (
        db.query(TrainingRunDataset)
        .filter(
            TrainingRunDataset.training_run_id == run.id,
            TrainingRunDataset.scientific_dataset_id == dataset.id,
            TrainingRunDataset.role == role,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing
    link = TrainingRunDataset(
        training_run_id=run.id,
        scientific_dataset_id=dataset.id,
        role=role,
    )
    db.add(link)
    db.flush()
    return link


def _validate_dataset_link_consistency(
    run: TrainingRun,
    training_result: SuitabilityTrainingResult,
) -> None:
    """For NATIVE runs, ensure the dataset IDs in the persisted
    configuration snapshot agree exactly with the relational
    TrainingRunDataset links.

    Raises ``ValueError`` on any disagreement. Mismatches are NOT
    silently repaired; the caller is responsible for fixing the
    dataset links before calling ``record_training_completion``.
    """
    if run.provenance_origin != ORIGIN_NATIVE:
        return
    config_snapshot = json.loads(run.configuration_json)
    configured_occ = config_snapshot.get("occurrence_dataset_id")
    configured_env = list(
        config_snapshot.get("environmental_dataset_ids") or []
    )
    linked_dataset_ids_by_role: Dict[str, set] = {}
    for link in run.dataset_links:
        linked_dataset_ids_by_role.setdefault(link.role, set()).add(
            link.scientific_dataset_id
        )
    occurrence_links = linked_dataset_ids_by_role.get(
        ROLE_TRAINING_OCCURRENCES, set()
    )
    environmental_links = linked_dataset_ids_by_role.get(
        ROLE_ENVIRONMENTAL_INPUT, set()
    )
    if configured_occ is not None:
        if len(occurrence_links) != 1 or configured_occ not in occurrence_links:
            raise ValueError(
                f"TrainingRun {run.id}: configuration occurrence_dataset_id="
                f"{configured_occ} disagrees with TRAINING_OCCURRENCES "
                f"links={sorted(occurrence_links)}"
            )
    if configured_env:
        if set(configured_env) != environmental_links:
            raise ValueError(
                f"TrainingRun {run.id}: configuration environmental_dataset_ids="
                f"{sorted(configured_env)} disagrees with ENVIRONMENTAL_INPUT "
                f"links={sorted(environmental_links)}"
            )
    if not configured_env and environmental_links:
        raise ValueError(
            f"TrainingRun {run.id}: environmental_dataset_ids missing "
            "from configuration but ENVIRONMENTAL_INPUT links present"
        )


def _validate_selected_candidate(
    run: TrainingRun,
    training_result: SuitabilityTrainingResult,
) -> None:
    """Ensure the selected candidate exists in the configured
    candidates (Phase 10D-3 selection-rule contract)."""
    config_snapshot = json.loads(run.configuration_json)
    configured_candidates = {
        c.get("name")
        for c in config_snapshot.get("candidate_models", [])
    }
    if configured_candidates and training_result.selected_candidate_name not in configured_candidates:
        raise ValueError(
            f"TrainingRun {run.id}: selected_candidate="
            f"{training_result.selected_candidate_name!r} is not in the "
            f"configured candidates {sorted(configured_candidates)}"
        )


def validate_native_completion(
    db: Session,
    run: TrainingRun,
    training_result: SuitabilityTrainingResult,
) -> None:
    """Enforce completeness invariants for native COMPLETED runs.

    - configuration_sha256 must match the recomputed hash of the
      persisted configuration_json.
    - Dataset links must match configuration IDs.
    - Selected candidate must exist in configured candidates.
    - Artifact SHA must be present.
    - Validation metrics must be present.
    - Training input SHA must be present (Phase 10E-4).
    - input_integrity_status must be COMPLETE (Phase 10E-4).
    """
    if run.provenance_origin != ORIGIN_NATIVE:
        return
    config_snapshot = json.loads(run.configuration_json)
    if config_snapshot.get("schema_version") != CONFIGURATION_SCHEMA_VERSION_NATIVE:
        raise ValueError(
            f"TrainingRun {run.id}: native completion requires schema_version="
            f"{CONFIGURATION_SCHEMA_VERSION_NATIVE}, got "
            f"{config_snapshot.get('schema_version')}"
        )
    expected_sha = compute_configuration_sha256(config_snapshot)
    if run.configuration_sha256 != expected_sha:
        raise ValueError(
            f"TrainingRun {run.id}: configuration_sha256="
            f"{run.configuration_sha256} does not match recomputed="
            f"{expected_sha}"
        )
    _validate_dataset_link_consistency(run, training_result)
    _validate_selected_candidate(run, training_result)
    if not run.training_input_sha256:
        raise ValueError(
            f"TrainingRun {run.id}: training_input_sha256 is required "
            "for native completion"
        )
    if run.input_integrity_status != "COMPLETE":
        raise ValueError(
            f"TrainingRun {run.id}: input_integrity_status="
            f"{run.input_integrity_status!r} is not COMPLETE; native "
            "completion requires every linked dataset to have an "
            "artifact_sha256."
        )
    if not run.artifact_sha256:
        raise ValueError(
            f"TrainingRun {run.id}: artifact_sha256 is required for "
            "native completion"
        )
    if not run.validation_metrics_json:
        raise ValueError(
            f"TrainingRun {run.id}: validation_metrics_json is required "
            "for native completion"
        )


def record_training_completion(
    db: Session,
    run: TrainingRun,
    training_result: SuitabilityTrainingResult,
    *,
    artifact_path: Optional[str] = None,
    artifact_sha256: Optional[str] = None,
    skip_validation: bool = False,
) -> TrainingRun:
    """Transition the run to COMPLETED with full scientific
    provenance. The configuration snapshot, dataset links, and
    validation metrics are persisted.

    For NATIVE runs, ``validate_native_completion`` is invoked
    by default. Pass ``skip_validation=True`` for LEGACY runs
    (where the configuration snapshot is incomplete by design).

    If artifact_path is supplied but artifact_sha256 is None, the
    SHA is recomputed from disk.
    """
    if run.status != STATUS_BUILDING:
        raise ValueError(
            f"TrainingRun {run.id} is in status={run.status}; "
            "only BUILDING runs can transition to COMPLETED."
        )

    if not skip_validation:
        # Provisional validation: the artifact_sha256 may not yet
        # be persisted. Apply the parts we can check now (links,
        # selected candidate). The artifact_sha256 check happens
        # after we persist it.
        _validate_dataset_link_consistency(run, training_result)
        _validate_selected_candidate(run, training_result)

    if artifact_sha256 is None and artifact_path is not None:
        artifact_sha256 = _sha256(artifact_path)

    selected_features = list(training_result.selected_feature_names)
    candidate_result = training_result.candidate_results.get(
        training_result.selected_candidate_name
    )
    metrics_blob = None
    if candidate_result is not None:
        metrics_blob = json.dumps({
            "aggregate": candidate_result.aggregate,
            "fold_metrics": candidate_result.fold_metrics,
            "extra": candidate_result.extra,
            "selected_features": selected_features,
            "selection_rationale": training_result.selection_rationale,
        })

    warnings_blob = None
    if training_result.warnings:
        warnings_blob = json.dumps(list(training_result.warnings))

    run.status = STATUS_COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    run.selected_candidate = training_result.selected_candidate_name
    if artifact_path is not None:
        run.artifact_path = artifact_path
    elif training_result.artifact_path:
        run.artifact_path = training_result.artifact_path
    if artifact_sha256 is not None:
        run.artifact_sha256 = artifact_sha256
    elif training_result.artifact_sha256:
        run.artifact_sha256 = training_result.artifact_sha256
    run.training_sample_count = training_result.training_sample_count
    run.presence_count = training_result.presence_count
    run.background_count = training_result.background_count
    run.validation_metrics_json = metrics_blob
    run.warnings_json = warnings_blob
    run.failure_reason = None

    # Phase 10E-4: persist the training input integrity SHA for
    # native runs before validation. The hash is computed over the
    # ordered TrainingRunDataset links. The integrity status is
    # PARTIAL when any linked dataset has a NULL artifact_sha256.
    if run.provenance_origin == ORIGIN_NATIVE:
        from suitability_dataset_artifact_repository import (
            persist_training_input_sha256,
        )
        persist_training_input_sha256(db, run)

    # Final validation for native runs.
    if not skip_validation:
        validate_native_completion(db, run, training_result)

    db.flush()
    return run


def record_training_failure(
    db: Session,
    run: TrainingRun,
    reason: str,
    *,
    warnings: Optional[List[str]] = None,
) -> TrainingRun:
    """Transition the run to FAILED with diagnostic context."""
    if run.status != STATUS_BUILDING:
        raise ValueError(
            f"TrainingRun {run.id} is in status={run.status}; "
            "only BUILDING runs can transition to FAILED."
        )
    run.status = STATUS_FAILED
    run.completed_at = datetime.now(timezone.utc)
    run.failure_reason = reason
    if warnings:
        existing: List[str] = []
        if run.warnings_json:
            try:
                existing = json.loads(run.warnings_json)
                if not isinstance(existing, list):
                    existing = []
            except (TypeError, ValueError):
                existing = []
        run.warnings_json = json.dumps(existing + list(warnings))
    db.flush()
    return run


def assert_completed_immutable(
    run: TrainingRun,
    attempted_field: str,
) -> None:
    """Application-level guard for COMPLETED-run immutability.

    Raises ``ValueError`` if the caller attempts to silently
    mutate the scientific provenance of a COMPLETED run.
    """
    if run.status == STATUS_COMPLETED:
        raise ValueError(
            f"TrainingRun {run.id} is COMPLETED; "
            f"field {attempted_field!r} cannot be silently mutated."
        )


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "STATUS_BUILDING",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "ORIGIN_NATIVE",
    "ORIGIN_LEGACY_RECONSTRUCTED",
    "ROLE_TRAINING_OCCURRENCES",
    "ROLE_ENVIRONMENTAL_INPUT",
    "ROLE_VALIDATION_INPUT",
    "CONFIGURATION_SCHEMA_VERSION_NATIVE",
    "CONFIGURATION_SCHEMA_VERSION_LEGACY",
    "SUITABILITY_BAND_THRESHOLDS",
    "CV_STRATEGY_METHOD",
    "CV_STRATEGY_SHUFFLE",
    "LOGISTIC_HYPERPARAMETERS",
    "NONLINEAR_HYPERPARAMETERS",
    "ARTIFACT_FORMAT",
    "create_training_run",
    "link_training_run_dataset",
    "record_training_completion",
    "record_training_failure",
    "assert_completed_immutable",
    "validate_native_completion",
    "build_configuration_snapshot",
    "build_legacy_configuration_snapshot",
    "canonical_configuration_json",
    "compute_configuration_sha256",
]