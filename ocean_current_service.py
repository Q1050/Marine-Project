import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from geographic_utils import haversine_km


DEFAULT_CACHE_ROOT = Path("current_data")
COPERNICUS_DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"


def vector_speed(u, v):
    return math.hypot(u, v)


def toward_bearing_degrees(u, v):
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copernicus_access_status():
    """Report configuration presence without reading or exposing secrets."""
    try:
        import importlib.util
        toolbox_installed = importlib.util.find_spec("copernicusmarine") is not None
    except (ImportError, ValueError):
        toolbox_installed = False
    username_configured = bool(os.getenv("COPERNICUSMARINE_SERVICE_USERNAME"))
    password_configured = bool(os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD"))
    configuration_file = Path.home() / ".copernicusmarine" / ".copernicusmarine-credentials"
    credential_file_present = configuration_file.exists()
    configured = toolbox_installed and (
        (username_configured and password_configured) or credential_file_present
    )
    return {
        "configured": configured,
        "toolbox_installed": toolbox_installed,
        "username_environment_configured": username_configured,
        "password_environment_configured": password_configured,
        "credential_file_present": credential_file_present,
        "configuration_required": [
            "Install the copernicusmarine Python package/CLI in the project environment.",
            "Create a free Copernicus Marine account.",
            "Run `copernicusmarine login` or set COPERNICUSMARINE_SERVICE_USERNAME and COPERNICUSMARINE_SERVICE_PASSWORD for the process.",
            "Do not commit credentials to this repository.",
        ] if not configured else [],
    }


class CurrentCacheWriter:

    @staticmethod
    def write_partition(path, latitudes, longitudes, u, v, metadata):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        latitudes = np.asarray(latitudes, dtype=np.float64)
        longitudes = np.asarray(longitudes, dtype=np.float64)
        u = np.asarray(u, dtype=np.float32)
        v = np.asarray(v, dtype=np.float32)
        if u.shape != (len(latitudes), len(longitudes)) or v.shape != u.shape:
            raise ValueError("u/v arrays must match latitude × longitude dimensions")
        with netcdf_file(path, "w") as dataset:
            dataset.createDimension("latitude", len(latitudes))
            dataset.createDimension("longitude", len(longitudes))
            latitude = dataset.createVariable("latitude", "f8", ("latitude",))
            longitude = dataset.createVariable("longitude", "f8", ("longitude",))
            eastward = dataset.createVariable("u", "f4", ("latitude", "longitude"))
            northward = dataset.createVariable("v", "f4", ("latitude", "longitude"))
            latitude[:] = latitudes
            longitude[:] = longitudes
            eastward[:] = u
            northward[:] = v
            latitude.units = "degrees_north"
            longitude.units = "degrees_east"
            eastward.units = metadata["u_units"]
            northward.units = metadata["v_units"]
            eastward.missing_value = np.float32(np.nan)
            northward.missing_value = np.float32(np.nan)
            dataset.provider = metadata["provider"]
            dataset.product = metadata["product"]
            dataset.dataset_id = metadata["dataset_id"]
            if metadata.get("actual_timestamp"):
                dataset.actual_timestamp = metadata["actual_timestamp"]
            if metadata.get("represented_date"):
                dataset.represented_date = metadata["represented_date"]
            if metadata.get("temporal_representation"):
                dataset.temporal_representation = metadata["temporal_representation"]
            dataset.source_depth_m = float(metadata["source_depth_m"])
        checksum = sha256_file(path)
        complete_metadata = dict(metadata)
        complete_metadata.update({
            "cache_file": path.as_posix(),
            "checksum_algorithm": "SHA-256",
            "checksum": checksum,
            "file_size_bytes": path.stat().st_size,
        })
        metadata_path = path.with_suffix(path.suffix + ".metadata.json")
        metadata_path.write_text(json.dumps(complete_metadata, indent=2), encoding="utf-8")
        return complete_metadata


class OceanCurrentLookupService:

    def __init__(self, cache_root=DEFAULT_CACHE_ROOT):
        self.cache_root = Path(cache_root)

    def _partitions(self):
        partitions = []
        if not self.cache_root.exists():
            return partitions
        for path in sorted(self.cache_root.rglob("*.nc.metadata.json")):
            metadata = json.loads(path.read_text(encoding="utf-8"))
            cache_file = Path(metadata["cache_file"])
            if not cache_file.is_absolute():
                cache_file = Path.cwd() / cache_file
            partitions.append((cache_file, metadata))
        return partitions

    @staticmethod
    def _empty(status, requested, metadata=None):
        return {
            "status": status,
            "u": None,
            "v": None,
            "speed": None,
            "toward_bearing_degrees": None,
            "source_latitude": None,
            "source_longitude": None,
            "spatial_distance_km": None,
            "source_timestamp": metadata.get("actual_timestamp") if metadata else None,
            "represented_date": metadata.get("represented_date") if metadata else None,
            "temporal_representation": metadata.get("temporal_representation") if metadata else None,
            "temporal_difference_seconds": None,
            "source_depth_m": metadata.get("source_depth_m") if metadata else None,
            "provider": metadata.get("provider") if metadata else requested.get("provider"),
            "product": metadata.get("product") if metadata else None,
            "dataset_id": metadata.get("dataset_id") if metadata else None,
            "sampling_method": "MISSING",
            "missing_or_masked": status == "MISSING_PROVIDER_VALUE",
        }

    def get_current(self, latitude, longitude, timestamp, depth, provider=None):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        requested = {"provider": provider}
        matches = []
        for path, metadata in self._partitions():
            represented_date = metadata.get("represented_date")
            actual_timestamp = metadata.get("actual_timestamp")
            actual = (
                datetime.fromisoformat(actual_timestamp.replace("Z", "+00:00"))
                if actual_timestamp else None
            )
            if provider and metadata["provider"] != provider:
                continue
            partition_date = (
                datetime.fromisoformat(represented_date).date()
                if represented_date else actual.date()
            )
            if partition_date != timestamp.date():
                continue
            if not math.isclose(float(metadata["source_depth_m"]), float(depth), abs_tol=1e-6):
                continue
            matches.append((path, metadata, actual))
        if not matches:
            return self._empty("NOT_CACHED", requested)
        path, metadata, actual = sorted(matches, key=lambda item: item[1]["dataset_id"])[0]
        extent = metadata["actual_returned_extent"]
        if not (
            extent["latitude_min"] <= latitude <= extent["latitude_max"]
            and extent["longitude_min"] <= longitude <= extent["longitude_max"]
        ):
            return self._empty("OUTSIDE_EXTENT", requested, metadata)
        with netcdf_file(path, "r", mmap=False) as dataset:
            latitudes = dataset.variables["latitude"].data.copy()
            longitudes = dataset.variables["longitude"].data.copy()
            u_values = dataset.variables["u"].data.copy()
            v_values = dataset.variables["v"].data.copy()
        latitude_index = int(np.argmin(np.abs(latitudes - latitude)))
        longitude_index = int(np.argmin(np.abs(longitudes - longitude)))
        source_latitude = float(latitudes[latitude_index])
        source_longitude = float(longitudes[longitude_index])
        u = float(u_values[latitude_index, longitude_index])
        v = float(v_values[latitude_index, longitude_index])
        distance = haversine_km(
            latitude, longitude, source_latitude, source_longitude
        )
        if not math.isfinite(u) or not math.isfinite(v):
            result = self._empty("MISSING_PROVIDER_VALUE", requested, metadata)
            result.update({
                "source_latitude": source_latitude,
                "source_longitude": source_longitude,
                "spatial_distance_km": distance,
                "temporal_difference_seconds": (
                    (actual - timestamp).total_seconds() if actual else None
                ),
            })
            return result
        exact = math.isclose(latitude, source_latitude, abs_tol=1e-9) and math.isclose(
            longitude, source_longitude, abs_tol=1e-9
        )
        return {
            "status": "VALID",
            "u": u,
            "v": v,
            "speed": vector_speed(u, v),
            "toward_bearing_degrees": toward_bearing_degrees(u, v),
            "source_latitude": source_latitude,
            "source_longitude": source_longitude,
            "spatial_distance_km": distance,
            "source_timestamp": metadata.get("actual_timestamp"),
            "represented_date": metadata.get("represented_date"),
            "temporal_representation": metadata.get("temporal_representation"),
            "temporal_difference_seconds": (
                (actual - timestamp).total_seconds() if actual else None
            ),
            "source_depth_m": metadata["source_depth_m"],
            "provider": metadata["provider"],
            "product": metadata["product"],
            "dataset_id": metadata["dataset_id"],
            "sampling_method": "EXACT" if exact else "NEAREST_GRID_POINT",
            "missing_or_masked": False,
        }
