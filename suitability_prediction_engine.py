"""Phase 10D-4: generalized suitability grid prediction engine.

This module extends the Phase 10D-3 training engine with a reusable
prediction surface that consumes a ``SuitabilityTrainingResult`` together
with an explicit ``SuitabilityGrid`` and an explicit environmental
inputs bundle. The engine:

- enumerates grid cells from ``SuitabilityGrid.candidate_cells``
  (deterministic, no Jamaica globals)
- resolves environmental feature values per cell from the explicit
  inputs bundle (no global database query)
- runs the selected fitted model from the training result on each cell
- assigns suitability bands using the explicit thresholds used by the
  current v3 grid generator (``0.2``, ``0.4``, ``0.6``, ``0.8``)
- returns an in-memory ``SuitabilityPredictionResult`` (not persisted)

It also defines ``prepare_deployment_candidate(...)`` which validates
the training/prediction result is eligible for deployment preparation
and returns a structured deployment candidate with status
``CANDIDATE`` (or ``NOT_ACTIVE``). It MUST NOT insert
``SuitabilityDeployment``, MUST NOT activate anything, MUST NOT write
production grid cells, and MUST NOT modify ``SpeciesProgram``.

Limitations reported explicitly:
- The Phase 10D-2 loaders resolve environmental feature rows by
  ``feature_version``. The schema does not yet represent per-dataset
  feature ownership beyond ``feature_version``. The engine preserves
  the existing v3-compatible behaviour (last-write-wins for cells that
  have multiple rows across datasets) and records this in
  ``prediction_warnings``.
- No automatic deployment activation. Activation remains a separate
  later operation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from suitability_training_engine import SuitabilityTrainingResult
from suitability_training_spec import SuitabilityGrid


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Band thresholds (current v3 grid generator's exact semantics).
# ---------------------------------------------------------------------------

# The thresholds below mirror
# ``HabitatSuitabilityV3GridService._band`` in
# ``habitat_suitability_v3_grid_service.py``. They are NOT generic
# defaults; they are the production v3 boundaries and the engine
# preserves them verbatim. They are reproduced here so that the
# generic predictor does not import a Jamaica-specific module.
SUITABILITY_BAND_THRESHOLDS: Tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)

SUITABILITY_BANDS: Tuple[str, ...] = (
    "VERY_LOW",
    "LOW",
    "MODERATE",
    "HIGH",
    "VERY_HIGH",
)


def suitability_band(score: Optional[float]) -> Optional[str]:
    """Return the v3 band label for a raw model score.

    The mapping is identical to ``HabitatSuitabilityV3GridService._band``:

    - score < 0.2  -> "VERY_LOW"
    - score < 0.4  -> "LOW"
    - score < 0.6  -> "MODERATE"
    - score < 0.8  -> "HIGH"
    - otherwise    -> "VERY_HIGH"

    A ``None`` score (incomplete features) returns ``None``.
    """
    if score is None:
        return None
    if score < SUITABILITY_BAND_THRESHOLDS[0]:
        return "VERY_LOW"
    if score < SUITABILITY_BAND_THRESHOLDS[1]:
        return "LOW"
    if score < SUITABILITY_BAND_THRESHOLDS[2]:
        return "MODERATE"
    if score < SUITABILITY_BAND_THRESHOLDS[3]:
        return "HIGH"
    return "VERY_HIGH"


# ---------------------------------------------------------------------------
# Cell coordinate helpers.
# ---------------------------------------------------------------------------


def _cell_id_for(lat_index: int, lon_index: int) -> str:
    """Return the v3-compatible cell id ``"{lat_index}:{lon_index}"``.

    The v3 grid generator stores cells with this id format. The
    loader rows' ``prediction_model_sample_id`` uses the same format
    so that join-by-cell-id works without an integer remapping.
    """
    return f"{lat_index}:{lon_index}"


def _cell_center(lat_index: int, lon_index: int, size: float) -> Tuple[float, float]:
    """Return the cell center (latitude, longitude).

    Mirrors the v3 convention: ``(index + 0.5) * grid_size``.
    """
    return (
        round((lat_index + 0.5) * size, 6),
        round((lon_index + 0.5) * size, 6),
    )


# ---------------------------------------------------------------------------
# Result structures.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuitabilityCellPrediction:
    """A single grid-cell prediction.

    The fields mirror the columns persisted by
    ``HabitatSuitabilityV3GridCell`` so the temporary result is
    drop-in compatible with the existing schema. The ``status``
    field mirrors ``prediction_status``: ``"SCORED"`` when all
    required features resolved, otherwise ``"INCOMPLETE_FEATURES"``.
    """

    grid_cell_id: str
    latitude: float
    longitude: float
    score: Optional[float]
    band: Optional[str]
    status: str
    feature_values: Dict[str, float]
    missing_features: Tuple[str, ...]
    algorithm: str
    selected_candidate: str


@dataclass(frozen=True)
class SuitabilityPredictionResult:
    """Immutable in-memory prediction result.

    Contains the full provenance required to audit a prediction
    without consulting the database. ``prediction_warnings`` records
    limitations discovered during prediction (e.g. ambiguous
    environmental feature ownership).
    """

    species: str
    geographic_scope: str
    region_id: Optional[int]
    jurisdiction_id: Optional[int]
    model_version: str
    feature_version: str
    generation_version: str
    selected_candidate: str
    selected_feature_names: Tuple[str, ...]
    grid: Dict[str, Any]
    cell_predictions: Tuple[SuitabilityCellPrediction, ...]
    dataset_provenance: Dict[str, Any]
    artifact_path: Optional[str]
    artifact_sha256: Optional[str]
    band_thresholds: Tuple[float, ...]
    generated_at: str
    prediction_warnings: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_cells(self) -> int:
        return len(self.cell_predictions)

    @property
    def scored_cells(self) -> int:
        return sum(1 for cell in self.cell_predictions if cell.status == "SCORED")

    @property
    def incomplete_cells(self) -> int:
        return sum(
            1 for cell in self.cell_predictions if cell.status != "SCORED"
        )


@dataclass(frozen=True)
class SuitabilityDeploymentCandidate:
    """Immutable deployment-preparation candidate.

    Produced exclusively by ``prepare_deployment_candidate``. The
    candidate is a structured value, not a database row. It carries
    the eligibility metadata required to validate a deployment and
    leaves the activation decision to a separate operation.
    """

    status: str  # "CANDIDATE" or "NOT_ACTIVE"
    eligibility_reasons: Tuple[str, ...]
    species: str
    species_program_id: Optional[int]
    region_id: Optional[int]
    jurisdiction_id: Optional[int]
    model_version: str
    feature_version: str
    generation_version: str
    selected_candidate: str
    selected_feature_names: Tuple[str, ...]
    grid_cell_count: int
    scored_cell_count: int
    incomplete_cell_count: int
    artifact_path: Optional[str]
    artifact_sha256: Optional[str]
    source_dataset_ids: Dict[str, Any]
    training_metrics: Dict[str, Dict[str, float]]
    grid: Dict[str, Any]
    band_thresholds: Tuple[float, ...]
    generated_at: str
    prediction_warnings: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_active(self) -> bool:
        """Always False for a candidate. Activation is a separate op."""
        return False


# ---------------------------------------------------------------------------
# Environmental feature matching.
# ---------------------------------------------------------------------------


def _build_feature_index(
    inputs,
) -> Tuple[Dict[Tuple[int, int], Dict[str, float]], List[str]]:
    """Index environmental feature values by (lat_index, lon_index).

    The Phase 10D-2 loader resolves environmental rows primarily by
    ``feature_version``. The schema does not yet represent
    per-dataset feature ownership beyond ``feature_version``. The
    engine preserves the existing v3-compatible behaviour:
    last-write-wins per cell when multiple rows are present.

    Returns ``(index, warnings)`` where ``warnings`` records any
    ambiguous ownership discovered.
    """
    index: Dict[Tuple[int, int], Dict[str, float]] = {}
    warnings: List[str] = []
    multi_source_cells: set = set()

    for env_dataset, env_rows in inputs.environmental_datasets:
        for row in env_rows:
            try:
                value = float(row.value)
            except (TypeError, ValueError):
                continue
            sample_id_str = str(row.prediction_model_sample_id)
            if ":" in sample_id_str:
                lat_str, lon_str = sample_id_str.split(":", 1)
                try:
                    lat_index = int(lat_str)
                    lon_index = int(lon_str)
                except ValueError:
                    continue
            else:
                try:
                    lat_index = int(sample_id_str)
                    lon_index = int(sample_id_str)
                except ValueError:
                    continue

            cell_values = index.setdefault((lat_index, lon_index), {})
            for name, existing in list(cell_values.items()):
                if name == row.feature_name:
                    multi_source_cells.add((lat_index, lon_index))
            cell_values[row.feature_name] = value

    if multi_source_cells:
        warnings.append(
            "environmental_feature_ownership_ambiguous: "
            f"{len(multi_source_cells)} cells had feature values contributed "
            "by multiple datasets; last-write-wins per (cell, feature) was "
            "applied. The schema does not yet represent per-dataset "
            "feature ownership beyond feature_version."
        )
    return index, warnings


def _resolve_cell_features(
    lat_index: int,
    lon_index: int,
    feature_index: Dict[Tuple[int, int], Dict[str, float]],
    selected_feature_names: Tuple[str, ...],
    cell_latitude: float,
    cell_longitude: float,
) -> Tuple[Dict[str, float], Tuple[str, ...]]:
    """Resolve the model's required feature values for a grid cell.

    The cell's geographic coordinates (latitude, longitude) are
    synthesized from the cell indices using the v3 convention
    ``(index + 0.5) * grid_size``. This is required because the v3
    geography candidates (``model_a_geography`` and
    ``model_e_geography_environment``) consume latitude and
    longitude directly. The training engine stores the same values
    in each sample's feature_values dict, so the prediction engine
    must produce them consistently.

    Returns ``(feature_values, missing_features)``. ``missing_features``
    is the ordered tuple of feature names with no resolvable value
    for the cell.
    """
    cell_values = dict(feature_index.get((lat_index, lon_index), {}))
    # Synthesize geography features from the cell coordinates so the
    # geography candidates receive latitude/longitude.
    cell_values.setdefault("latitude", float(cell_latitude))
    cell_values.setdefault("longitude", float(cell_longitude))
    feature_values: Dict[str, float] = {}
    missing: List[str] = []
    for name in selected_feature_names:
        value = cell_values.get(name)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            missing.append(name)
        else:
            feature_values[name] = float(value)
    return feature_values, tuple(missing)


def _score_cell(
    fitted_model: Any,
    selected_feature_names: Tuple[str, ...],
    feature_values: Dict[str, float],
) -> float:
    """Run the fitted model on a single cell's feature vector."""
    matrix = np.asarray(
        [[feature_values[name] for name in selected_feature_names]], dtype=float
    )
    return float(fitted_model.predict_proba(matrix)[0, 1])


