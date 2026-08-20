import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np
import requests
from scipy.io import netcdf_file

from ocean_current_service import CurrentCacheWriter, copernicus_access_status


HYCOM_SOURCE_FILE = "hycom_glby_930_2018120412_t000_uv3z.nc"
HYCOM_DATASET_PATH = (
    "datasets/GLBy0.08/expt_93.0/data/hindcasts/2018/" + HYCOM_SOURCE_FILE
)
HYCOM_NCSS_URL = "https://ncss.hycom.org/thredds/ncss/grid/" + HYCOM_DATASET_PATH


def cache_hycom_reference():
    params = [
        ("var", "water_u"), ("var", "water_v"),
        ("north", "18.7"), ("south", "16.9"),
        ("east", "-75.9"), ("west", "-78.6"),
        ("horizStride", "1"), ("vertCoord", "0"),
        ("addLatLon", "true"), ("accept", "netcdf"),
    ]
    started = perf_counter()
    response = requests.get(HYCOM_NCSS_URL, params=params, timeout=60)
    response.raise_for_status()
    request_seconds = perf_counter() - started
    descriptor, temporary_path = tempfile.mkstemp(suffix=".nc")
    os.close(descriptor)
    try:
        Path(temporary_path).write_bytes(response.content)
        with netcdf_file(temporary_path, "r", mmap=False) as dataset:
            latitudes = dataset.variables["lat"].data.copy()
            longitudes = dataset.variables["lon"].data.copy()
            longitudes = np.where(longitudes > 180, longitudes - 360, longitudes)
            source_u = dataset.variables["water_u"]
            source_v = dataset.variables["water_v"]
            u = source_u.data.copy()[0, 0].astype(np.float32)
            v = source_v.data.copy()[0, 0].astype(np.float32)
            u[u == source_u._FillValue] = np.nan
            v[v == source_v._FillValue] = np.nan
            u *= float(source_u.scale_factor)
            v *= float(source_v.scale_factor)
            depth = float(dataset.variables["depth"].data.copy()[0])
        path = Path(
            "current_data/hycom/gofs3.1/expt_93.0/daily/2018/12/"
            "hycom_gofs3.1_2018-12-04_depth-0m_jamaica.nc"
        )
        metadata = CurrentCacheWriter.write_partition(path, latitudes, longitudes, u, v, {
            "provider": "HYCOM",
            "product": "GOFS 3.1 GLBy0.08",
            "dataset_id": "GLBy0.08/expt_93.0",
            "product_version": "experiment 93.0",
            "source_file": HYCOM_SOURCE_FILE,
            "access_url": response.url,
            "requested_extent": {
                "latitude_min": 16.9, "latitude_max": 18.7,
                "longitude_min": -78.6, "longitude_max": -75.9,
            },
            "actual_returned_extent": {
                "latitude_min": float(latitudes.min()),
                "latitude_max": float(latitudes.max()),
                "longitude_min": float(longitudes.min()),
                "longitude_max": float(longitudes.max()),
            },
            "requested_date": "2018-12-04",
            "actual_timestamp": "2018-12-04T12:00:00+00:00",
            "source_depth_m": depth,
            "depth_index": 0,
            "variables": ["water_u", "water_v"],
            "canonical_variables": ["u", "v"],
            "u_units": "m/s", "v_units": "m/s",
            "source_coordinate_convention": "longitude 0..360; normalized cache -180..180",
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "request_seconds": request_seconds,
            "valid_ocean_cells": int((np.isfinite(u) & np.isfinite(v)).sum()),
            "masked_or_missing_cells": int((~(np.isfinite(u) & np.isfinite(v))).sum()),
        })
        return metadata
    finally:
        Path(temporary_path).unlink(missing_ok=True)


def main():
    status = copernicus_access_status()
    result = {
        "copernicus": status,
        "copernicus_downloads": (
            "Skipped cleanly because authentication/tooling is unavailable."
            if not status["configured"]
            else "Configured; validation download requires the provider adapter in a credentialed run."
        ),
        "hycom_reference": cache_hycom_reference(),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
