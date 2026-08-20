import json
import math
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import copernicusmarine
import numpy as np
import xarray as xr

from ocean_current_service import CurrentCacheWriter, sha256_file


DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
DATASET_VERSION = "202311"
PRODUCT_ID = "GLOBAL_MULTIYEAR_PHY_001_030"
PRODUCT = "Global Ocean Physics Reanalysis (GLORYS12V1)"
DATES = (
    "2012-02-21", "2018-07-22", "2018-11-27", "2019-10-21",
    "2021-08-03", "2021-12-28", "2022-03-12", "2022-09-05",
    "2022-09-06", "2022-09-30",
    "2023-02-18", "2023-04-29", "2023-08-25", "2023-11-20",
    "2024-01-02", "2024-01-06", "2024-10-01", "2025-01-07",
    "2025-05-06", "2025-08-31", "2025-10-03", "2025-11-29",
    "2026-03-13", "2026-05-17", "2026-05-18", "2026-06-12",
)
EXTENT = {
    "latitude_min": 16.9, "latitude_max": 18.7,
    "longitude_min": -78.6, "longitude_max": -75.9,
}
REQUESTED_DEPTH_M = 0.494025


def target_path(day):
    parsed = date.fromisoformat(day)
    return Path(
        f"current_data/copernicus/glorys12v1/daily/{parsed:%Y/%m}/"
        f"glorys12v1_{day}_depth-0.494025m_jamaica.nc"
    )


def validated_existing(path):
    metadata_path = path.with_suffix(path.suffix + ".metadata.json")
    if not path.exists() or not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("checksum") != sha256_file(path):
            return None
        if metadata.get("represented_date") != path.stem.split("_")[1]:
            return None
        return metadata
    except (OSError, ValueError, KeyError):
        return None


def acquire(day):
    output = target_path(day)
    existing = validated_existing(output)
    if existing:
        return "SKIPPED_VALID", existing
    with tempfile.TemporaryDirectory(prefix="glorys-current-") as temporary:
        filename = f"source-{day}.nc"
        copernicusmarine.subset(
            dataset_id=DATASET_ID,
            dataset_version=DATASET_VERSION,
            variables=["uo", "vo"],
            minimum_longitude=EXTENT["longitude_min"],
            maximum_longitude=EXTENT["longitude_max"],
            minimum_latitude=EXTENT["latitude_min"],
            maximum_latitude=EXTENT["latitude_max"],
            minimum_depth=REQUESTED_DEPTH_M,
            maximum_depth=REQUESTED_DEPTH_M,
            start_datetime=f"{day}T00:00:00",
            end_datetime=f"{day}T23:59:59",
            coordinates_selection_method="inside",
            output_filename=filename,
            output_directory=temporary,
            file_format="netcdf",
            overwrite=True,
            disable_progress_bar=True,
        )
        source_path = Path(temporary) / filename
        with xr.open_dataset(source_path) as dataset:
            latitudes = np.asarray(dataset.latitude.values, dtype=np.float64)
            longitudes = np.asarray(dataset.longitude.values, dtype=np.float64)
            depths = np.asarray(dataset.depth.values, dtype=np.float64)
            actual_depth = float(depths.reshape(-1)[0])
            u = np.asarray(dataset.uo.squeeze().values, dtype=np.float32)
            v = np.asarray(dataset.vo.squeeze().values, dtype=np.float32)
            u_units = dataset.uo.attrs.get("units", "m s-1")
            v_units = dataset.vo.attrs.get("units", "m s-1")
        valid = np.isfinite(u) & np.isfinite(v)
        metadata = CurrentCacheWriter.write_partition(output, latitudes, longitudes, u, v, {
            "provider": "COPERNICUS_MARINE",
            "product": PRODUCT,
            "product_id": PRODUCT_ID,
            "dataset_id": DATASET_ID,
            "product_version": DATASET_VERSION,
            "represented_date": day,
            "temporal_representation": "DAILY_MEAN",
            "requested_extent": EXTENT,
            "actual_returned_extent": {
                "latitude_min": float(latitudes.min()),
                "latitude_max": float(latitudes.max()),
                "longitude_min": float(longitudes.min()),
                "longitude_max": float(longitudes.max()),
            },
            "requested_depth_m": REQUESTED_DEPTH_M,
            "source_depth_m": actual_depth,
            "variables": ["uo", "vo"],
            "canonical_variables": ["u", "v"],
            "u_units": u_units,
            "v_units": v_units,
            "source_coordinate_convention": "longitude -180..180, degrees_east",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "valid_ocean_cells": int(valid.sum()),
            "masked_or_missing_cells": int(valid.size - valid.sum()),
            "grid_shape": [int(u.shape[0]), int(u.shape[1])],
            "latitude_resolution_degrees": float(np.median(np.diff(latitudes))),
            "longitude_resolution_degrees": float(np.median(np.diff(longitudes))),
        })
    return "CACHED", metadata


def main():
    print(json.dumps({
        "plan": {
            "dates": DATES,
            "partitions": len(DATES),
            "extent": EXTENT,
            "variables": ["uo", "vo"],
            "requested_depth_m": REQUESTED_DEPTH_M,
            "estimated_native_cells_per_partition": 23 * 33,
            "estimated_storage_bytes": [8_000 * len(DATES), 20_000 * len(DATES)],
        }
    }, indent=2))
    results = []
    for day in DATES:
        try:
            status, metadata = acquire(day)
            results.append({"date": day, "status": status, "metadata": metadata})
        except Exception as error:
            results.append({"date": day, "status": "FAILED", "error": str(error)})
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