# ---------------------------------------------------------------------------
# Public predictor.
# ---------------------------------------------------------------------------


def predict_grid(
    training_result: SuitabilityTrainingResult,
    inputs,
    grid: SuitabilityGrid,
    *,
    scientific_name: Optional[str] = None,
    geographic_scope: Optional[str] = None,
    region_id: Optional[int] = None,
    jurisdiction_id: Optional[int] = None,
    feature_version: Optional[str] = None,
    generation_version: Optional[str] = None,
    model_version: Optional[str] = None,
) -> SuitabilityPredictionResult:
    """Run the v3-equivalent grid prediction in memory.

    The function:

    1. enumerates grid cells from ``grid.candidate_cells``
    2. indexes environmental feature values from ``inputs``
    3. runs the selected fitted model on each cell
    4. assigns suitability bands using the v3 thresholds
    5. returns a ``SuitabilityPredictionResult`` (NOT persisted)

    The prediction is fully determined by the inputs. The function
    does NOT write any database rows, does NOT activate any
    deployment, and does NOT regenerate downstream monitoring
    pipelines.
    """
    selected_candidate_name = training_result.selected_candidate_name
    selected_candidate = training_result.candidate_results[selected_candidate_name]
    selected_feature_names = tuple(selected_candidate.features)
    algorithm = selected_candidate.algorithm

    feature_index, index_warnings = _build_feature_index(inputs)

    cell_predictions: List[SuitabilityCellPrediction] = []
    for lat_index, lon_index in grid.candidate_cells():
        cell_id = _cell_id_for(lat_index, lon_index)
        latitude, longitude = _cell_center(lat_index, lon_index, grid.grid_size_degrees)
        feature_values, missing = _resolve_cell_features(
            lat_index,
            lon_index,
            feature_index,
            selected_feature_names,
            latitude,
            longitude,
        )
        if missing:
            cell_predictions.append(SuitabilityCellPrediction(
                grid_cell_id=cell_id,
                latitude=latitude,
                longitude=longitude,
                score=None,
                band=None,
                status="INCOMPLETE_FEATURES",
                feature_values=feature_values,
                missing_features=missing,
                algorithm=algorithm,
                selected_candidate=selected_candidate_name,
            ))
            continue
        score = _score_cell(
            training_result.fitted_model,
            selected_feature_names,
            feature_values,
        )
        cell_predictions.append(SuitabilityCellPrediction(
            grid_cell_id=cell_id,
            latitude=latitude,
            longitude=longitude,
            score=score,
            band=suitability_band(score),
            status="SCORED",
            feature_values=feature_values,
            missing_features=(),
            algorithm=algorithm,
            selected_candidate=selected_candidate_name,
        ))

    generated_at = datetime.now(timezone.utc).isoformat()

    grid_snapshot = {
        "name": grid.name,
        "bounds": list(grid.bounds),
        "grid_size_degrees": grid.grid_size_degrees,
    }

    warnings: List[str] = list(training_result.warnings) + index_warnings

    return SuitabilityPredictionResult(
        species=scientific_name if scientific_name is not None else _species_from_spec(training_result),
        geographic_scope=geographic_scope
        or _scope_from_spec(training_result),
        region_id=region_id if region_id is not None else _region_from_spec(training_result),
        jurisdiction_id=jurisdiction_id
        if jurisdiction_id is not None
        else _jurisdiction_from_spec(training_result),
        model_version=model_version
        if model_version is not None
        else training_result.model_version,
        feature_version=feature_version
        if feature_version is not None
        else training_result.feature_version,
        generation_version=generation_version
        if generation_version is not None
        else training_result.generation_version,
        selected_candidate=selected_candidate_name,
        selected_feature_names=selected_feature_names,
        grid=grid_snapshot,
        cell_predictions=tuple(cell_predictions),
        dataset_provenance=dict(training_result.dataset_provenance),
        artifact_path=training_result.artifact_path,
        artifact_sha256=training_result.artifact_sha256,
        band_thresholds=SUITABILITY_BAND_THRESHOLDS,
        generated_at=generated_at,
        prediction_warnings=tuple(warnings),
    )


