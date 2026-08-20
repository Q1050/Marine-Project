from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from database import SessionLocal
from geographic_utils import haversine_km
from models import HabitatSuitabilityV3GridCell, PredictionTrainingOccurrence
from next_area_backtest_service import NextAreaBacktestService


WEIGHTS = ((1, 0), (.9, .1), (.8, .2), (.7, .3), (.6, .4), (.55, .45),
           (.5, .5), (.4, .6), (.3, .7), (.2, .8), (.1, .9), (0, 1))


def recency_band(age_days):
    if age_days <= 7: return "0-7_days"
    if age_days <= 30: return "8-30_days"
    if age_days <= 90: return "31-90_days"
    if age_days <= 365: return "91-365_days"
    return ">365_days"


class NextAreaV1DiagnosticAudit:

    def __init__(self):
        self.backtest = NextAreaBacktestService()
        self.production = self.backtest.production

    def evidence_details(self, cell, historical, cutoff):
        values = []
        for source in historical:
            distance = haversine_km(cell.latitude, cell.longitude, source.latitude, source.longitude)
            distance_weight = self.production.distance_weight(distance)
            age_days = max(0, (cutoff - self.backtest._aware(source.event_date)).total_seconds() / 86400)
            recency_weight = self.production.recency_weight(age_days)
            values.append({
                "source_occurrence_id": source.id, "source_date": source.event_date.isoformat(),
                "source_cell": self.backtest.grid_cell_id(source.latitude, source.longitude),
                "source_coordinate": [source.latitude, source.longitude],
                "distance_km": distance, "verification_weight": 1.0,
                "recency_weight": recency_weight, "recency_band": recency_band(age_days),
                "distance_weight": distance_weight,
                "contribution": recency_weight * distance_weight,
            })
        nearest = min(values, key=lambda item: (item["distance_km"], item["source_occurrence_id"]), default=None)
        qualifying = [item for item in values if item["distance_weight"] > 0]
        winner = max(
            qualifying,
            key=lambda item: (item["contribution"], -item["distance_km"], -item["source_occurrence_id"]),
            default=None,
        )
        return nearest, winner, qualifying

    @staticmethod
    def rank(rows, score):
        return sorted(rows, key=lambda row: (-row[score], row["grid_cell_id"]))

    def analyze_window(self, grid, grid_lookup, domain, window, window_index):
        cutoff, end = window["cutoff"], window["evaluation_end"]
        historical, future, occupied, future_cells, future_new = self.backtest.partition_window(domain, cutoff, end)
        rows = []
        for cell in grid:
            if cell.grid_cell_id in occupied:
                continue
            nearest, winner, qualifying = self.evidence_details(cell, historical, cutoff)
            evidence = winner["contribution"] if winner else 0.0
            rows.append({
                "grid_cell_id": cell.grid_cell_id, "latitude": cell.latitude, "longitude": cell.longitude,
                "suitability_score": cell.suitability_score, "evidence_score": evidence,
                "combined_score": .55 * cell.suitability_score + .45 * evidence,
                "nearest_source": nearest, "winning_source": winner,
                "qualifying_source_count": len(qualifying),
                "qualifying_source_ids": [item["source_occurrence_id"] for item in qualifying],
            })
        rankings = {
            "suitability": self.rank(rows, "suitability_score"),
            "evidence": self.rank(rows, "evidence_score"),
            "combined": self.rank(rows, "combined_score"),
        }
        rank_maps = {name: {row["grid_cell_id"]: index for index, row in enumerate(ranking, 1)} for name, ranking in rankings.items()}
        metrics = {name: self.backtest._metrics(ranking, future_new, grid_lookup) for name, ranking in rankings.items()}
        metrics["random"] = self.backtest._random_baseline(rows, future_new, grid_lookup, window_index)
        by_cell = {row["grid_cell_id"]: row for row in rows}
        future_reports = []
        for cell_id in sorted(future_new):
            row = by_cell[cell_id]
            suit_contribution = .55 * row["suitability_score"]
            evidence_contribution = .45 * row["evidence_score"]
            combined = row["combined_score"]
            suit_rank, evidence_rank, combined_rank = (rank_maps[name][cell_id] for name in ("suitability", "evidence", "combined"))
            flags = []
            flags.append("SUITABILITY_DOMINATES" if suit_contribution > evidence_contribution else "EVIDENCE_DOMINATES" if evidence_contribution > suit_contribution else "EQUAL_CONTRIBUTIONS")
            if combined_rank > suit_rank and combined_rank < evidence_rank: flags.append("SUITABILITY_HELPS_EVIDENCE_HURTS")
            if combined_rank > evidence_rank and combined_rank < suit_rank: flags.append("EVIDENCE_HELPS_SUITABILITY_HURTS")
            if suit_rank <= 50 and evidence_rank <= 50: flags.append("BOTH_AGREE_TOP_50")
            future_reports.append({
                "grid_cell_id": cell_id, "latitude": row["latitude"], "longitude": row["longitude"],
                "suitability_score": row["suitability_score"], "suitability_rank": suit_rank,
                "evidence_score": row["evidence_score"], "evidence_rank": evidence_rank,
                "combined_score": combined, "combined_rank": combined_rank,
                "suitability_contribution": suit_contribution,
                "evidence_contribution": evidence_contribution,
                "suitability_contribution_percent": 100 * suit_contribution / combined if combined else None,
                "evidence_contribution_percent": 100 * evidence_contribution / combined if combined else None,
                "combined_minus_suitability_rank": combined_rank - suit_rank,
                "combined_minus_evidence_rank": combined_rank - evidence_rank,
                "nearest_historical_source_distance_km": row["nearest_source"]["distance_km"] if row["nearest_source"] else None,
                "nearest_historical_source": row["nearest_source"], "winning_historical_source": row["winning_source"],
                "classification_flags": flags,
            })

        top_set_changes = {}
        for k in (10, 20, 50):
            combined = {row["grid_cell_id"] for row in rankings["combined"][:k]}
            top_set_changes[f"top_{k}"] = {}
            for component in ("suitability", "evidence"):
                comparison = {row["grid_cell_id"] for row in rankings[component][:k]}
                top_set_changes[f"top_{k}"][f"combined_vs_{component}"] = {
                    "overlap": len(combined & comparison), "entered": len(combined - comparison),
                    "left": len(comparison - combined),
                }

        sweep, stability = [], []
        production_ranking = rankings["combined"]
        production_rank = {row["grid_cell_id"]: index for index, row in enumerate(production_ranking, 1)}
        for suitability_weight, evidence_weight in WEIGHTS:
            weighted = [dict(row, diagnostic_score=suitability_weight * row["suitability_score"] + evidence_weight * row["evidence_score"]) for row in rows]
            ranking = self.rank(weighted, "diagnostic_score")
            result = self.backtest._metrics(ranking, future_new, grid_lookup)
            sweep.append({"suitability_weight": suitability_weight, "evidence_weight": evidence_weight, "metrics": result})
            rank = {row["grid_cell_id"]: index for index, row in enumerate(ranking, 1)}
            correlation = spearmanr([production_rank[cell] for cell in sorted(production_rank)], [rank[cell] for cell in sorted(rank)]).statistic
            stability.append({
                "suitability_weight": suitability_weight, "evidence_weight": evidence_weight,
                "spearman_vs_55_45": float(correlation),
                **{f"top_{k}_overlap": len({r["grid_cell_id"] for r in ranking[:k]} & {r["grid_cell_id"] for r in production_ranking[:k]}) for k in (10, 20, 50)},
            })

        evidence_counts = Counter(row["evidence_score"] for row in rows)
        distance_counts = Counter(
            row["winning_source"]["distance_weight"] if row["winning_source"] else 0.0 for row in rows
        )
        recency_counts = Counter(
            row["winning_source"]["recency_band"] if row["winning_source"] else "NO_QUALIFYING_SOURCE" for row in rows
        )
        qualifying_counts = Counter(row["qualifying_source_count"] for row in rows)
        winner_ids = {row["grid_cell_id"]: row["winning_source"]["source_occurrence_id"] if row["winning_source"] else None for row in rows}
        adjacent, changes = 0, 0
        coordinates = {(round(row["latitude"], 2), round(row["longitude"], 2)): row["grid_cell_id"] for row in rows}
        for row in rows:
            for delta in ((.1, 0), (0, .1)):
                neighbor = coordinates.get((round(row["latitude"] + delta[0], 2), round(row["longitude"] + delta[1], 2)))
                if neighbor:
                    adjacent += 1
                    changes += winner_ids[row["grid_cell_id"]] != winner_ids[neighbor]

        false_priority = []
        for row in rankings["combined"][:10]:
            if row["grid_cell_id"] in future_cells: continue
            false_priority.append({
                "grid_cell_id": row["grid_cell_id"], "suitability_score": row["suitability_score"],
                "evidence_score": row["evidence_score"], "combined_score": row["combined_score"],
                "suitability_contribution": .55 * row["suitability_score"],
                "evidence_contribution": .45 * row["evidence_score"],
                "nearest_source_distance_km": row["nearest_source"]["distance_km"] if row["nearest_source"] else None,
                "reason_codes": (["HIGH_HABITAT_SUITABILITY"] if row["suitability_score"] >= .6 else []) + (["HISTORICAL_EVIDENCE_WITHIN_100_KM"] if row["winning_source"] else []),
                "subsequent_occurrence_status": "NO_RECORDED_OCCURRENCE_IN_EVALUATION_PERIOD",
            })
        missed = [report for report in future_reports if report["combined_rank"] > 50]

        source_cell_counts = Counter(self.backtest.grid_cell_id(row.latitude, row.longitude) for row in historical)
        return {
            "cutoff": cutoff.date().isoformat(), "evaluation_start": f"{cutoff.year + 1}-01-01",
            "evaluation_end": end.date().isoformat(), "future_new_cells": sorted(future_new),
            "sample": {
                "historical_records": len(historical), "unique_historical_dates": len({row.event_date.date() for row in historical}),
                "unique_historical_cells": len(source_cell_counts), "repeated_records_by_cell": dict(source_cell_counts),
                "future_records": len(future), "future_new_cell_count": len(future_new),
            },
            "reproduction": metrics, "future_cell_explainability": future_reports,
            "rank_displacement": {"future_cells": [{"grid_cell_id": item["grid_cell_id"], "combined_minus_suitability": item["combined_minus_suitability_rank"], "combined_minus_evidence": item["combined_minus_evidence_rank"]} for item in future_reports], "top_set_changes": top_set_changes},
            "error_analysis": {"high_priority_without_subsequent_record": false_priority, "missed_future_new_cells": missed},
            "weight_sensitivity": sweep, "rank_stability": stability,
            "distance_diagnostic": {"winning_distance_weight_counts": {str(k): v for k, v in sorted(distance_counts.items())}, "evidence_score_ties": {str(k): v for k, v in sorted(evidence_counts.items())}, "unique_evidence_scores": len(evidence_counts), "largest_tie_group": max(evidence_counts.values())},
            "recency_diagnostic": {"winning_recency_band_counts": dict(recency_counts)},
            "max_evidence_diagnostic": {
                "candidate_cells_by_qualifying_source_count": {str(k): v for k, v in sorted(qualifying_counts.items())},
                "cells_with_one_qualifying_source": qualifying_counts[1],
                "cells_with_multiple_qualifying_sources": sum(v for k, v in qualifying_counts.items() if k > 1),
                "cells_where_multiple_sources_reduce_to_one_winner": sum(v for k, v in qualifying_counts.items() if k > 1),
                "adjacent_candidate_pairs": adjacent, "adjacent_pairs_with_winner_change": changes,
                "winner_change_percent": 100 * changes / adjacent if adjacent else None,
            },
        }

    def run(self, db):
        source = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == "Pterois volitans",
            PredictionTrainingOccurrence.event_date.is_not(None),
        ).order_by(PredictionTrainingOccurrence.event_date, PredictionTrainingOccurrence.id).all()
        clean = self.backtest._deduplicate(source)
        grid = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == "Pterois volitans",
            HabitatSuitabilityV3GridCell.model_version == "pterois-volitans-suitability-v3",
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        ).all()
        grid_lookup = {cell.grid_cell_id: cell for cell in grid}
        domain = [row for row in clean if self.backtest.grid_cell_id(row.latitude, row.longitude) in grid_lookup]
        selected = self.backtest._select_windows(domain)
        windows = [self.analyze_window(grid, grid_lookup, domain, window, index) for index, window in enumerate(selected)]
        future_sets = [{*window["future_new_cells"]} for window in windows]
        return {
            "experiment": "read-only next-area-v1 diagnostic audit",
            "production_formula": "0.55 * suitability_score + 0.45 * max(1.0 * recency_weight * distance_weight)",
            "historical_verification_adaptation": "uniform 1.0 for each unique OBIS occurrence",
            "data": {
                "raw_dated_records": len(source), "deduplicated_records": len(clean),
                "duplicate_coordinate_date_records_removed": len(source) - len(clean),
                "jamaica_domain_records": len(domain), "jamaica_domain_dates": len({row.event_date.date() for row in domain}),
                "jamaica_domain_cells": len({self.backtest.grid_cell_id(row.latitude, row.longitude) for row in domain}),
                "future_new_cell_overlap_between_windows": {
                    f"{windows[i]['evaluation_start']}__{windows[j]['evaluation_start']}": sorted(future_sets[i] & future_sets[j])
                    for i in range(len(windows)) for j in range(i + 1, len(windows))
                },
            },
            "windows": windows,
            "limitations": [
                "Presence-only records do not establish absence in unrecorded cells.",
                "Suitability-v3 is not temporally independent of these evaluation windows.",
                "Weight sweep is diagnostic and must not be used as optimization.",
            ],
        }


def main():
    database = SessionLocal()
    try:
        report = NextAreaV1DiagnosticAudit().run(database)
    finally:
        database.close()
    output = Path("next_area_v1_diagnostic_audit.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
