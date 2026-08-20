import json
import math
from datetime import datetime, timezone

import numpy as np

from database import SessionLocal
from directional_connectivity_service import (
    DirectionalConnectivityService,
    INTERPRETATION_WARNING,
)
from models import HabitatSuitabilityV3GridCell
from ocean_current_service import OceanCurrentLookupService


TIMESTAMP = datetime(2018, 12, 4, 12, tzinfo=timezone.utc)
DEPTH_M = 0.0
SOURCE_TARGETS = [
    (16.95, -78.55),
    (16.95, -76.05),
    (17.75, -77.35),
    (18.65, -78.55),
    (18.65, -76.05),
]


def destination(latitude, longitude, bearing, distance_km):
    angular_distance = distance_km / 6371.0088
    latitude_a = math.radians(latitude)
    longitude_a = math.radians(longitude)
    bearing = math.radians(bearing)
    latitude_b = math.asin(
        math.sin(latitude_a) * math.cos(angular_distance)
        + math.cos(latitude_a) * math.sin(angular_distance) * math.cos(bearing)
    )
    longitude_b = longitude_a + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude_a),
        math.cos(angular_distance) - math.sin(latitude_a) * math.sin(latitude_b),
    )
    return math.degrees(latitude_b), ((math.degrees(longitude_b) + 180) % 360) - 180


def distribution(values):
    if not values:
        return {"count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": float(np.min(values)),
        "p25": float(np.percentile(values, 25)),
        "median": float(np.median(values)),
        "p75": float(np.percentile(values, 75)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def distance_band(distance):
    if distance <= 10:
        return "0-10_km"
    if distance <= 25:
        return ">10-25_km"
    if distance <= 50:
        return ">25-50_km"
    if distance <= 100:
        return ">50-100_km"
    return ">100_km"


def nearest_valid_sources(cells, lookup):
    valid = []
    for target in SOURCE_TARGETS:
        ordered = sorted(
            cells,
            key=lambda cell: (
                (cell.latitude - target[0]) ** 2 + (cell.longitude - target[1]) ** 2,
                cell.grid_cell_id,
            ),
        )
        for cell in ordered:
            current = lookup.get_current(
                cell.latitude, cell.longitude, TIMESTAMP, DEPTH_M, "HYCOM"
            )
            if current["status"] == "VALID":
                valid.append((cell, current))
                break
    return valid


def run():
    db = SessionLocal()
    try:
        cells = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.model_version
            == "pterois-volitans-suitability-v3"
        ).order_by(
            HabitatSuitabilityV3GridCell.latitude,
            HabitatSuitabilityV3GridCell.longitude,
        ).all()
    finally:
        db.close()
    lookup = OceanCurrentLookupService()
    service = DirectionalConnectivityService(lookup)
    sources = nearest_valid_sources(cells, lookup)
    real_examples = []
    grid_experiments = []
    masked_sources = 0
    for source_index, (source, current) in enumerate(sources):
        if current["status"] != "VALID":
            masked_sources += 1
            continue
        examples = []
        for label, offset in (
            ("DOWNSTREAM", 0), ("CROSS_CURRENT", 90), ("UPSTREAM", 180)
        ):
            candidate = destination(
                source.latitude, source.longitude,
                current["toward_bearing_degrees"] + offset, 20,
            )
            value = service.calculate_with_current(
                source.latitude, source.longitude,
                candidate[0], candidate[1], current,
            )
            value["constructed_relationship"] = label
            examples.append(value)
        real_examples.append({
            "source_grid_cell_id": source.grid_cell_id,
            "examples": examples,
        })
        if source_index >= 3:
            continue
        values = []
        for candidate in cells:
            if candidate.grid_cell_id == source.grid_cell_id:
                continue
            value = service.calculate_with_current(
                source.latitude, source.longitude,
                candidate.latitude, candidate.longitude, current,
            )
            value["grid_cell_id"] = candidate.grid_cell_id
            values.append(value)
        ranked = sorted(
            values,
            key=lambda item: (-item["downstream_alignment"], item["grid_cell_id"]),
        )
        bands = {}
        for name in ("0-10_km", ">10-25_km", ">25-50_km", ">50-100_km", ">100_km"):
            bands[name] = distribution([
                item["downstream_alignment"] for item in values
                if distance_band(item["source_to_candidate_distance_km"]) == name
            ])
        grid_experiments.append({
            "source": {"latitude": source.latitude, "longitude": source.longitude, "grid_cell_id": source.grid_cell_id},
            "current": current,
            "candidate_cells_evaluated": len(values),
            "candidate_cells_with_valid_source_current": len(values),
            "alignment_distribution": distribution([item["alignment"] for item in values]),
            "downstream_alignment_distribution": distribution([item["downstream_alignment"] for item in values]),
            "downstream_alignment_by_distance_band": bands,
            "top_10_downstream_cells": [
                {key: item[key] for key in (
                    "grid_cell_id", "candidate", "source_to_candidate_distance_km",
                    "source_to_candidate_bearing_degrees", "angular_difference_degrees",
                    "alignment", "downstream_alignment",
                )}
                for item in ranked[:10]
            ],
            "bottom_10_upstream_cells": [
                {key: item[key] for key in (
                    "grid_cell_id", "candidate", "source_to_candidate_distance_km",
                    "source_to_candidate_bearing_degrees", "angular_difference_degrees",
                    "alignment", "downstream_alignment",
                )}
                for item in sorted(values, key=lambda item: (item["alignment"], item["grid_cell_id"]))[:10]
            ],
        })
    return {
        "experiment": "single-vector environmental directional-connectivity geometry",
        "timestamp": TIMESTAMP.isoformat(),
        "depth_m": DEPTH_M,
        "provider": "HYCOM",
        "interpretation_warning": INTERPRETATION_WARNING,
        "real_vector_examples": real_examples,
        "jamaica_grid_experiments": grid_experiments,
        "tested_sources": len(sources),
        "masked_sources": masked_sources,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