def _species_from_spec(training_result: SuitabilityTrainingResult) -> str:
    return str(training_result.spec_snapshot.get("species", ""))


def _scope_from_spec(training_result: SuitabilityTrainingResult) -> str:
    return str(training_result.spec_snapshot.get("geographic_scope", ""))


def _region_from_spec(training_result: SuitabilityTrainingResult) -> Optional[int]:
    value = training_result.spec_snapshot.get("region_id")
    return int(value) if value is not None else None


def _jurisdiction_from_spec(training_result: SuitabilityTrainingResult) -> Optional[int]:
    value = training_result.spec_snapshot.get("jurisdiction_id")
    return int(value) if value is not None else None


# ---------------------------------------------------------------------------
# Deployment preparation boundary.
# ---------------------------------------------------------------------------


_DEPLOYMENT_ELIGIBLE_BANDS = {"MODERATE", "HIGH", "VERY_HIGH"}


def prepare_deployment_candidate(
    prediction_result: SuitabilityPredictionResult,
    *,
    species_program_id: Optional[int] = None,
    min_scored_cells: int = 1,
) -> SuitabilityDeploymentCandidate:
    """Validate a prediction result and produce a deployment candidate.

    Returns a structured ``SuitabilityDeploymentCandidate`` with
    ``status = "CANDIDATE"`` when the prediction is eligible (i.e.
    has at least ``min_scored_cells`` scored cells), otherwise
    ``status = "NOT_ACTIVE"`` with a list of eligibility reasons.

    The function:

    - MUST NOT insert any ``SuitabilityDeployment`` row
    - MUST NOT activate, deactivate, or modify any deployment
    - MUST NOT write any production grid cell rows
    - MUST NOT modify any ``SpeciesProgram`` row
    - DOES carry forward provenance, artifact SHA, grid, and metrics

    Activation remains a separate later operation.
    """
    eligibility_reasons: List[str] = []
    if prediction_result.scored_cells < min_scored_cells:
        eligibility_reasons.append(
            f"insufficient_scored_cells: {prediction_result.scored_cells} < "
            f"{min_scored_cells}"
        )
    if prediction_result.artifact_sha256 is None:
        eligibility_reasons.append("missing_artifact_sha256")
    if prediction_result.scored_cells == 0:
        eligibility_reasons.append("zero_scored_cells")

    status = "CANDIDATE" if not eligibility_reasons else "NOT_ACTIVE"

    source_dataset_ids = {
        key: value
        for key, value in prediction_result.dataset_provenance.items()
        if key in ("occurrence_dataset_id", "environmental_dataset_ids")
    }

    training_metrics: Dict[str, Dict[str, float]] = {}
    for candidate_name, candidate in (
        prediction_result.dataset_provenance or {}
    ).items():
        if isinstance(candidate, dict):
            training_metrics[candidate_name] = candidate  # type: ignore[index]

    return SuitabilityDeploymentCandidate(
        status=status,
        eligibility_reasons=tuple(eligibility_reasons),
        species=prediction_result.species,
        species_program_id=species_program_id,
        region_id=prediction_result.region_id,
        jurisdiction_id=prediction_result.jurisdiction_id,
        model_version=prediction_result.model_version,
        feature_version=prediction_result.feature_version,
        generation_version=prediction_result.generation_version,
        selected_candidate=prediction_result.selected_candidate,
        selected_feature_names=prediction_result.selected_feature_names,
        grid_cell_count=prediction_result.total_cells,
        scored_cell_count=prediction_result.scored_cells,
        incomplete_cell_count=prediction_result.incomplete_cells,
        artifact_path=prediction_result.artifact_path,
        artifact_sha256=prediction_result.artifact_sha256,
        source_dataset_ids=source_dataset_ids,
        training_metrics=training_metrics,
        grid=dict(prediction_result.grid),
        band_thresholds=prediction_result.band_thresholds,
        generated_at=prediction_result.generated_at,
        prediction_warnings=prediction_result.prediction_warnings,
    )


