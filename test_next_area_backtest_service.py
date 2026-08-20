from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from next_area_backtest_service import NextAreaBacktestService


def occurrence(identifier, date, latitude=18.05, longitude=-76.95):
    return SimpleNamespace(
        id=identifier,
        scientific_name="Pterois volitans",
        event_date=date,
        latitude=latitude,
        longitude=longitude,
    )


class NextAreaBacktestTests(unittest.TestCase):

    def setUp(self):
        self.service = NextAreaBacktestService(random_permutations=20)
        self.cutoff = datetime(2020, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        self.end = datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    def test_future_records_cannot_influence_cutoff_evidence(self):
        old = occurrence(1, datetime(2020, 1, 1), 18.05, -76.95)
        future = occurrence(2, datetime(2021, 1, 1), 18.05, -76.85)
        historical, _, _, _, _ = self.service.partition_window(
            [old, future], self.cutoff, self.end
        )
        self.assertEqual([row.id for row in historical], [1])
        cell = SimpleNamespace(latitude=18.05, longitude=-76.85)
        self.assertAlmostEqual(
            self.service._historical_evidence_score(cell, historical, self.cutoff),
            0.08,
        )

    def test_occupied_exclusion_and_new_cell_identification(self):
        old = occurrence(1, datetime(2020, 1, 1), 18.05, -76.95)
        repeated = occurrence(2, datetime(2021, 1, 1), 18.05, -76.95)
        new = occurrence(3, datetime(2021, 1, 2), 18.15, -76.95)
        historical, _, occupied, _, future_new = self.service.partition_window(
            [old, repeated, new], self.cutoff, self.end
        )
        grid = [
            SimpleNamespace(grid_cell_id="180:-770", latitude=18.05, longitude=-76.95, suitability_score=0.5),
            SimpleNamespace(grid_cell_id="181:-770", latitude=18.15, longitude=-76.95, suitability_score=0.5),
        ]
        candidates = self.service.score_candidates(grid, occupied, historical, self.cutoff)
        self.assertEqual([item["grid_cell_id"] for item in candidates], ["181:-770"])
        self.assertEqual(future_new, {"181:-770"})

    def test_duplicate_coordinate_date_is_removed(self):
        date = datetime(2020, 1, 1)
        rows = [occurrence(1, date), occurrence(2, date)]
        self.assertEqual(len(self.service._deduplicate(rows)), 1)

    def test_exact_and_tolerance_are_separate(self):
        future = SimpleNamespace(latitude=18.05, longitude=-76.95)
        adjacent = {
            "grid_cell_id": "181:-770", "latitude": 18.15, "longitude": -76.95
        }
        result = self.service._metrics(
            [adjacent], {"180:-770"}, {"180:-770": future}
        )
        self.assertEqual(result["exact"]["at_10"]["hit_rate"], 0.0)
        self.assertEqual(result["tolerance"]["at_10"]["hit_rate"], 1.0)

    def test_ranking_and_random_baseline_are_reproducible(self):
        candidates = [
            {"grid_cell_id": str(index), "latitude": 18 + index / 100, "longitude": -77, "suitability_score": index / 100}
            for index in range(60)
        ]
        self.assertEqual(
            self.service._rank(candidates, "suitability_score"),
            self.service._rank(candidates, "suitability_score"),
        )
        lookup = {item["grid_cell_id"]: SimpleNamespace(latitude=item["latitude"], longitude=item["longitude"]) for item in candidates}
        first = self.service._random_baseline(candidates, {"20"}, lookup, 0)
        second = self.service._random_baseline(candidates, {"20"}, lookup, 0)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
