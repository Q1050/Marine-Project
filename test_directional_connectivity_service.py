from datetime import datetime, timezone
import unittest

from directional_connectivity_service import (
    DirectionalConnectivityService,
    alignment_from_bearings,
    initial_great_circle_bearing,
    smallest_angular_difference,
)


class FakeCurrentService:
    def __init__(self, current):
        self.current = current

    def get_current(self, *args):
        return dict(self.current)


def valid_current(u, v, bearing, speed=1.0):
    return {
        "status": "VALID", "u": u, "v": v, "speed": speed,
        "toward_bearing_degrees": bearing,
        "source_latitude": 0.0, "source_longitude": 0.0,
        "spatial_distance_km": 0.0,
        "source_timestamp": "2024-01-01T00:00:00+00:00",
        "source_depth_m": 0.0, "provider": "FIXTURE",
        "product": "fixture", "dataset_id": "fixture-v1",
        "sampling_method": "EXACT",
    }


class DirectionalConnectivityTests(unittest.TestCase):

    def test_great_circle_cardinal_bearings(self):
        self.assertAlmostEqual(initial_great_circle_bearing(0, 0, 0, 1), 90)
        self.assertAlmostEqual(initial_great_circle_bearing(0, 0, 0, -1), 270)
        self.assertAlmostEqual(initial_great_circle_bearing(0, 0, 1, 0), 0)
        self.assertAlmostEqual(initial_great_circle_bearing(0, 0, -1, 0), 180)

    def test_angular_difference_wraparound(self):
        self.assertEqual(smallest_angular_difference(359, 1), 2)

    def test_alignment_bounds(self):
        for first in range(0, 360, 15):
            for second in range(0, 360, 15):
                self.assertGreaterEqual(alignment_from_bearings(first, second), -1)
                self.assertLessEqual(alignment_from_bearings(first, second), 1)

    def test_east_current_cardinal_candidates(self):
        service = DirectionalConnectivityService(FakeCurrentService(valid_current(1, 0, 90)))
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        east = service.calculate_directional_connectivity(0, 0, 0, 1, timestamp, 0)
        west = service.calculate_directional_connectivity(0, 0, 0, -1, timestamp, 0)
        north = service.calculate_directional_connectivity(0, 0, 1, 0, timestamp, 0)
        south = service.calculate_directional_connectivity(0, 0, -1, 0, timestamp, 0)
        self.assertAlmostEqual(east["alignment"], 1)
        self.assertAlmostEqual(west["alignment"], -1)
        self.assertAlmostEqual(north["alignment"], 0, places=12)
        self.assertAlmostEqual(south["alignment"], 0, places=12)

    def test_north_current_cardinal_candidates(self):
        service = DirectionalConnectivityService(FakeCurrentService(valid_current(0, 1, 0)))
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        north = service.calculate_directional_connectivity(0, 0, 1, 0, timestamp, 0)
        south = service.calculate_directional_connectivity(0, 0, -1, 0, timestamp, 0)
        east = service.calculate_directional_connectivity(0, 0, 0, 1, timestamp, 0)
        self.assertAlmostEqual(north["alignment"], 1)
        self.assertAlmostEqual(south["alignment"], -1)
        self.assertAlmostEqual(east["alignment"], 0, places=12)

    def test_diagonal_cases(self):
        service = DirectionalConnectivityService(FakeCurrentService(valid_current(1, 1, 45, 2 ** 0.5)))
        timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        northeast = service.calculate_directional_connectivity(0, 0, 1, 1, timestamp, 0)
        southwest = service.calculate_directional_connectivity(0, 0, -1, -1, timestamp, 0)
        self.assertGreater(northeast["alignment"], 0.999)
        self.assertLess(southwest["alignment"], -0.999)

    def test_missing_current_keeps_directional_metrics_null(self):
        missing = {"status": "MISSING_PROVIDER_VALUE", "provider": "FIXTURE", "sampling_method": "MISSING"}
        service = DirectionalConnectivityService(FakeCurrentService(missing))
        result = service.calculate_directional_connectivity(
            0, 0, 0, 1, datetime(2024, 1, 1, tzinfo=timezone.utc), 0
        )
        self.assertIsNone(result["alignment"])
        self.assertIsNone(result["speed_weighted_alignment"])

    def test_repeated_calculation_is_deterministic(self):
        service = DirectionalConnectivityService(FakeCurrentService(valid_current(1, 0, 90)))
        arguments = (0, 0, 0, 1, datetime(2024, 1, 1, tzinfo=timezone.utc), 0)
        self.assertEqual(
            service.calculate_directional_connectivity(*arguments),
            service.calculate_directional_connectivity(*arguments),
        )


if __name__ == "__main__":
    unittest.main()