# ---------------------------------------------------------------------------
# Convenience: bundle a small in-memory snapshot for serialization.
# ---------------------------------------------------------------------------


def prediction_result_to_dict(
    prediction_result: SuitabilityPredictionResult,
) -> Dict[str, Any]:
    """Serialize a prediction result to a JSON-friendly dictionary."""
    return {
        "species": prediction_result.species,
        "geographic_scope": prediction_result.geographic_scope,
        "region_id": prediction_result.region_id,
        "jurisdiction_id": prediction_result.jurisdiction_id,
        "model_version": prediction_result.model_version,
        "feature_version": prediction_result.feature_version,
        "generation_version": prediction_result.generation_version,
        "selected_candidate": prediction_result.selected_candidate,
        "selected_feature_names": list(prediction_result.selected_feature_names),
        "grid": dict(prediction_result.grid),
        "total_cells": prediction_result.total_cells,
        "scored_cells": prediction_result.scored_cells,
        "incomplete_cells": prediction_result.incomplete_cells,
        "dataset_provenance": dict(prediction_result.dataset_provenance),
        "artifact_path": prediction_result.artifact_path,
        "artifact_sha256": prediction_result.artifact_sha256,
        "band_thresholds": list(prediction_result.band_thresholds),
        "generated_at": prediction_result.generated_at,
        "prediction_warnings": list(prediction_result.prediction_warnings),
        "cell_predictions": [
            {
                "grid_cell_id": cell.grid_cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "score": cell.score,
                "band": cell.band,
                "status": cell.status,
                "feature_values": dict(cell.feature_values),
                "missing_features": list(cell.missing_features),
                "algorithm": cell.algorithm,
                "selected_candidate": cell.selected_candidate,
            }
            for cell in prediction_result.cell_predictions
        ],
    }


