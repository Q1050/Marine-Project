import json
from datetime import datetime, timezone
from math import floor
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np

from environmental_feature_expansion_service import (
    FEATURE_VERSION,
    GENERATION_VERSION,
    EnvironmentalFeatureExpansionService,
)
from habitat_suitability_service import GRID_SIZE, JAMAICA_BOUNDS
from models import (
    BathymetryGridCell,
    HabitatSuitabilityModel,
    HabitatSuitabilityV3GridCell,
)


MODEL_VERSION = "pterois-volitans-suitability-v3"
EXPECTED_FEATURES = [
    "bathymetry_center_depth",
    "bathymetry_neighbor_mean",
    "bathymetry_neighbor_std",
    "bathymetry_local_relief",
    "bathymetry_max_slope",
    "distance_to_land_km",
    "sst_climatology_annual_mean",
    "sst_climatology_monthly_min",
    "sst_climatology_monthly_max",
    "sst_climatology_seasonal_range",
    "salinity_climatology_annual_mean",
]


class HabitatSuitabilityV3GridService:

    def __init__(self, feature_service=None):
        self.feature_service = feature_service or EnvironmentalFeatureExpansionService()

    @staticmethod
    def _band(score):
        if score < 0.2:
            return "VERY_LOW"
        if score < 0.4:
            return "LOW"
        if score < 0.6:
            return "MODERATE"
        if score < 0.8:
            return "HIGH"
        return "VERY_HIGH"

    @staticmethod
    def _candidate_cells():
        longitude_min, longitude_max, latitude_min, latitude_max = JAMAICA_BOUNDS
        return [
            (
                f"{latitude_index}:{longitude_index}",
                round((latitude_index + 0.5) * GRID_SIZE, 6),
                round((longitude_index + 0.5) * GRID_SIZE, 6),
            )
            for latitude_index in range(
                round(latitude_min / GRID_SIZE), round(latitude_max / GRID_SIZE)
            )
            for longitude_index in range(
                round(longitude_min / GRID_SIZE), round(longitude_max / GRID_SIZE)
            )
        ]

    def generate(self, db, scientific_name="Pterois volitans"):
        record = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.scientific_name == scientific_name,
            HabitatSuitabilityModel.model_version == MODEL_VERSION,
        ).one_or_none()
        if record is None:
            raise ValueError(f"Model not found: {MODEL_VERSION}")
        features = json.loads(record.feature_list_json)
        validation = json.loads(record.validation_metrics_json)
        if record.algorithm != "HistGradientBoostingClassifier":
            raise ValueError(f"Unexpected v3 algorithm: {record.algorithm}")
        if validation.get("feature_version") != FEATURE_VERSION:
            raise ValueError("The v3 artifact does not use the expected feature version")
        if record.training_generation_version != GENERATION_VERSION:
            raise ValueError("The v3 artifact does not use caribbean-grid-v2")
        if features != EXPECTED_FEATURES:
            raise ValueError(f"Unexpected stored v3 feature list: {features}")

        existing = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.model_version == MODEL_VERSION
        ).count()
        if existing:
            return {"already_generated": True, "stored_cells": existing}

        artifact_path = Path(record.artifact_path)
        if not artifact_path.exists():
            raise FileNotFoundError(artifact_path)
        model = joblib.load(artifact_path)

        candidates = self._candidate_cells()
        identifiers = [item[0] for item in candidates]
        cached = {
            row.grid_cell_id: row
            for row in db.query(BathymetryGridCell).filter(
                BathymetryGridCell.grid_cell_id.in_(identifiers)
            ).all()
        }
        missing = [item for item in candidates if item[0] not in cached]
        from concurrent.futures import ThreadPoolExecutor

        def classify(item):
            identifier, latitude, longitude = item
            result = self.feature_service.environmental_service.classify_marine_coordinate(
                latitude, longitude
            )
            return identifier, latitude, longitude, result

        with ThreadPoolExecutor(max_workers=24) as executor:
            for identifier, latitude, longitude, result in executor.map(classify, missing):
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

        marine = []
        for index, (identifier, latitude, longitude) in enumerate(candidates, start=1):
            bathymetry = cached.get(identifier)
            if (
                bathymetry is not None
                and bathymetry.classification == "MARINE"
                and bathymetry.depth is not None
            ):
                marine.append(SimpleNamespace(
                    id=index,
                    grid_cell_id=identifier,
                    latitude=latitude,
                    longitude=longitude,
                    depth=float(bathymetry.depth),
                ))

        climatology = self.feature_service._climatology_features(marine)
        coast_vertices = self.feature_service._coast_vertices()
        neighborhoods = self.feature_service._bathymetry_neighborhoods(db, marine)
        generated_at = datetime.now(timezone.utc)
        rows = []
        for cell in marine:
            temperature = climatology[cell.id]["temperature"]
            salinity = climatology[cell.id]["salinity"]
            temperature_values = [item[0] for item in temperature]
            salinity_values = [item[0] for item in salinity]
            neighborhood = neighborhoods[cell.id]
            neighbors = neighborhood["values"]
            values = {
                "bathymetry_center_depth": cell.depth,
                "bathymetry_neighbor_mean": float(np.mean(neighbors)) if neighbors else None,
                "bathymetry_neighbor_std": float(np.std(neighbors)) if neighbors else None,
                "bathymetry_local_relief": (
                    float(max(neighbors + [cell.depth]) - min(neighbors + [cell.depth]))
                    if neighbors else None
                ),
                "bathymetry_max_slope": (
                    float(max(neighborhood["slopes"])) if neighborhood["slopes"] else None
                ),
                "distance_to_land_km": self.feature_service._nearest_vertex_distance(
                    coast_vertices, cell.latitude, cell.longitude
                ),
                "sst_climatology_annual_mean": (
                    float(np.mean(temperature_values)) if temperature_values else None
                ),
                "sst_climatology_monthly_min": (
                    float(np.min(temperature_values)) if temperature_values else None
                ),
                "sst_climatology_monthly_max": (
                    float(np.max(temperature_values)) if temperature_values else None
                ),
                "sst_climatology_seasonal_range": (
                    float(np.max(temperature_values) - np.min(temperature_values))
                    if temperature_values else None
                ),
                "salinity_climatology_annual_mean": (
                    float(np.mean(salinity_values)) if salinity_values else None
                ),
            }
            missing_features = [name for name in features if values[name] is None]
            score = None
            status = "INCOMPLETE_FEATURES"
            band = None
            if not missing_features:
                matrix = np.asarray([[values[name] for name in features]], dtype=float)
                score = float(model.predict_proba(matrix)[0, 1])
                band = self._band(score)
                status = "SCORED"
            rows.append(HabitatSuitabilityV3GridCell(
                scientific_name=scientific_name,
                model_version=MODEL_VERSION,
                grid_cell_id=cell.grid_cell_id,
                latitude=cell.latitude,
                longitude=cell.longitude,
                grid_size=GRID_SIZE,
                suitability_score=score,
                suitability_band=band,
                prediction_status=status,
                feature_values_json=json.dumps(values),
                missing_features_json=json.dumps(missing_features),
                generated_at=generated_at,
            ))
        db.add_all(rows)
        db.commit()
        return {
            "already_generated": False,
            "candidate_cells": len(candidates),
            "marine_cells": len(marine),
            "stored_cells": len(rows),
            "scored_cells": sum(row.prediction_status == "SCORED" for row in rows),
            "incomplete_cells": sum(row.prediction_status != "SCORED" for row in rows),
        }
