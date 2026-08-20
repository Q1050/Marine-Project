from collections import Counter
from datetime import datetime, timezone
from math import floor
import random

import numpy as np

from geographic_utils import haversine_km
from models import HabitatSuitabilityV3GridCell, PredictionTrainingOccurrence
from next_area_prediction_service import NextAreaPredictionService


EXPERIMENT_LABEL = (
    "retrospective monitoring-priority logic evaluation using a fixed habitat "
    "suitability surface"
)
LIMITATIONS = [
    "OBIS occurrence data represents recorded presence, not systematic absence.",
    "Lack of a future OBIS record does not establish species absence.",
    "Suitability-v3 contains information derived from records later than some historical cutoffs, so this is not a fully temporally independent model validation.",
    "Results evaluate whether monitoring-priority ranking aligns with subsequently recorded occurrences.",
    "Monitoring-priority scores are not spread probabilities.",
]


class NextAreaBacktestService:

    def __init__(self, random_seed=20260816, random_permutations=500):
        self.production = NextAreaPredictionService()
        self.random_seed = random_seed
        self.random_permutations = random_permutations

    @staticmethod
    def grid_cell_id(latitude, longitude):
        return f"{floor(latitude / 0.1)}:{floor(longitude / 0.1)}"

    @staticmethod
    def _deduplicate(rows):
        unique = {}
        for row in rows:
            key = (
                round(row.latitude, 7), round(row.longitude, 7),
                row.event_date.isoformat(), row.scientific_name,
            )
            unique.setdefault(key, row)
        return sorted(unique.values(), key=lambda row: (row.event_date, row.id))

    def _yearly(self, rows):
        counts = Counter(row.event_date.year for row in rows)
        new_counts = Counter()
        seen = set()
        for row in rows:
            cell = self.grid_cell_id(row.latitude, row.longitude)
            if cell not in seen:
                new_counts[row.event_date.year] += 1
                seen.add(cell)
        return [
            {
                "year": year,
                "records": counts[year],
                "newly_occupied_0_1_degree_cells": new_counts[year],
            }
            for year in sorted(counts)
        ]

    def _select_windows(self, rows):
        years = range(min(row.event_date.year for row in rows), max(row.event_date.year for row in rows))
        candidates = []
        for cutoff_year in years:
            cutoff = datetime(cutoff_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            end_year = min(cutoff_year + 2, max(row.event_date.year for row in rows))
            evaluation_end = datetime(end_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            historical = [row for row in rows if self._aware(row.event_date) <= cutoff]
            future = [row for row in rows if cutoff < self._aware(row.event_date) <= evaluation_end]
            occupied = {self.grid_cell_id(row.latitude, row.longitude) for row in historical}
            future_cells = {self.grid_cell_id(row.latitude, row.longitude) for row in future}
            new_cells = future_cells - occupied
            if historical and len(future) >= 2 and new_cells:
                candidates.append({
                    "cutoff_year": cutoff_year,
                    "cutoff": cutoff,
                    "evaluation_end": evaluation_end,
                    "new_count": len(new_cells),
                })
        selected = []
        for candidate in sorted(candidates, key=lambda item: (-item["new_count"], item["cutoff_year"])):
            interval = (candidate["cutoff_year"] + 1, candidate["evaluation_end"].year)
            if any(not (interval[1] < other[0] or interval[0] > other[1]) for other in [item["interval"] for item in selected]):
                continue
            selected.append(candidate | {"interval": interval})
            if len(selected) == 3:
                break
        return sorted(selected, key=lambda item: item["cutoff"])

    @staticmethod
    def _aware(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def _historical_evidence_score(self, cell, historical, cutoff):
        contributions = []
        for occurrence in historical:
            distance = haversine_km(
                cell.latitude, cell.longitude,
                occurrence.latitude, occurrence.longitude,
            )
            distance_weight = self.production.distance_weight(distance)
            age_days = (cutoff - self._aware(occurrence.event_date)).total_seconds() / 86400
            recency_weight = self.production.recency_weight(max(0.0, age_days))
            contributions.append(recency_weight * distance_weight)
        return max(contributions, default=0.0)

    @staticmethod
    def _rank(cells, score_name):
        return sorted(
            cells,
            key=lambda item: (-item[score_name], item["grid_cell_id"]),
        )

    @staticmethod
    def _distance_to_top(future_cell, top, grid_lookup):
        future = grid_lookup[future_cell]
        return min(
            (haversine_km(future.latitude, future.longitude, cell["latitude"], cell["longitude"]) for cell in top),
            default=None,
        )

    def _metrics(self, ranking, future_new, grid_lookup, tolerance_km=16.0):
        rank_by_cell = {item["grid_cell_id"]: index for index, item in enumerate(ranking, 1)}
        exact_ranks = [rank_by_cell[cell] for cell in sorted(future_new) if cell in rank_by_cell]
        output = {
            "future_cell_ranks": {cell: rank_by_cell.get(cell) for cell in sorted(future_new)},
            "median_future_cell_rank": float(np.median(exact_ranks)) if exact_ranks else None,
            "mean_future_cell_rank": float(np.mean(exact_ranks)) if exact_ranks else None,
            "exact": {},
            "tolerance": {"distance_km": tolerance_km},
            "distance_from_future_cells_to_recommendations_km": {},
        }
        for k in (10, 20, 50):
            top = ranking[:k]
            top_ids = {item["grid_cell_id"] for item in top}
            exact_matches = top_ids & future_new
            predicted_tolerance_matches = {
                item["grid_cell_id"] for item in top
                if any(
                    haversine_km(
                        item["latitude"], item["longitude"],
                        grid_lookup[future].latitude, grid_lookup[future].longitude,
                    ) <= tolerance_km
                    for future in future_new
                )
            }
            future_tolerance_matches = {
                future for future in future_new
                if any(
                    haversine_km(
                        item["latitude"], item["longitude"],
                        grid_lookup[future].latitude, grid_lookup[future].longitude,
                    ) <= tolerance_km
                    for item in top
                )
            }
            output["exact"][f"at_{k}"] = {
                "hit_rate": 1.0 if exact_matches else 0.0,
                "precision": len(exact_matches) / k,
                "recall": len(exact_matches) / len(future_new) if future_new else None,
                "matched_future_cells": len(exact_matches),
            }
            output["tolerance"][f"at_{k}"] = {
                "hit_rate": 1.0 if future_tolerance_matches else 0.0,
                "precision": len(predicted_tolerance_matches) / k,
                "recall": len(future_tolerance_matches) / len(future_new) if future_new else None,
                "matched_future_cells": len(future_tolerance_matches),
            }
            output["distance_from_future_cells_to_recommendations_km"][f"top_{k}"] = {
                future: self._distance_to_top(future, top, grid_lookup)
                for future in sorted(future_new)
            }
        return output

    def _random_baseline(self, candidates, future_new, grid_lookup, window_index):
        results = []
        for iteration in range(self.random_permutations):
            ranking = list(candidates)
            random.Random(self.random_seed + window_index * 100000 + iteration).shuffle(ranking)
            results.append(self._metrics(ranking, future_new, grid_lookup))
        aggregate = {"permutations": self.random_permutations, "seed": self.random_seed}
        for matching in ("exact", "tolerance"):
            aggregate[matching] = {}
            for k in (10, 20, 50):
                aggregate[matching][f"at_{k}"] = {
                    metric: float(np.mean([
                        result[matching][f"at_{k}"][metric] for result in results
                    ]))
                    for metric in ("hit_rate", "precision", "recall")
                }
        ranks = [result["median_future_cell_rank"] for result in results if result["median_future_cell_rank"] is not None]
        aggregate["mean_of_median_future_cell_rank"] = float(np.mean(ranks)) if ranks else None
        return aggregate

    def partition_window(self, rows, cutoff, evaluation_end):
        historical = [row for row in rows if self._aware(row.event_date) <= cutoff]
        future = [
            row for row in rows
            if cutoff < self._aware(row.event_date) <= evaluation_end
        ]
        occupied = {self.grid_cell_id(row.latitude, row.longitude) for row in historical}
        future_cells = {self.grid_cell_id(row.latitude, row.longitude) for row in future}
        return historical, future, occupied, future_cells, future_cells - occupied

    def score_candidates(self, grid, occupied, historical, cutoff):
        candidates = []
        for cell in grid:
            if cell.grid_cell_id in occupied:
                continue
            evidence = self._historical_evidence_score(cell, historical, cutoff)
            candidates.append({
                "grid_cell_id": cell.grid_cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "suitability_score": cell.suitability_score,
                "historical_current_evidence_score": evidence,
                "combined_v1_score": 0.55 * cell.suitability_score + 0.45 * evidence,
            })
        return candidates

    def run(self, db, scientific_name="Pterois volitans"):
        source = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name,
            PredictionTrainingOccurrence.event_date.is_not(None),
        ).order_by(PredictionTrainingOccurrence.event_date, PredictionTrainingOccurrence.id).all()
        clean = self._deduplicate(source)
        grid = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
            HabitatSuitabilityV3GridCell.model_version == "pterois-volitans-suitability-v3",
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        ).all()
        grid_lookup = {cell.grid_cell_id: cell for cell in grid}
        domain_rows = [row for row in clean if self.grid_cell_id(row.latitude, row.longitude) in grid_lookup]
        windows = self._select_windows(domain_rows)
        reports = []
        for window_index, window in enumerate(windows):
            cutoff = window["cutoff"]
            end = window["evaluation_end"]
            historical, future, occupied, future_cells, future_new = self.partition_window(
                domain_rows, cutoff, end
            )
            candidates = self.score_candidates(grid, occupied, historical, cutoff)
            methods = {}
            for name, score_name in (
                ("suitability_only", "suitability_score"),
                ("evidence_only", "historical_current_evidence_score"),
                ("combined_v1", "combined_v1_score"),
            ):
                methods[name] = self._metrics(
                    self._rank(candidates, score_name), future_new, grid_lookup
                )
            methods["random_baseline"] = self._random_baseline(
                candidates, future_new, grid_lookup, window_index
            )
            reports.append({
                "cutoff": cutoff.date().isoformat(),
                "evaluation_start": datetime(cutoff.year + 1, 1, 1).date().isoformat(),
                "evaluation_end": end.date().isoformat(),
                "historical_records_available": len(historical),
                "historically_occupied_cells": len(occupied),
                "future_records": len(future),
                "future_occupied_cells": len(future_cells),
                "future_new_occupied_cells": len(future_new),
                "future_new_cell_ids": sorted(future_new),
                "eligible_candidate_cells": len(candidates),
                "results": methods,
            })
        return {
            "experiment": EXPERIMENT_LABEL,
            "limitations": LIMITATIONS,
            "spatial_domain": "391 scored Jamaica marine cells from suitability-v3",
            "historical_evidence_adaptation": (
                "OBIS has no platform-equivalent verification state. Each unique valid occurrence is assigned uniform verification weight 1.0; production recency and distance weights are retained, and max contribution is used."
            ),
            "matching_definitions": {
                "hit_rate_at_k": "1 when at least one future-new cell is matched in Top-K, otherwise 0",
                "precision_at_k": "matched recommended cells divided by K",
                "recall_at_k": "unique matched future-new cells divided by all future-new cells",
                "exact": "same 0.1-degree cell",
                "tolerance": "recommended center within 16 km of a future-new cell center; 16 km covers the diagonal between touching 0.1-degree cells near Jamaica",
            },
            "random_baseline": {
                "seed": self.random_seed,
                "permutations_per_window": self.random_permutations,
            },
            "data": {
                "dated_source_records": len(source),
                "unique_coordinate_date_records_used": len(clean),
                "duplicate_coordinate_date_records_removed": len(source) - len(clean),
                "date_range": {
                    "earliest": clean[0].event_date.isoformat(),
                    "latest": clean[-1].event_date.isoformat(),
                },
                "caribbean_by_year": self._yearly(clean),
                "jamaica_grid_records": len(domain_rows),
                "jamaica_grid_occupied_cells": len({self.grid_cell_id(row.latitude, row.longitude) for row in domain_rows}),
                "jamaica_grid_by_year": self._yearly(domain_rows),
            },
            "window_selection": (
                "Up to three non-overlapping two-year evaluation periods, prioritized by number of future-new Jamaica cells; each requires prior evidence, at least two future records, and at least one future-new cell."
            ),
            "windows": reports,
        }
