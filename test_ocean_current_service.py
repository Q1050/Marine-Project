from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import numpy as np

from ocean_current_service import (
    CurrentCacheWriter,
    OceanCurrentLookupService,
    toward_bearing_degrees,
    vector_speed,
)


class OceanCurrentServiceTests(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        path = root / "fixture" / "2024" / "01" / "current.nc"
        CurrentCacheWriter.write_partition(
            path,
            [18.0, 18.1],
            [-77.1, -77.0],
            [[1.0, np.nan], [0.0, -1.0]],
            [[0.0, np.nan], [1.0, 0.0]],
            {
                "provider": "FIXTURE",
                "product": "Fixture currents",
                "dataset_id": "fixture-v1",
                "product_version": "1",
                "requested_extent": {"latitude_min": 18, "latitude_max": 18.1, "longitude_min": -77.1, "longitude_max": -77},
                "actual_returned_extent": {"latitude_min": 18, "latitude_max": 18.1, "longitude_min": -77.1, "longitude_max": -77},
                "requested_date": "2024-01-01",
                "actual_timestamp": "2024-01-01T12:00:00+00:00",
                "source_depth_m": 0.5,
                "depth_index": 0,
                "variables": ["uo", "vo"],
                "u_units": "m/s", "v_units": "m/s",
                "downloaded_at": "2024-01-02T00:00:00+00:00",
            },
        )
        self.service = OceanCurrentLookupService(root)
        self.timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.temporary.cleanup()

    def test_speed_and_bearing(self):
        self.assertEqual(vector_speed(3, 4), 5)
        self.assertAlmostEqual(toward_bearing_degrees(1, 0), 90)
        self.assertAlmostEqual(toward_bearing_degrees(-1, 0), 270)
        self.assertAlmostEqual(toward_bearing_degrees(0, 1), 0)
        self.assertAlmostEqual(toward_bearing_degrees(0, -1), 180)

    def test_masked_value_handling(self):
        result = self.service.get_current(18.0, -77.0, self.timestamp, 0.5)
        self.assertEqual(result["status"], "MISSING_PROVIDER_VALUE")
        self.assertTrue(result["missing_or_masked"])

    def test_not_cached(self):
        result = self.service.get_current(
            18.0, -77.1, datetime(2024, 1, 2, tzinfo=timezone.utc), 0.5
        )
        self.assertEqual(result["status"], "NOT_CACHED")

    def test_nearest_grid_and_provenance(self):
        result = self.service.get_current(18.01, -77.09, self.timestamp, 0.5)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["sampling_method"], "NEAREST_GRID_POINT")
        self.assertEqual(result["provider"], "FIXTURE")
        self.assertEqual(result["dataset_id"], "fixture-v1")
        self.assertGreater(result["spatial_distance_km"], 0)

    def test_repeated_lookup_is_deterministic(self):
        first = self.service.get_current(18.1, -77.1, self.timestamp, 0.5)
        second = self.service.get_current(18.1, -77.1, self.timestamp, 0.5)
        self.assertEqual(first, second)

    def test_daily_mean_partition_uses_represented_date_without_fake_timestamp(self):
        root = Path(self.temporary.name)
        CurrentCacheWriter.write_partition(
            root / "daily" / "2024" / "01" / "current.nc",
            [18.0], [-77.0], [[0.25]], [[-0.5]],
            {
                "provider": "DAILY_FIXTURE",
                "product": "Daily fixture currents",
                "dataset_id": "daily-fixture-v1",
                "product_version": "1",
                "represented_date": "2024-01-03",
                "temporal_representation": "DAILY_MEAN",
                "requested_extent": {"latitude_min": 18, "latitude_max": 18, "longitude_min": -77, "longitude_max": -77},
                "actual_returned_extent": {"latitude_min": 18, "latitude_max": 18, "longitude_min": -77, "longitude_max": -77},
                "requested_depth_m": 0.5,
                "source_depth_m": 0.5,
                "variables": ["uo", "vo"],
                "u_units": "m s-1", "v_units": "m s-1",
                "downloaded_at": "2024-01-04T00:00:00+00:00",
            },
        )
        result = self.service.get_current(
            18.0, -77.0, datetime(2024, 1, 3, 19, tzinfo=timezone.utc), 0.5,
            provider="DAILY_FIXTURE",
        )
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["represented_date"], "2024-01-03")
        self.assertEqual(result["temporal_representation"], "DAILY_MEAN")
        self.assertIsNone(result["source_timestamp"])
        self.assertIsNone(result["temporal_difference_seconds"])


if __name__ == "__main__":
    unittest.main()
