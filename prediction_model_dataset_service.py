from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from math import floor
import random
from statistics import median

from environmental_feature_service import DEPTH_SOURCE, EnvironmentalFeatureService
from models import (
    PredictionModelDatasetGeneration,
    PredictionModelSample,
    PredictionTrainingEnvironmentalFeature,
    PredictionTrainingOccurrence,
)
from prediction_training_occurrence_service import (
    DEFAULT_SCIENTIFIC_NAME,
    GRID_SIZE,
    TRAINING_REGION_NAME,
)


GENERATION_VERSION = "caribbean-grid-v1"
DEFAULT_SEED = 20260816
DEFAULT_BACKGROUND_RATIO = 5.0
LATITUDE_MIN, LATITUDE_MAX = 9.0, 28.0
LONGITUDE_MIN, LONGITUDE_MAX = -89.0, -59.0


class PredictionModelDatasetService:

    def __init__(self, environmental_service=None):
        self.environmental_service = environmental_service or EnvironmentalFeatureService(
            timeout=5
        )

    @staticmethod
    def _cell_indices(latitude, longitude):
        return (
            floor(float(latitude) / GRID_SIZE),
            floor(float(longitude) / GRID_SIZE),
        )

    @staticmethod
    def _cell_id(indices):
        return f"{indices[0]}:{indices[1]}"

    @staticmethod
    def _cell_center(indices):
        return (
            round((indices[0] + 0.5) * GRID_SIZE, 6),
            round((indices[1] + 0.5) * GRID_SIZE, 6),
        )

    @staticmethod
    def _median(values):
        values = [value for value in values if value is not None]
        return float(median(values)) if values else None

    def _presence_cells(self, db, scientific_name):
        rows = db.query(
            PredictionTrainingOccurrence,
            PredictionTrainingEnvironmentalFeature,
        ).outerjoin(
            PredictionTrainingEnvironmentalFeature,
            PredictionTrainingEnvironmentalFeature.prediction_training_occurrence_id
            == PredictionTrainingOccurrence.id,
        ).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name
        ).all()
        cells = defaultdict(list)
        for occurrence, feature in rows:
            cells[self._cell_indices(
                occurrence.latitude, occurrence.longitude
            )].append((occurrence, feature))
        return cells

    def generate(
        self,
        db,
        scientific_name=DEFAULT_SCIENTIFIC_NAME,
        background_ratio=DEFAULT_BACKGROUND_RATIO,
        seed=DEFAULT_SEED,
        generation_version=GENERATION_VERSION,
        workers=24,
    ):
        existing = db.query(PredictionModelDatasetGeneration).filter(
            PredictionModelDatasetGeneration.scientific_name == scientific_name,
            PredictionModelDatasetGeneration.generation_version == generation_version,
        ).one_or_none()
        if existing is not None:
            result = self.summary(db, scientific_name, generation_version)
            result["new_samples_inserted"] = 0
            result["already_generated"] = True
            return result

        presence_cells = self._presence_cells(db, scientific_name)
        if not presence_cells:
            raise ValueError(f"No prediction-training occurrences for {scientific_name}")

        samples = []
        original_counts = Counter()
        for indices, cell_rows in sorted(presence_cells.items()):
            occurrences = [row[0] for row in cell_rows]
            features = [row[1] for row in cell_rows if row[1] is not None]
            dates = sorted(
                occurrence.event_date for occurrence in occurrences
                if occurrence.event_date is not None
            )
            latitude, longitude = self._cell_center(indices)
            original_counts[indices] = len(occurrences)
            samples.append(PredictionModelSample(
                scientific_name=scientific_name,
                grid_cell_id=self._cell_id(indices),
                latitude=latitude,
                longitude=longitude,
                sample_type="PRESENCE",
                occurrence_count=len(occurrences),
                unique_location_count=len({
                    (round(item.latitude, 6), round(item.longitude, 6))
                    for item in occurrences
                }),
                earliest_occurrence_date=dates[0] if dates else None,
                latest_occurrence_date=dates[-1] if dates else None,
                depth=self._median([feature.depth for feature in features]),
                sst=self._median([feature.sst for feature in features]),
                salinity=self._median([feature.salinity for feature in features]),
                depth_source=DEPTH_SOURCE,
                sst_source="Aggregated training-occurrence environmental features",
                salinity_source="Aggregated training-occurrence environmental features",
                depth_sampling_method="CELL_AGGREGATE",
                marine_filter_source="Known OBIS marine occurrence cell",
                generation_version=generation_version,
                generation_seed=seed,
                background_ratio=background_ratio,
            ))

        target_background = round(len(presence_cells) * background_ratio)
        all_cells = [
            (latitude_index, longitude_index)
            for latitude_index in range(
                round(LATITUDE_MIN / GRID_SIZE), round(LATITUDE_MAX / GRID_SIZE)
            )
            for longitude_index in range(
                round(LONGITUDE_MIN / GRID_SIZE), round(LONGITUDE_MAX / GRID_SIZE)
            )
        ]
        random.Random(seed).shuffle(all_cells)
        candidate_cells = [cell for cell in all_cells if cell not in presence_cells]
        presence_rejected = len(all_cells) - len(candidate_cells)
        terrestrial_rejected = 0
        unavailable_rejected = 0
        candidates_evaluated = 0
        background_count = 0

        def classify(indices):
            latitude, longitude = self._cell_center(indices)
            return indices, latitude, longitude, self.environmental_service.classify_marine_coordinate(
                latitude, longitude
            )

        batch_size = max(100, workers * 10)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            for start in range(0, len(candidate_cells), batch_size):
                batch = candidate_cells[start:start + batch_size]
                for indices, latitude, longitude, result in executor.map(classify, batch):
                    candidates_evaluated += 1
                    if result["classification"] == "TERRESTRIAL":
                        terrestrial_rejected += 1
                        continue
                    if result["classification"] != "MARINE":
                        unavailable_rejected += 1
                        continue
                    samples.append(PredictionModelSample(
                        scientific_name=scientific_name,
                        grid_cell_id=self._cell_id(indices),
                        latitude=latitude,
                        longitude=longitude,
                        sample_type="BACKGROUND",
                        occurrence_count=0,
                        unique_location_count=0,
                        depth=result["depth"],
                        sst=None,
                        salinity=None,
                        depth_source=result["source"],
                        sst_source=None,
                        salinity_source=None,
                        depth_sampling_method="EXACT",
                        marine_filter_source=result["source"],
                        generation_version=generation_version,
                        generation_seed=seed,
                        background_ratio=background_ratio,
                    ))
                    background_count += 1
                    if background_count >= target_background:
                        break
                if background_count >= target_background:
                    break

        generation = PredictionModelDatasetGeneration(
            scientific_name=scientific_name,
            generation_version=generation_version,
            generation_seed=seed,
            background_ratio=background_ratio,
            grid_size=GRID_SIZE,
            training_region=TRAINING_REGION_NAME,
            marine_filter_source=DEPTH_SOURCE,
            terrestrial_candidates_rejected=terrestrial_rejected,
            unavailable_candidates_rejected=unavailable_rejected,
            presence_candidates_rejected=presence_rejected,
            candidates_evaluated=candidates_evaluated,
        )
        db.add_all(samples)
        db.add(generation)
        db.commit()
        result = self.summary(db, scientific_name, generation_version)
        strongest_cell, strongest_count = original_counts.most_common(1)[0]
        result.update({
            "new_samples_inserted": len(samples),
            "already_generated": False,
            "strongest_original_cell": {
                "grid_cell_id": self._cell_id(strongest_cell),
                "source_occurrences": strongest_count,
                "model_samples": 1,
            },
        })
        return result

    def summary(self, db, scientific_name, generation_version=GENERATION_VERSION):
        samples = db.query(PredictionModelSample).filter(
            PredictionModelSample.scientific_name == scientific_name,
            PredictionModelSample.generation_version == generation_version,
        ).all()
        generation = db.query(PredictionModelDatasetGeneration).filter(
            PredictionModelDatasetGeneration.scientific_name == scientific_name,
            PredictionModelDatasetGeneration.generation_version == generation_version,
        ).one_or_none()
        by_type = {
            sample_type: [sample for sample in samples if sample.sample_type == sample_type]
            for sample_type in ("PRESENCE", "BACKGROUND")
        }

        def diagnostics(sample_type):
            rows = by_type[sample_type]
            return {
                "samples": len(rows),
                "occupied_cells": len({row.grid_cell_id for row in rows}),
                "environmental_coverage": {
                    field: sum(getattr(row, field) is not None for row in rows)
                    for field in ("depth", "sst", "salinity")
                },
                "geographic_range": {
                    "latitude": {
                        "min": min((row.latitude for row in rows), default=None),
                        "max": max((row.latitude for row in rows), default=None),
                    },
                    "longitude": {
                        "min": min((row.longitude for row in rows), default=None),
                        "max": max((row.longitude for row in rows), default=None),
                    },
                },
            }

        presence = diagnostics("PRESENCE")
        background = diagnostics("BACKGROUND")
        strongest = max(
            by_type["PRESENCE"], key=lambda row: row.occurrence_count, default=None
        )
        return {
            "species": scientific_name,
            "generation_version": generation_version,
            "generation_seed": generation.generation_seed if generation else None,
            "background_ratio_configured": generation.background_ratio if generation else None,
            "presence_samples": presence["samples"],
            "background_samples": background["samples"],
            "total_samples": len(samples),
            "presence_background_ratio": (
                round(background["samples"] / presence["samples"], 3)
                if presence["samples"] else None
            ),
            "presence": presence,
            "background": background,
            "candidate_rejections": {
                "terrestrial": generation.terrestrial_candidates_rejected if generation else 0,
                "environmental_unavailable": generation.unavailable_candidates_rejected if generation else 0,
                "known_presence_cell": generation.presence_candidates_rejected if generation else 0,
            },
            "candidates_evaluated": generation.candidates_evaluated if generation else 0,
            "marine_filter_source": generation.marine_filter_source if generation else None,
            "strongest_original_cell": {
                "grid_cell_id": strongest.grid_cell_id if strongest else None,
                "source_occurrences": strongest.occurrence_count if strongest else 0,
                "model_samples": 1 if strongest else 0,
            },
        }
