import csv
import gzip
import io
import json
import math
from pathlib import Path

import numpy as np
import requests
from scipy.stats import mannwhitneyu, pointbiserialr

from environmental_feature_service import DEPTH_SOURCE, EnvironmentalFeatureService
from geographic_utils import haversine_km
from models import (
    BathymetryGridCell,
    PredictionModelSample,
    PredictionSampleEnvironmentalFeature,
)


FEATURE_VERSION = "caribbean-grid-v2-environment-v1"
GENERATION_VERSION = "caribbean-grid-v2"
WOA_SOURCE = "NOAA World Ocean Atlas 2023 1955-2022 monthly surface climatology, 1-degree"
COAST_SOURCE = "Natural Earth 1:10m land polygons, public domain"
CACHE_DIRECTORY = Path("data/environmental_cache")
WOA_URL = (
    "https://www.ncei.noaa.gov/data/oceans/woa/WOA23/DATA/"
    "{variable}/csv/decav/1.00/woa23_decav_{code}{month:02d}an01.csv.gz"
)
NATURAL_EARTH_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_land.geojson"
)


class EnvironmentalFeatureExpansionService:

    def __init__(self, environmental_service=None):
        self.environmental_service = environmental_service or EnvironmentalFeatureService(
            timeout=10
        )
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "marine-monitoring-feature-expansion/0.1"

    def _download(self, url, filename, timeout=240):
        CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIRECTORY / filename
        if not path.exists():
            response = self.session.get(url, timeout=(20, timeout))
            response.raise_for_status()
            path.write_bytes(response.content)
        return path

    def _woa_month(self, variable, code, month):
        path = self._download(
            WOA_URL.format(variable=variable, code=code, month=month),
            f"woa23_{code}{month:02d}an01.csv.gz",
        )
        points = []
        with gzip.open(path, "rt", encoding="utf-8") as source:
            reader = csv.reader(source)
            for row in reader:
                if not row or row[0].startswith("#"):
                    continue
                try:
                    latitude = float(row[0])
                    longitude = float(row[1])
                    value = float(row[2])
                except (IndexError, ValueError):
                    continue
                if (
                    7 <= latitude <= 30
                    and -91 <= longitude <= -57
                    and math.isfinite(value)
                ):
                    points.append((latitude, longitude, value))
        return np.asarray(points, dtype=float)

    @staticmethod
    def _nearest_climatology(points, latitude, longitude, max_distance_km=160):
        if not len(points):
            return None
        latitudes = np.radians(points[:, 0])
        longitudes = np.radians(points[:, 1])
        origin_latitude = math.radians(latitude)
        origin_longitude = math.radians(longitude)
        latitude_delta = latitudes - origin_latitude
        longitude_delta = longitudes - origin_longitude
        value = (
            np.sin(latitude_delta / 2) ** 2
            + np.cos(origin_latitude) * np.cos(latitudes)
            * np.sin(longitude_delta / 2) ** 2
        )
        distances = 6371.0088 * 2 * np.arcsin(np.sqrt(value))
        index = int(np.argmin(distances))
        if distances[index] > max_distance_km:
            return None
        return float(points[index, 2]), float(distances[index])

    def _climatology_features(self, samples):
        temperature = [
            self._woa_month("temperature", "t", month) for month in range(1, 13)
        ]
        salinity = [
            self._woa_month("salinity", "s", month) for month in range(1, 13)
        ]
        output = {}
        for sample in samples:
            temperatures = [
                self._nearest_climatology(points, sample.latitude, sample.longitude)
                for points in temperature
            ]
            salinities = [
                self._nearest_climatology(points, sample.latitude, sample.longitude)
                for points in salinity
            ]
            valid_temperature = [item for item in temperatures if item is not None]
            valid_salinity = [item for item in salinities if item is not None]
            output[sample.id] = {
                "temperature": valid_temperature if len(valid_temperature) == 12 else [],
                "salinity": valid_salinity if len(valid_salinity) == 12 else [],
            }
        return output

    def _coast_vertices(self):
        path = self._download(NATURAL_EARTH_URL, "ne_10m_land.geojson")
        payload = json.loads(path.read_text(encoding="utf-8"))
        vertices = []

        def rings(coordinates):
            if not coordinates:
                return
            if isinstance(coordinates[0][0], (int, float)):
                for longitude, latitude, *_ in coordinates:
                    if 7 <= latitude <= 30 and -91 <= longitude <= -57:
                        vertices.append((latitude, longitude))
                return
            for child in coordinates:
                rings(child)

        for feature in payload["features"]:
            rings(feature["geometry"]["coordinates"])
        return np.asarray(vertices, dtype=float)

    @staticmethod
    def _nearest_vertex_distance(vertices, latitude, longitude):
        latitudes = np.radians(vertices[:, 0])
        longitudes = np.radians(vertices[:, 1])
        origin_latitude = math.radians(latitude)
        origin_longitude = math.radians(longitude)
        value = (
            np.sin((latitudes - origin_latitude) / 2) ** 2
            + np.cos(origin_latitude) * np.cos(latitudes)
            * np.sin((longitudes - origin_longitude) / 2) ** 2
        )
        return float((6371.0088 * 2 * np.arcsin(np.sqrt(value))).min())

    def _bathymetry_neighborhoods(self, db, samples):
        identifiers = set()
        for sample in samples:
            latitude_index, longitude_index = map(int, sample.grid_cell_id.split(":"))
            for latitude_offset in (-1, 0, 1):
                for longitude_offset in (-1, 0, 1):
                    identifiers.add(
                        f"{latitude_index + latitude_offset}:{longitude_index + longitude_offset}"
                    )
        cached = {
            row.grid_cell_id: row
            for row in db.query(BathymetryGridCell).filter(
                BathymetryGridCell.grid_cell_id.in_(identifiers)
            ).all()
        }
        missing = sorted(identifiers - set(cached))
        from concurrent.futures import ThreadPoolExecutor

        def lookup(identifier):
            latitude_index, longitude_index = map(int, identifier.split(":"))
            latitude = round((latitude_index + 0.5) * 0.1, 6)
            longitude = round((longitude_index + 0.5) * 0.1, 6)
            result = self.environmental_service.classify_marine_coordinate(
                latitude, longitude
            )
            return identifier, latitude, longitude, result

        with ThreadPoolExecutor(max_workers=24) as executor:
            for identifier, latitude, longitude, result in executor.map(lookup, missing):
                if result["classification"] == "UNAVAILABLE":
                    continue
                row = BathymetryGridCell(
                    grid_cell_id=identifier,
                    latitude=latitude,
                    longitude=longitude,
                    classification=result["classification"],
                    depth=result["depth"],
                    source=result["source"],
                )
                db.add(row)
                cached[identifier] = row
        db.commit()
        output = {}
        for sample in samples:
            latitude_index, longitude_index = map(int, sample.grid_cell_id.split(":"))
            neighbors = []
            slopes = []
            for latitude_offset in (-1, 0, 1):
                for longitude_offset in (-1, 0, 1):
                    if latitude_offset == 0 and longitude_offset == 0:
                        continue
                    row = cached.get(
                        f"{latitude_index + latitude_offset}:{longitude_index + longitude_offset}"
                    )
                    if row is None or row.classification != "MARINE" or row.depth is None:
                        continue
                    neighbors.append(float(row.depth))
                    distance = haversine_km(
                        sample.latitude, sample.longitude, row.latitude, row.longitude
                    )
                    slopes.append(abs(float(row.depth) - sample.depth) / distance)
            output[sample.id] = {
                "values": neighbors,
                "slopes": slopes,
                "neighbor_count": len(neighbors),
            }
        return output

    @staticmethod
    def _feature(sample, name, value, source, method, metadata=None):
        return PredictionSampleEnvironmentalFeature(
            prediction_model_sample_id=sample.id,
            feature_name=name,
            value=value,
            source=source,
            sampling_method=method if value is not None else "MISSING",
            is_missing=value is None,
            metadata_json=json.dumps(metadata or {}),
            feature_version=FEATURE_VERSION,
        )

    def enrich(self, db):
        existing = db.query(PredictionSampleEnvironmentalFeature).filter(
            PredictionSampleEnvironmentalFeature.feature_version == FEATURE_VERSION
        ).count()
        if existing:
            return self.audit(db) | {"already_generated": True, "new_feature_rows": 0}
        samples = db.query(PredictionModelSample).filter(
            PredictionModelSample.generation_version == GENERATION_VERSION
        ).order_by(PredictionModelSample.id).all()
        if len(samples) != 2334:
            raise ValueError(f"Expected 2334 fixed v2 samples; found {len(samples)}")
        climatology = self._climatology_features(samples)
        coast_vertices = self._coast_vertices()
        bathymetry = self._bathymetry_neighborhoods(db, samples)
        rows = []
        for sample in samples:
            temperature = climatology[sample.id]["temperature"]
            salinity = climatology[sample.id]["salinity"]
            temperature_values = [item[0] for item in temperature]
            salinity_values = [item[0] for item in salinity]
            temperature_metadata = {
                "months": len(temperature),
                "max_sampling_distance_km": max((item[1] for item in temperature), default=None),
                "resolution_degrees": 1.0,
            }
            salinity_metadata = {
                "months": len(salinity),
                "max_sampling_distance_km": max((item[1] for item in salinity), default=None),
                "resolution_degrees": 1.0,
            }
            temperature_features = {
                "sst_climatology_annual_mean": np.mean(temperature_values) if temperature_values else None,
                "sst_climatology_monthly_min": np.min(temperature_values) if temperature_values else None,
                "sst_climatology_monthly_max": np.max(temperature_values) if temperature_values else None,
                "sst_climatology_seasonal_range": (
                    np.max(temperature_values) - np.min(temperature_values)
                    if temperature_values else None
                ),
            }
            for name, value in temperature_features.items():
                rows.append(self._feature(
                    sample, name, float(value) if value is not None else None,
                    WOA_SOURCE, "NEAREST_VALID_1_DEGREE", temperature_metadata,
                ))
            rows.append(self._feature(
                sample,
                "salinity_climatology_annual_mean",
                float(np.mean(salinity_values)) if salinity_values else None,
                WOA_SOURCE,
                "NEAREST_VALID_1_DEGREE",
                salinity_metadata,
            ))
            neighborhood = bathymetry[sample.id]
            neighbor_values = neighborhood["values"]
            bathymetry_metadata = {
                "neighborhood": "8 adjacent 0.1-degree cell centers",
                "marine_neighbor_count": neighborhood["neighbor_count"],
            }
            rows.append(self._feature(
                sample, "bathymetry_center_depth", sample.depth,
                DEPTH_SOURCE, "EXACT_CELL_CENTER", {"resolution_degrees": 0.1},
            ))
            bathymetry_features = {
                "bathymetry_neighbor_mean": np.mean(neighbor_values) if neighbor_values else None,
                "bathymetry_neighbor_std": np.std(neighbor_values) if neighbor_values else None,
                "bathymetry_local_relief": (
                    max(neighbor_values + [sample.depth]) - min(neighbor_values + [sample.depth])
                    if neighbor_values else None
                ),
                "bathymetry_max_slope": max(neighborhood["slopes"]) if neighborhood["slopes"] else None,
            }
            for name, value in bathymetry_features.items():
                rows.append(self._feature(
                    sample, name, float(value) if value is not None else None,
                    DEPTH_SOURCE, "DETERMINISTIC_3X3_GRID", bathymetry_metadata,
                ))
            rows.append(self._feature(
                sample,
                "distance_to_land_km",
                self._nearest_vertex_distance(coast_vertices, sample.latitude, sample.longitude),
                COAST_SOURCE,
                "NEAREST_COASTLINE_VERTEX",
                {"nominal_scale": "1:10m", "vertex_count_caribbean_subset": len(coast_vertices)},
            ))
        db.add_all(rows)
        db.commit()
        return self.audit(db) | {"already_generated": False, "new_feature_rows": len(rows)}

    def audit(self, db):
        samples = db.query(PredictionModelSample).filter(
            PredictionModelSample.generation_version == GENERATION_VERSION
        ).all()
        sample_type = {sample.id: sample.sample_type for sample in samples}
        rows = db.query(PredictionSampleEnvironmentalFeature).filter(
            PredictionSampleEnvironmentalFeature.feature_version == FEATURE_VERSION
        ).all()
        features = {}
        for name in sorted({row.feature_name for row in rows}):
            feature_rows = [row for row in rows if row.feature_name == name]
            values = [row.value for row in feature_rows if row.value is not None]
            entry = {}
            provenance = {}
            missing_counts = {}
            for group in ("PRESENCE", "BACKGROUND"):
                group_rows = [row for row in feature_rows if sample_type[row.prediction_model_sample_id] == group]
                group_values = [row.value for row in group_rows if row.value is not None]
                entry[group.lower()] = {
                    "available": len(group_values),
                    "coverage_percent": round(100 * len(group_values) / len(group_rows), 2),
                    "min": min(group_values) if group_values else None,
                    "median": float(np.median(group_values)) if group_values else None,
                    "max": max(group_values) if group_values else None,
                }
                provenance[group] = sorted({
                    (row.source, row.sampling_method) for row in group_rows
                    if not row.is_missing
                })
                missing_counts[group] = sum(row.is_missing for row in group_rows)
            entry["total"] = {
                "available": len(values),
                "coverage_percent": round(100 * len(values) / len(feature_rows), 2),
                "min": min(values) if values else None,
                "median": float(np.median(values)) if values else None,
                "max": max(values) if values else None,
            }
            presence_values = [
                row.value for row in feature_rows
                if row.value is not None
                and sample_type[row.prediction_model_sample_id] == "PRESENCE"
            ]
            background_values = [
                row.value for row in feature_rows
                if row.value is not None
                and sample_type[row.prediction_model_sample_id] == "BACKGROUND"
            ]
            if presence_values and background_values:
                labels = np.array(
                    [1] * len(presence_values) + [0] * len(background_values)
                )
                combined = np.array(presence_values + background_values)
                point = pointbiserialr(labels, combined)
                mann = mannwhitneyu(presence_values, background_values)
                entry["distribution_association"] = {
                    "point_biserial": float(point.statistic),
                    "rank_biserial_presence_vs_background": float(
                        2 * mann.statistic
                        / (len(presence_values) * len(background_values))
                        - 1
                    ),
                }
            entry["leakage_check"] = {
                "identical_generation_method": provenance["PRESENCE"] == provenance["BACKGROUND"],
                "presence": provenance["PRESENCE"],
                "background": provenance["BACKGROUND"],
                "missing": missing_counts,
            }
            features[name] = entry
        return {
            "feature_version": FEATURE_VERSION,
            "sample_count": len(samples),
            "features": features,
            "reef_feature": {
                "implemented": False,
                "reason": (
                    "UNEP-WCMC Global Distribution of Coral Reefs v4.1 is suitable in coverage, "
                    "but automated use requires explicit non-commercial/commercial license acceptance "
                    "and redistribution conditions; it was not integrated automatically."
                ),
            },
        }
