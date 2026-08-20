from collections import defaultdict
from datetime import datetime, timezone
import math
import random

import numpy as np
from scipy.stats import mannwhitneyu

from directional_connectivity_service import (
    DirectionalConnectivityService,
    alignment_from_bearings,
)
from models import HabitatSuitabilityV3GridCell, PredictionTrainingOccurrence
from next_area_backtest_service import NextAreaBacktestService
from ocean_current_service import OceanCurrentLookupService


WINDOWS = (
    (datetime(2016, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2018, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
    (datetime(2020, 12, 31, 23, 59, 59, tzinfo=timezone.utc), datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
)
DEPTH_M = 0.494025
PROVIDER = "COPERNICUS_MARINE"
SEED = 20260816
PERMUTATIONS = 500
DISTANCE_BANDS = (
    ("0-10", 0.0, 10.0),
    (">10-25", 10.0, 25.0),
    (">25-50", 25.0, 50.0),
    (">50-100", 50.0, 100.0),
    (">100", 100.0, math.inf),
)


def summary(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "q1": None, "q3": None}
    array = np.asarray(values, dtype=float)
    return {
        "count": len(values), "mean": float(np.mean(array)),
        "median": float(np.median(array)), "q1": float(np.percentile(array, 25)),
        "q3": float(np.percentile(array, 75)),
    }


class HistoricalDirectionalBacktestService:

    def __init__(self, seed=SEED, permutations=PERMUTATIONS):
        self.existing = NextAreaBacktestService(random_seed=seed, random_permutations=permutations)
        self.lookup = OceanCurrentLookupService()
        self.directional = DirectionalConnectivityService(self.lookup)
        self.seed = seed
        self.permutations = permutations

    @staticmethod
    def _rank(cells, score, nullable=False):
        return sorted(cells, key=lambda item: (
            item.get(score) is None if nullable else False,
            -(item.get(score) if item.get(score) is not None else -math.inf),
            item["grid_cell_id"],
        ))

    @staticmethod
    def _winner_payload(source, connection):
        return {
            "source_occurrence_id": source.id,
            "source_date": source.event_date.isoformat(),
            "source_coordinate": [source.latitude, source.longitude],
            "destination_coordinate": [connection["candidate"]["latitude"], connection["candidate"]["longitude"]],
            "distance_km": connection["source_to_candidate_distance_km"],
            "u": connection["u"], "v": connection["v"],
            "current_speed": connection["current_speed"],
            "current_toward_bearing_degrees": connection["current_toward_bearing_degrees"],
            "source_to_destination_bearing_degrees": connection["source_to_candidate_bearing_degrees"],
            "angular_difference_degrees": connection["angular_difference_degrees"],
            "alignment": connection["alignment"],
            "downstream_alignment": connection["downstream_alignment"],
            "speed_weighted_alignment": connection["speed_weighted_alignment"],
            "provider": connection["provider"], "dataset_id": connection["dataset_id"],
            "represented_date": connection.get("represented_date", source.event_date.date().isoformat()),
            "temporal_representation": "DAILY_MEAN",
            "current_depth_m": connection["current_depth_m"],
            "current_sampling_method": connection["current_sampling_method"],
        }

    def _sources(self, historical):
        eligible, excluded = [], []
        for source in historical:
            current = self.lookup.get_current(
                source.latitude, source.longitude, self.existing._aware(source.event_date),
                DEPTH_M, provider=PROVIDER,
            )
            item = {
                "occurrence_id": source.id,
                "date": source.event_date.isoformat(),
                "grid_cell_id": self.existing.grid_cell_id(source.latitude, source.longitude),
                "latitude": source.latitude, "longitude": source.longitude,
                "lookup_status": current["status"],
                "represented_date": current.get("represented_date"),
                "temporal_representation": current.get("temporal_representation"),
                "u": current.get("u"), "v": current.get("v"),
                "speed": current.get("speed"),
                "toward_bearing_degrees": current.get("toward_bearing_degrees"),
                "sampling_method": current.get("sampling_method"),
                "lookup_distance_km": current.get("spatial_distance_km"),
            }
            if current["status"] == "VALID" and current.get("represented_date") == source.event_date.date().isoformat():
                eligible.append((source, current, item))
            else:
                excluded.append(item)
        return eligible, excluded

    def _score_direction(self, candidates, sources):
        scored = []
        for candidate in candidates:
            contributions = []
            for source, current, _ in sources:
                connection = self.directional.calculate_with_current(
                    source.latitude, source.longitude, candidate["latitude"], candidate["longitude"], current
                )
                contributions.append((source, connection))
            d1_source, d1 = max(contributions, key=lambda pair: (pair[1]["downstream_alignment"], -pair[0].id))
            within = [pair for pair in contributions if pair[1]["source_to_candidate_distance_km"] <= 100.0]
            d2_pair = max(within, key=lambda pair: (pair[1]["downstream_alignment"], -pair[0].id)) if within else None
            speed_source, speed = max(contributions, key=lambda pair: (pair[1]["speed_weighted_alignment"], -pair[0].id))
            bands = {}
            for label, low, high in DISTANCE_BANDS:
                choices = [pair for pair in contributions if pair[1]["source_to_candidate_distance_km"] > low and pair[1]["source_to_candidate_distance_km"] <= high]
                if label == "0-10":
                    choices = [pair for pair in contributions if 0 <= pair[1]["source_to_candidate_distance_km"] <= high]
                pair = max(choices, key=lambda value: (value[1]["downstream_alignment"], -value[0].id)) if choices else None
                bands[label] = pair[1]["downstream_alignment"] if pair else None
            row = dict(candidate)
            row.update({
                "direction_score": d1["downstream_alignment"],
                "direction_winner": self._winner_payload(d1_source, d1),
                "distance_limited_direction_score": d2_pair[1]["downstream_alignment"] if d2_pair else None,
                "distance_limited_winner": self._winner_payload(*d2_pair) if d2_pair else None,
                "speed_weighted_alignment": speed["speed_weighted_alignment"],
                "speed_winner": self._winner_payload(speed_source, speed),
                "distance_band_scores": bands,
            })
            scored.append(row)
        return scored

    def _negative_control(self, candidates, sources, future_new, grid_lookup, window_index):
        results = {"d1": [], "d2": []}
        rng = random.Random(self.seed + window_index * 100_000)
        for _ in range(self.permutations):
            rotated = [(source, rng.uniform(0, 360)) for source, _, _ in sources]
            cells = []
            for candidate in candidates:
                contributions = []
                for source, bearing in rotated:
                    connection = self.directional.calculate_with_current(
                        source.latitude, source.longitude, candidate["latitude"], candidate["longitude"],
                        {"status": "VALID", "u": 0.0, "v": 0.0, "speed": 0.0, "toward_bearing_degrees": bearing},
                    )
                    contributions.append(connection)
                d1 = max(value["downstream_alignment"] for value in contributions)
                within = [value["downstream_alignment"] for value in contributions if value["source_to_candidate_distance_km"] <= 100]
                cells.append(dict(candidate, randomized_d1=d1, randomized_d2=max(within) if within else None))
            for label, score, nullable in (("d1", "randomized_d1", False), ("d2", "randomized_d2", True)):
                ranking = self._rank(cells, score, nullable)
                results[label].append(self.existing._metrics(ranking, future_new, grid_lookup))
        output = {"seed": self.seed, "permutations": self.permutations}
        for label, permutations in results.items():
            output[label] = {"exact": {}, "tolerance": {}}
            for matching in ("exact", "tolerance"):
                for k in (10, 20, 50):
                    output[label][matching][f"at_{k}"] = {
                        metric: float(np.mean([p[matching][f"at_{k}"][metric] for p in permutations]))
                        for metric in ("hit_rate", "precision", "recall")
                    }
            output[label]["median_future_rank_distribution"] = summary([
                p["median_future_cell_rank"] for p in permutations if p["median_future_cell_rank"] is not None
            ])
            output[label]["_median_rank_values"] = [
                p["median_future_cell_rank"] for p in permutations if p["median_future_cell_rank"] is not None
            ]
            output[label]["per_future_cell_rank"] = {
                cell: summary([p["future_cell_ranks"][cell] for p in permutations if p["future_cell_ranks"].get(cell) is not None])
                for cell in sorted(future_new)
            }
            output[label]["_per_future_cell_rank_values"] = {
                cell: [p["future_cell_ranks"][cell] for p in permutations if p["future_cell_ranks"].get(cell) is not None]
                for cell in sorted(future_new)
            }
        return output

    def run(self, db, scientific_name="Pterois volitans"):
        rows = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name,
            PredictionTrainingOccurrence.event_date.is_not(None),
        ).order_by(PredictionTrainingOccurrence.event_date, PredictionTrainingOccurrence.id).all()
        clean = self.existing._deduplicate(rows)
        grid = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
            HabitatSuitabilityV3GridCell.model_version == "pterois-volitans-suitability-v3",
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        ).all()
        grid_lookup = {cell.grid_cell_id: cell for cell in grid}
        domain = [row for row in clean if self.existing.grid_cell_id(row.latitude, row.longitude) in grid_lookup]
        reports = []
        for window_index, (cutoff, evaluation_end) in enumerate(WINDOWS):
            historical, future, occupied, future_cells, future_new = self.existing.partition_window(domain, cutoff, evaluation_end)
            sources, excluded = self._sources(historical)
            if excluded:
                raise RuntimeError(f"Authorized window lacks direct current coverage: {excluded}")
            candidates = self.existing.score_candidates(grid, occupied, historical, cutoff)
            scored = self._score_direction(candidates, sources)
            rankings = {
                "suitability": self._rank(scored, "suitability_score"),
                "evidence": self._rank(scored, "historical_current_evidence_score"),
                "combined": self._rank(scored, "combined_v1_score"),
                "d1": self._rank(scored, "direction_score"),
                "d2": self._rank(scored, "distance_limited_direction_score", True),
                "speed_weighted": self._rank(scored, "speed_weighted_alignment"),
            }
            metrics = {name: self.existing._metrics(ranking, future_new, grid_lookup) for name, ranking in rankings.items()}
            metrics["random_candidate"] = self.existing._random_baseline(candidates, future_new, grid_lookup, window_index)
            ranks = {name: {row["grid_cell_id"]: index for index, row in enumerate(ranking, 1)} for name, ranking in rankings.items()}
            future_report = []
            by_id = {row["grid_cell_id"]: row for row in scored}
            for cell in sorted(future_new):
                row = by_id[cell]
                future_report.append({
                    "grid_cell_id": cell,
                    "latitude": row["latitude"], "longitude": row["longitude"],
                    "ranks": {name: rank[cell] for name, rank in ranks.items()},
                    "d1_winning_connection": row["direction_winner"],
                    "d2_winning_connection": row["distance_limited_winner"],
                })
            future_scores = [by_id[cell]["direction_score"] for cell in future_new]
            other_scores = [row["direction_score"] for row in scored if row["grid_cell_id"] not in future_new]
            exploratory = None
            if future_scores and other_scores:
                statistic, pvalue = mannwhitneyu(future_scores, other_scores, alternative="two-sided")
                exploratory = {"test": "Mann-Whitney U, exploratory", "statistic": float(statistic), "two_sided_p_value": float(pvalue)}
            band_results = {}
            for label, _, _ in DISTANCE_BANDS:
                band_rows = [dict(row, band_score=row["distance_band_scores"][label]) for row in scored]
                ranking = self._rank(band_rows, "band_score", True)
                band_results[label] = self.existing._metrics(ranking, future_new, grid_lookup)
            control = self._negative_control(candidates, sources, future_new, grid_lookup, window_index)
            for label in ("d1", "d2"):
                real_median = metrics[label]["median_future_cell_rank"]
                control[label]["real_median_future_rank"] = real_median
                random_medians = control[label].pop("_median_rank_values")
                control[label]["empirical_fraction_random_median_rank_as_good_or_better"] = (
                    sum(value <= real_median for value in random_medians) / len(random_medians)
                    if random_medians and real_median is not None else None
                )
                random_cell_ranks = control[label].pop("_per_future_cell_rank_values")
                for cell in sorted(future_new):
                    random_summary = control[label]["per_future_cell_rank"][cell]
                    control[label]["per_future_cell_rank"][cell]["real_rank"] = ranks[label][cell]
                    control[label]["per_future_cell_rank"][cell]["real_better_than_random_median"] = ranks[label][cell] < random_summary["median"]
                    values = random_cell_ranks[cell]
                    control[label]["per_future_cell_rank"][cell]["empirical_fraction_random_rank_as_good_or_better"] = (
                        sum(value <= ranks[label][cell] for value in values) / len(values) if values else None
                    )
            reports.append({
                "cutoff": cutoff.date().isoformat(),
                "evaluation_start": datetime(cutoff.year + 1, 1, 1).date().isoformat(),
                "evaluation_end": evaluation_end.date().isoformat(),
                "source_cohort": [item for _, _, item in sources],
                "excluded_sources": excluded,
                "future_records": len(future),
                "future_occupied_cells": sorted(future_cells),
                "future_new_cells": sorted(future_new),
                "eligible_candidates": len(candidates),
                "metrics": metrics,
                "future_cell_results": future_report,
                "alignment_distributions": {
                    "future_new": summary(future_scores), "other_candidates": summary(other_scores),
                    "exploratory_comparison": exploratory,
                },
                "distance_band_results": band_results,
                "randomized_bearing_control": control,
            })
        return {
            "experiment": "read-only historical directional-connectivity backtest",
            "current_data": {
                "provider": PROVIDER, "dataset_id": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
                "depth_m": DEPTH_M, "temporal_representation": "DAILY_MEAN",
                "nearest_valid_fallback": False,
            },
            "randomized_bearing_control": {"seed": self.seed, "permutations": self.permutations},
            "interpretation": "Tests alignment with historical environmental surface-current direction; not organism movement, transport, spread, or occurrence probability.",
            "windows": reports,
        }
