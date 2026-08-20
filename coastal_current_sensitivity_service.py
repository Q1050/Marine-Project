from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from geographic_utils import haversine_km
from historical_directional_backtest_service import (
    DEPTH_M,
    PROVIDER,
    HistoricalDirectionalBacktestService,
)
from models import HabitatSuitabilityV3GridCell, PredictionTrainingOccurrence
from ocean_current_service import toward_bearing_degrees, vector_speed


WINDOWS = (
    ("PRIMARY_NON_OVERLAPPING", datetime(2016, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2018, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    ("PRIMARY_NON_OVERLAPPING", datetime(2020, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    ("OVERLAPPING_DIAGNOSTIC", datetime(2021, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    ("ADDITIONAL_NON_OVERLAPPING_DIAGNOSTIC", datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
)
MAX_FALLBACK_KM = 10.0


def circular_spread_degrees(bearings):
    if len(bearings) < 2:
        return 0.0
    ordered = sorted(value % 360 for value in bearings)
    gaps = [ordered[index + 1] - ordered[index] for index in range(len(ordered) - 1)]
    gaps.append(ordered[0] + 360 - ordered[-1])
    return 360.0 - max(gaps)


class CoastalCurrentSensitivityService(HistoricalDirectionalBacktestService):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_metadata = {}
        for path in Path("current_data/copernicus/glorys12v1/daily").rglob("*.nc.metadata.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            self.cache_metadata[item["represented_date"]] = item

    def _valid_points(self, source):
        represented_date = source.event_date.date().isoformat()
        metadata = self.cache_metadata.get(represented_date)
        if not metadata:
            return metadata, []
        with netcdf_file(metadata["cache_file"], "r", mmap=False) as dataset:
            latitudes = dataset.variables["latitude"].data.copy()
            longitudes = dataset.variables["longitude"].data.copy()
            u_values = dataset.variables["u"].data.copy()
            v_values = dataset.variables["v"].data.copy()
        points = []
        for latitude_index, longitude_index in zip(*np.where(np.isfinite(u_values) & np.isfinite(v_values))):
            latitude = float(latitudes[latitude_index])
            longitude = float(longitudes[longitude_index])
            distance = haversine_km(source.latitude, source.longitude, latitude, longitude)
            if distance <= MAX_FALLBACK_KM:
                u = float(u_values[latitude_index, longitude_index])
                v = float(v_values[latitude_index, longitude_index])
                points.append({
                    "latitude": latitude, "longitude": longitude,
                    "distance_km": distance, "u": u, "v": v,
                    "speed": vector_speed(u, v),
                    "toward_bearing_degrees": toward_bearing_degrees(u, v),
                })
        return metadata, sorted(points, key=lambda item: (item["distance_km"], item["latitude"], item["longitude"]))

    def fallback_current(self, source, direct):
        metadata, points = self._valid_points(source)
        if not points:
            return None, {
                "occurrence_id": source.id,
                "source_cell": self.existing.grid_cell_id(source.latitude, source.longitude),
                "occurrence_coordinate": [source.latitude, source.longitude],
                "represented_date": source.event_date.date().isoformat(),
                "original_direct_status": direct["status"],
                "sampling_method": "MISSING",
            }, None
        selected = points[0]
        current = {
            "status": "VALID", "u": selected["u"], "v": selected["v"],
            "speed": selected["speed"],
            "toward_bearing_degrees": selected["toward_bearing_degrees"],
            "source_latitude": selected["latitude"],
            "source_longitude": selected["longitude"],
            "spatial_distance_km": selected["distance_km"],
            "source_timestamp": None,
            "represented_date": source.event_date.date().isoformat(),
            "temporal_representation": "DAILY_MEAN",
            "temporal_difference_seconds": None,
            "source_depth_m": metadata["source_depth_m"],
            "provider": metadata["provider"], "product": metadata["product"],
            "dataset_id": metadata["dataset_id"],
            "sampling_method": "NEAREST_VALID_SENSITIVITY",
            "missing_or_masked": False,
        }
        audit = {
            "occurrence_id": source.id,
            "source_cell": self.existing.grid_cell_id(source.latitude, source.longitude),
            "occurrence_coordinate": [source.latitude, source.longitude],
            "represented_date": source.event_date.date().isoformat(),
            "original_direct_status": direct["status"],
            "selected_latitude": selected["latitude"],
            "selected_longitude": selected["longitude"],
            "fallback_distance_km": selected["distance_km"],
            "u": selected["u"], "v": selected["v"],
            "speed": selected["speed"],
            "toward_bearing_degrees": selected["toward_bearing_degrees"],
            "sampling_method": "NEAREST_VALID_SENSITIVITY",
        }
        bearings = [point["toward_bearing_degrees"] for point in points]
        maximum_difference = max(
            abs((bearing - selected["toward_bearing_degrees"] + 180) % 360 - 180)
            for bearing in bearings
        )
        stability = {
            "occurrence_id": source.id,
            "source_cell": audit["source_cell"],
            "represented_date": audit["represented_date"],
            "valid_points_within_10_km": points,
            "point_count": len(points),
            "circular_bearing_spread_degrees": circular_spread_degrees(bearings),
            "maximum_selected_to_neighbor_difference_degrees": maximum_difference,
            "selected_appears_directionally_similar": maximum_difference <= 30.0,
            "similarity_rule": "diagnostic only: every local bearing within 30 degrees of selected bearing",
        }
        return current, audit, stability

    def _cohort(self, historical, allow_fallback):
        eligible, direct_count, fallback_count, missing = [], 0, 0, []
        fallback_audits, stability = [], []
        for source in historical:
            direct = self.lookup.get_current(
                source.latitude, source.longitude, self.existing._aware(source.event_date),
                DEPTH_M, provider=PROVIDER,
            )
            if direct["status"] == "VALID":
                eligible.append((source, direct, None))
                direct_count += 1
            elif allow_fallback and direct["status"] == "MISSING_PROVIDER_VALUE":
                current, audit, diagnostic = self.fallback_current(source, direct)
                fallback_audits.append(audit)
                if diagnostic:
                    stability.append(diagnostic)
                if current:
                    eligible.append((source, current, audit))
                    fallback_count += 1
                else:
                    missing.append(audit)
            else:
                missing.append({"occurrence_id": source.id, "status": direct["status"]})
        return eligible, direct_count, fallback_count, missing, fallback_audits, stability

    def _evaluate(self, candidates, sources, future_new, grid_lookup, window_index):
        scored = self._score_direction(candidates, sources)
        d1_ranking = self._rank(scored, "direction_score")
        d2_ranking = self._rank(scored, "distance_limited_direction_score", True)
        metrics = {
            "d1": self.existing._metrics(d1_ranking, future_new, grid_lookup),
            "d2": self.existing._metrics(d2_ranking, future_new, grid_lookup),
        }
        ranks = {
            label: {row["grid_cell_id"]: rank for rank, row in enumerate(ranking, 1)}
            for label, ranking in (("d1", d1_ranking), ("d2", d2_ranking))
        }
        control = self._negative_control(candidates, sources, future_new, grid_lookup, window_index)
        for label in ("d1", "d2"):
            real_median = metrics[label]["median_future_cell_rank"]
            random_medians = control[label].pop("_median_rank_values")
            control[label]["real_median_future_rank"] = real_median
            control[label]["empirical_fraction_random_median_rank_as_good_or_better"] = (
                sum(value <= real_median for value in random_medians) / len(random_medians)
                if random_medians and real_median is not None else None
            )
            random_cell_values = control[label].pop("_per_future_cell_rank_values")
            for cell in sorted(future_new):
                values = random_cell_values[cell]
                control[label]["per_future_cell_rank"][cell].update({
                    "real_rank": ranks[label][cell],
                    "empirical_fraction_random_rank_as_good_or_better": (
                        sum(value <= ranks[label][cell] for value in values) / len(values) if values else None
                    ),
                })
        return {"metrics": metrics, "ranks": ranks, "randomized_bearing_control": control}

    @staticmethod
    def _differences(primary, sensitivity, future_new):
        differences = {"future_cell_rank_changes": {}, "top_k_hit_changes": {}}
        for cell in sorted(future_new):
            differences["future_cell_rank_changes"][cell] = {
                label: {
                    "primary": primary["ranks"][label][cell],
                    "sensitivity": sensitivity["ranks"][label][cell],
                    "improvement": primary["ranks"][label][cell] - sensitivity["ranks"][label][cell],
                }
                for label in ("d1", "d2")
            }
        for label in ("d1", "d2"):
            differences["top_k_hit_changes"][label] = {}
            for matching in ("exact", "tolerance"):
                differences["top_k_hit_changes"][label][matching] = {
                    f"at_{k}": {
                        "primary": primary["metrics"][label][matching][f"at_{k}"]["matched_future_cells"],
                        "sensitivity": sensitivity["metrics"][label][matching][f"at_{k}"]["matched_future_cells"],
                    }
                    for k in (10, 20, 50)
                }
        return differences

    def run_sensitivity(self, db, scientific_name="Pterois volitans"):
        source_rows = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name,
            PredictionTrainingOccurrence.event_date.is_not(None),
        ).order_by(PredictionTrainingOccurrence.event_date, PredictionTrainingOccurrence.id).all()
        clean = self.existing._deduplicate(source_rows)
        grid = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
            HabitatSuitabilityV3GridCell.model_version == "pterois-volitans-suitability-v3",
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        ).all()
        grid_lookup = {cell.grid_cell_id: cell for cell in grid}
        domain = [row for row in clean if self.existing.grid_cell_id(row.latitude, row.longitude) in grid_lookup]
        reports, all_audits, all_stability = [], {}, {}
        for window_index, (label, cutoff, evaluation_end) in enumerate(WINDOWS):
            historical, future, occupied, future_cells, future_new = self.existing.partition_window(domain, cutoff, evaluation_end)
            candidates = self.existing.score_candidates(grid, occupied, historical, cutoff)
            direct, direct_count, _, direct_missing, _, _ = self._cohort(historical, False)
            sensitivity, sensitivity_direct, fallback_count, sensitivity_missing, audits, stability = self._cohort(historical, True)
            for audit in audits:
                all_audits[audit["occurrence_id"]] = audit
            for diagnostic in stability:
                all_stability[(diagnostic["occurrence_id"], diagnostic["represented_date"])] = diagnostic
            # Pair primary and sensitivity controls with the same per-window
            # rotation stream so differences reflect cohort sampling only.
            primary = self._evaluate(candidates, direct, future_new, grid_lookup, window_index)
            coastal = self._evaluate(candidates, sensitivity, future_new, grid_lookup, window_index)
            fallback_to_future = []
            for source, current, audit in sensitivity:
                if not audit:
                    continue
                for cell in sorted(future_new):
                    destination = grid_lookup[cell]
                    connection = self.directional.calculate_with_current(
                        source.latitude, source.longitude,
                        destination.latitude, destination.longitude, current,
                    )
                    fallback_to_future.append({
                        "source_occurrence_id": source.id,
                        "source_date": source.event_date.date().isoformat(),
                        "future_cell": cell,
                        "distance_km": connection["source_to_candidate_distance_km"],
                        "current_bearing_degrees": connection["current_toward_bearing_degrees"],
                        "destination_bearing_degrees": connection["source_to_candidate_bearing_degrees"],
                        "angular_difference_degrees": connection["angular_difference_degrees"],
                        "downstream_alignment": connection["downstream_alignment"],
                    })
            reports.append({
                "window_label": label, "cutoff": cutoff.date().isoformat(),
                "evaluation_start": f"{cutoff.year + 1}-01-01", "evaluation_end": evaluation_end.date().isoformat(),
                "future_records": len(future), "future_new_cells": sorted(future_new),
                "coverage": {
                    "source_records": len(historical), "direct_vectors": sensitivity_direct,
                    "fallback_vectors": fallback_count, "still_missing": len(sensitivity_missing),
                    "unique_source_dates_represented": len({source.event_date.date() for source, _, _ in sensitivity}),
                    "unique_source_cells_represented": len({self.existing.grid_cell_id(source.latitude, source.longitude) for source, _, _ in sensitivity}),
                },
                "primary_direct_only": primary,
                "coastal_nearest_valid_sensitivity": coastal,
                "differences": self._differences(primary, coastal, future_new),
                "fallback_to_future_cell_diagnostics": fallback_to_future,
            })
        return {
            "experiment": "COASTAL_NEAREST_VALID_SENSITIVITY",
            "primary_experiment_unchanged": "directional_connectivity_backtest_glorys_v1.json",
            "fallback_policy": {
                "maximum_distance_km": MAX_FALLBACK_KM, "same_date": True,
                "same_depth_provider_product_version": True, "interpolation": False,
                "averaging": False, "hycom": False, "persistence": False,
            },
            "fallback_lookup_audit": sorted(all_audits.values(), key=lambda item: item["occurrence_id"]),
            "local_vector_stability": sorted(all_stability.values(), key=lambda item: (item["represented_date"], item["occurrence_id"])),
            "windows": reports,
            "interpretation": "Environmental surface-current masking sensitivity only; not organism movement, dispersal, spread, or occurrence probability.",
        }
