"""Phase 11C-4 isolated spatial validation for geographic candidates."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from math import floor
from pathlib import Path

import numpy as np

from anomaly_repository import canonical_json
from geographic_baseline_experiment import ExperimentPoint, ExperimentVariant
from geographic_utils import haversine_km
from geographic_validation_inputs import (
    EventIndependence, ExpertCaseLabel, IndependenceStatus,
)


VALIDATION_METHOD_VERSION = "geographic-spatial-validation-v1"
CANDIDATE_METHODS = (
    "NEAREST_EVIDENCE_DISTRIBUTION",
    "DISTANCE_QUANTILE_CANDIDATE",
)


@dataclass(frozen=True)
class SpatialFold:
    fold_index: int
    held_out_blocks: tuple[str, ...]
    training_source_occurrence_ids: tuple[int, ...]
    held_out_source_occurrence_ids: tuple[int, ...]
    training_event_indices: tuple[int, ...]
    held_out_event_indices: tuple[int, ...]
    fingerprint: str


@dataclass(frozen=True)
class IndependentValidationInput:
    scientific_dataset_ids: tuple[int, ...]
    jurisdiction_id: int
    species: str
    points: tuple[ExperimentPoint, ...]
    role: str = "INDEPENDENT_VALIDATION_INPUT"
    canonical_event_ids: tuple[str, ...] = ()
    calibration_canonical_event_ids: tuple[str, ...] = ()
    cross_source_deduplication_complete: bool = False
    acquisition_provenance_json: str | None = None


@dataclass(frozen=True)
class ExpertGeographicCase:
    case_id: str
    species: str
    jurisdiction_id: int
    latitude: float
    longitude: float
    label: str
    expert_id: str
    evidence_reference: str
    labelled_at: str
    notes: str | None = None
    provenance_json: str = "{}"
    version: str = "experimental-v1"


@dataclass(frozen=True)
class GeographicValidationReport:
    species: str
    jurisdiction_id: int
    input_variant: str
    candidate_method: str
    validation_method_version: str
    validation_status: str
    fold_configuration_json: str
    seed_configuration_json: str
    input_fingerprint: str
    fold_fingerprints: tuple[str, ...]
    descriptive_metrics_json: str
    stability_metrics_json: str
    operating_point_analysis_json: str
    uncertainty_json: str
    provenance_json: str
    result_fingerprint: str
    limitations: tuple[str, ...]


class GeographicBaselineValidator:
    def __init__(self, block_size_degrees: float, fold_count: int, seeds, subsample_fraction: float = 0.8):
        if block_size_degrees <= 0 or fold_count < 2:
            raise ValueError("Positive block size and at least two folds are required")
        if not 0 < subsample_fraction < 1:
            raise ValueError("subsample_fraction must be between zero and one")
        self.block_size_degrees = float(block_size_degrees)
        self.fold_count = int(fold_count)
        self.seeds = tuple(int(seed) for seed in seeds)
        self.subsample_fraction = float(subsample_fraction)

    def validate(self, variant: ExperimentVariant, grid_resolutions=(0.05, 0.1, 0.2)) -> list[GeographicValidationReport]:
        folds = self.spatial_folds(variant)
        fold_results = [self._evaluate_fold(variant, fold, grid_resolutions) for fold in folds]
        held_distances = [item for fold in fold_results for item in fold["held_out_distances_km"]]
        descriptive = {
            "effective_event_count": len(variant.points),
            "fold_count": len(folds),
            "known_occurrence_distance_summary": self._summary(held_distances),
            "folds": fold_results,
            "terminology": "KNOWN_OCCURRENCE_FALSE_FLAG_PROXY",
        }
        stability = self._subsampling_stability(variant.points)
        operating = self._aggregate_operating_points(fold_results)
        uncertainty = {
            "method": "seeded_sampling_without_replacement",
            "interval_type": "observed_resampling_range_not_confidence_interval",
            "median_distance_range_km": stability["median_distance_range_km"],
            "q90_range_km": stability["q90_range_km"],
            "q95_range_km": stability["q95_range_km"],
            "maximum_range_km": stability["maximum_range_km"],
            "scientific_authorization": "NOT_AUTHORIZED_WITHOUT_INDEPENDENT_VALIDATION",
        }
        fold_configuration = {
            "block_size_degrees": self.block_size_degrees,
            "requested_fold_count": self.fold_count,
            "assignment": "sorted_complete_blocks_round_robin",
            "grid_resolutions_degrees": list(grid_resolutions),
        }
        seed_configuration = {
            "seeds": list(self.seeds),
            "subsample_fraction": self.subsample_fraction,
            "sampling": "without_replacement",
        }
        return [
            self._report(
                variant, method, folds, fold_configuration, seed_configuration,
                descriptive, stability, operating, uncertainty,
            )
            for method in CANDIDATE_METHODS
        ]

    def spatial_folds(self, variant: ExperimentVariant, strategy="ROUND_ROBIN_BLOCKS") -> tuple[SpatialFold, ...]:
        block_events = {}
        for index, point in enumerate(variant.points):
            key = self._block_key(point)
            block_events.setdefault(key, []).append(index)
        assignments = [[] for _ in range(min(self.fold_count, max(1, len(block_events))))]
        sorted_keys = sorted(block_events, key=self._block_coordinates)
        if strategy == "ROUND_ROBIN_BLOCKS":
            for index, key in enumerate(sorted_keys):
                assignments[index % len(assignments)].append(key)
        elif strategy == "CONTIGUOUS_LONGITUDE_STRIPS":
            # Adjacent longitude-sorted blocks remain in the same interpretable holdout.
            for index, key in enumerate(sorted_keys):
                assignments[min(index * len(assignments) // len(sorted_keys), len(assignments) - 1)].append(key)
        else:
            raise ValueError("Unknown spatial fold strategy")
        folds = []
        all_indices = set(range(len(variant.points)))
        for fold_index, held_blocks in enumerate(assignments):
            held_indices = sorted(index for block in held_blocks for index in block_events[block])
            train_indices = sorted(all_indices - set(held_indices))
            held_ids = sorted({identifier for index in held_indices for identifier in variant.points[index].source_occurrence_ids})
            train_ids = sorted({identifier for index in train_indices for identifier in variant.points[index].source_occurrence_ids})
            payload = {
                "fold_index": fold_index, "held_out_blocks": held_blocks,
                "training_source_occurrence_ids": train_ids,
                "held_out_source_occurrence_ids": held_ids,
                "input_fingerprint": variant.input_fingerprint,
            }
            folds.append(SpatialFold(
                fold_index=fold_index, held_out_blocks=tuple(held_blocks),
                training_source_occurrence_ids=tuple(train_ids),
                held_out_source_occurrence_ids=tuple(held_ids),
                training_event_indices=tuple(train_indices),
                held_out_event_indices=tuple(held_indices),
                fingerprint=hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            ))
        return tuple(folds)

    def validate_independent_input(self, variant: ExperimentVariant, external: IndependentValidationInput) -> dict:
        if external.role != "INDEPENDENT_VALIDATION_INPUT":
            raise ValueError("External evidence must use INDEPENDENT_VALIDATION_INPUT role")
        if external.jurisdiction_id != variant.jurisdiction_id or external.species != variant.species:
            raise ValueError("External evidence ownership is incompatible")
        independence = self.assess_independence(variant, external)
        if independence["independence_status"] == IndependenceStatus.OVERLAPPING.value:
            raise ValueError(f"Independent validation overlap: {independence['reason']}")
        training_ids = set(variant.source_occurrence_ids)
        external_ids = {identifier for point in external.points for identifier in point.source_occurrence_ids}
        if independence["independence_status"] == IndependenceStatus.INDEPENDENCE_UNKNOWN.value:
            distances = self._distances(external.points, variant.points)
            return {**independence, "role": external.role,
                    "external_dataset_ids": list(external.scientific_dataset_ids),
                    "calibration_input_unchanged": variant.input_fingerprint,
                    "distance_summary": self._summary(distances)}
        distances = self._distances(external.points, variant.points)
        return {
            "role": external.role,
            "independence_status": IndependenceStatus.INDEPENDENT.value,
            "external_dataset_ids": list(external.scientific_dataset_ids),
            "calibration_input_unchanged": variant.input_fingerprint,
            "distance_summary": self._summary(distances),
        }

    @staticmethod
    def assess_independence(variant, external):
        if set(external.scientific_dataset_ids) & set(variant.source_dataset_ids):
            return {"independence_status": IndependenceStatus.OVERLAPPING.value,
                    "reason": "scientific_dataset_ids_overlap"}
        training_ids = set(variant.source_occurrence_ids)
        external_ids = {identifier for point in external.points for identifier in point.source_occurrence_ids}
        if training_ids & external_ids:
            return {"independence_status": IndependenceStatus.OVERLAPPING.value,
                    "reason": "occurrence_ids_overlap"}
        if set(external.canonical_event_ids) & set(external.calibration_canonical_event_ids):
            return {"independence_status": IndependenceStatus.OVERLAPPING.value,
                    "reason": "canonical_events_overlap"}
        if not external.cross_source_deduplication_complete or not external.acquisition_provenance_json:
            return {"independence_status": IndependenceStatus.INDEPENDENCE_UNKNOWN.value,
                    "reason": "cross_source_linkage_or_acquisition_provenance_incomplete"}
        return {"independence_status": IndependenceStatus.INDEPENDENT.value,
                "reason": "dataset_occurrence_and_canonical_event_checks_passed"}

    def validate_expert_cases(self, variant, cases, candidate_values_km):
        """Describe expert-case distances; no accuracy or anomaly claim is made."""
        rows = []
        for case in cases:
            if case.species != variant.species or case.jurisdiction_id != variant.jurisdiction_id:
                raise ValueError("Expert case ownership is incompatible")
            distance = self._distances((case,), variant.points)[0] if variant.points else None
            rows.append({
                "case_id": case.case_id, "label": case.label.value if isinstance(case.label, ExpertCaseLabel) else case.label,
                "nearest_distance_km": distance,
                "candidate_behavior": {name: None if distance is None else distance > value
                                       for name, value in candidate_values_km.items()},
            })
        by_label = {}
        for label in ExpertCaseLabel:
            distances = [row["nearest_distance_km"] for row in rows
                         if row["label"] == label.value and row["nearest_distance_km"] is not None]
            by_label[label.value] = self._summary(distances)
        return {
            "cases": rows, "distance_distributions_by_label": by_label,
            "unresolved_abstention_count": sum(row["label"] == ExpertCaseLabel.UNRESOLVED.value for row in rows),
            "interpretation": "DESCRIPTIVE_EXPERT_CASE_BEHAVIOR_NOT_CLASSIFIER_ACCURACY",
        }

    @classmethod
    def block_size_sensitivity(cls, variant, block_sizes, fold_count, seeds,
                               strategy="CONTIGUOUS_LONGITUDE_STRIPS"):
        output = []
        for size in tuple(float(item) for item in block_sizes):
            validator = cls(size, fold_count, seeds)
            folds = validator.spatial_folds(variant, strategy=strategy)
            results = [validator._evaluate_fold(variant, fold, (0.1,)) for fold in folds]
            held = [value for row in results for value in row["held_out_distances_km"]]
            operating = validator._aggregate_operating_points(results)
            output.append({
                "block_size_degrees": size, "strategy": strategy, "fold_count": len(folds),
                "fold_event_counts": [{"training": row["training_event_count"], "holdout": row["held_out_event_count"]} for row in results],
                "held_out_distance_summary": validator._summary(held),
                "candidate_operating_points": operating,
                "stability": validator._subsampling_stability(variant.points),
            })
        return {"experimental_only": True, "block_sizes_degrees": list(map(float, block_sizes)),
                "strategy": strategy, "results": output, "production_block_size_selected": False}

    @staticmethod
    def write_report(report: GeographicValidationReport, directory) -> Path:
        target = Path(directory); target.mkdir(parents=True, exist_ok=True)
        path = target / f"{report.input_variant.lower()}__{report.candidate_method.lower()}__validation.json"
        path.write_text(canonical_json(asdict(report)), encoding="utf-8")
        return path

    def _block_key(self, point):
        return f"{floor(point.latitude / self.block_size_degrees)}:{floor(point.longitude / self.block_size_degrees)}"

    @staticmethod
    def _block_coordinates(key):
        latitude, longitude = (int(item) for item in key.split(":"))
        return longitude, latitude

    def _evaluate_fold(self, variant, fold, grid_resolutions):
        training = [variant.points[index] for index in fold.training_event_indices]
        held = [variant.points[index] for index in fold.held_out_event_indices]
        held_distances = self._distances(held, training)
        calibration_distances = self._leave_one_out(training)
        candidate_values = {
            label: (None if not calibration_distances else float(np.quantile(calibration_distances, quantile)))
            for label, quantile in (("q90", 0.90), ("q95", 0.95), ("q97_5", 0.975))
        }
        operating = {
            label: {
                "candidate_value_km": value,
                "held_out_above_count": 0 if value is None else sum(distance > value for distance in held_distances),
                "held_out_count": len(held_distances),
                "held_out_above_proportion": None if value is None or not held_distances else sum(distance > value for distance in held_distances) / len(held_distances),
                "interpretation": "candidate_operating_point_only",
            }
            for label, value in candidate_values.items()
        }
        grid = {
            format(float(resolution), ".10g"): self._held_to_training_cells(held, training, float(resolution))
            for resolution in grid_resolutions
        }
        return {
            "fold_index": fold.fold_index,
            "fingerprint": fold.fingerprint,
            "training_event_count": len(training),
            "held_out_event_count": len(held),
            "held_out_source_occurrence_ids": list(fold.held_out_source_occurrence_ids),
            "held_out_distances_km": held_distances,
            "held_out_distance_summary": self._summary(held_distances),
            "training_calibration_summary": self._summary(calibration_distances),
            "candidate_operating_points": operating,
            "grid_resolution_sensitivity": grid,
        }

    def _subsampling_stability(self, points):
        rows = []
        if len(points) < 2:
            samples = []
        else:
            sample_size = max(2, int(floor(len(points) * self.subsample_fraction)))
            samples = []
            for seed in self.seeds:
                indices = sorted(np.random.default_rng(seed).choice(len(points), size=sample_size, replace=False).tolist())
                sample = [points[index] for index in indices]
                summary = self._summary(self._leave_one_out(sample))
                rows.append({"seed": seed, "effective_sample_count": len(sample), **summary})
                samples.append(summary)
        def metric_range(key):
            values = [item[key] for item in samples if item[key] is not None]
            return None if not values else [min(values), max(values)]
        return {
            "sampling": "without_replacement",
            "runs": rows,
            "effective_sample_count_range": None if not rows else [min(row["effective_sample_count"] for row in rows), max(row["effective_sample_count"] for row in rows)],
            "median_distance_range_km": metric_range("median_km"),
            "q90_range_km": metric_range("q90_km"),
            "q95_range_km": metric_range("q95_km"),
            "maximum_range_km": metric_range("maximum_km"),
        }

    @staticmethod
    def _aggregate_operating_points(folds):
        output = {}
        for label in ("q90", "q95", "q97_5"):
            rows = [fold["candidate_operating_points"][label] for fold in folds]
            total = sum(row["held_out_count"] for row in rows)
            above = sum(row["held_out_above_count"] for row in rows)
            values = [row["candidate_value_km"] for row in rows if row["candidate_value_km"] is not None]
            output[label] = {
                "candidate_value_range_km": None if not values else [min(values), max(values)],
                "known_occurrence_above_count": above,
                "known_occurrence_count": total,
                "known_occurrence_above_proportion": None if not total else above / total,
                "terminology": "KNOWN_OCCURRENCE_FALSE_FLAG_PROXY",
                "production_threshold": False,
            }
        return output

    @staticmethod
    def _distances(query_points, training_points):
        if not training_points:
            return []
        return [
            min(haversine_km(point.latitude, point.longitude, candidate.latitude, candidate.longitude) for candidate in training_points)
            for point in query_points
        ]

    @classmethod
    def _leave_one_out(cls, points):
        return [
            min(haversine_km(point.latitude, point.longitude, candidate.latitude, candidate.longitude) for candidate_index, candidate in enumerate(points) if candidate_index != index)
            for index, point in enumerate(points)
        ] if len(points) > 1 else []

    @staticmethod
    def _summary(values):
        if not values:
            return {key: None for key in ("n", "minimum_km", "median_km", "mean_km", "q75_km", "q90_km", "q95_km", "maximum_km")}
        return {
            "n": len(values), "minimum_km": min(values),
            "median_km": statistics.median(values), "mean_km": statistics.mean(values),
            "q75_km": float(np.quantile(values, .75)), "q90_km": float(np.quantile(values, .90)),
            "q95_km": float(np.quantile(values, .95)), "maximum_km": max(values),
        }

    @staticmethod
    def _held_to_training_cells(held, training, resolution):
        cells = sorted({(
            round(floor(point.latitude / resolution) * resolution + resolution / 2, 10),
            round(floor(point.longitude / resolution) * resolution + resolution / 2, 10),
        ) for point in training})
        distances = [] if not cells else [
            min(haversine_km(point.latitude, point.longitude, latitude, longitude) for latitude, longitude in cells)
            for point in held
        ]
        return {"training_occupied_cell_count": len(cells), "held_out_nearest_cell_distance_summary": GeographicBaselineValidator._summary(distances)}

    def _report(self, variant, method, folds, fold_configuration, seed_configuration, descriptive, stability, operating, uncertainty):
        provenance = {
            "experimental_only": True, "species": variant.species,
            "jurisdiction_id": variant.jurisdiction_id, "input_variant": variant.name,
            "candidate_method": method, "validation_method_version": VALIDATION_METHOD_VERSION,
            "input_fingerprint": variant.input_fingerprint,
            "fold_configuration": fold_configuration, "seed_configuration": seed_configuration,
            "fold_fingerprints": [fold.fingerprint for fold in folds],
            "external_validation_source": None,
        }
        payload = {
            "provenance": provenance, "descriptive": descriptive,
            "stability": stability, "operating": operating, "uncertainty": uncertainty,
        }
        provenance_json = canonical_json(provenance)
        return GeographicValidationReport(
            species=variant.species, jurisdiction_id=variant.jurisdiction_id,
            input_variant=variant.name, candidate_method=method,
            validation_method_version=VALIDATION_METHOD_VERSION,
            validation_status="EXPERIMENTAL",
            fold_configuration_json=canonical_json(fold_configuration),
            seed_configuration_json=canonical_json(seed_configuration),
            input_fingerprint=variant.input_fingerprint,
            fold_fingerprints=tuple(fold.fingerprint for fold in folds),
            descriptive_metrics_json=canonical_json(descriptive),
            stability_metrics_json=canonical_json(stability),
            operating_point_analysis_json=canonical_json(operating),
            uncertainty_json=canonical_json(uncertainty), provenance_json=provenance_json,
            result_fingerprint=hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            limitations=(
                "Known-occurrence holdout is a false-flag proxy, not anomaly accuracy.",
                "Candidate quantiles are descriptive and are not production thresholds.",
                "Sampling effort, biological absence, and independent validation are unavailable.",
                "Subsampling ranges are not confidence intervals.",
            ),
        )


__all__ = [
    "GeographicBaselineValidator", "GeographicValidationReport", "SpatialFold",
    "IndependentValidationInput", "ExpertGeographicCase", "VALIDATION_METHOD_VERSION",
]