def deployment_candidate_to_dict(
    candidate: SuitabilityDeploymentCandidate,
) -> Dict[str, Any]:
    """Serialize a deployment candidate to a JSON-friendly dictionary."""
    return {
        "status": candidate.status,
        "eligibility_reasons": list(candidate.eligibility_reasons),
        "is_active": candidate.is_active,
        "species": candidate.species,
        "species_program_id": candidate.species_program_id,
        "region_id": candidate.region_id,
        "jurisdiction_id": candidate.jurisdiction_id,
        "model_version": candidate.model_version,
        "feature_version": candidate.feature_version,
        "generation_version": candidate.generation_version,
        "selected_candidate": candidate.selected_candidate,
        "selected_feature_names": list(candidate.selected_feature_names),
        "grid_cell_count": candidate.grid_cell_count,
        "scored_cell_count": candidate.scored_cell_count,
        "incomplete_cell_count": candidate.incomplete_cell_count,
        "artifact_path": candidate.artifact_path,
        "artifact_sha256": candidate.artifact_sha256,
        "source_dataset_ids": dict(candidate.source_dataset_ids),
        "training_metrics": {
            name: dict(metrics)
            for name, metrics in candidate.training_metrics.items()
        },
        "grid": dict(candidate.grid),
        "band_thresholds": list(candidate.band_thresholds),
        "generated_at": candidate.generated_at,
        "prediction_warnings": list(candidate.prediction_warnings),
    }