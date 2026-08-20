from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from math import floor
import json
import random

import numpy as np
from scipy.stats import mannwhitneyu, pointbiserialr

from environmental_feature_service import DEPTH_SOURCE, EnvironmentalFeatureService
from models import (
    BathymetryGridCell,
    HabitatSuitabilityGridCell,
    PredictionModelDatasetAudit,
    PredictionModelDatasetGeneration,
    PredictionModelSample,
    PredictionTrainingOccurrence,
)
from prediction_training_occurrence_service import GRID_SIZE, TRAINING_REGION_NAME


GENERATION_VERSION = "caribbean-grid-v2"
SCIENTIFIC_NAME = "Pterois volitans"
SEED = 20260816
BACKGROUND_RATIO = 5
MAX_DEPTH = 500.0
LATITUDE_MIN, LATITUDE_MAX = 9.0, 28.0
LONGITUDE_MIN, LONGITUDE_MAX = -89.0, -59.0
DEPTH_STRATA = (
    ("0-10", 0.0, 10.0),
    (">10-25", 10.0, 25.0),
    (">25-50", 25.0, 50.0),
    (">50-100", 50.0, 100.0),
    (">100-200", 100.0, 200.0),
    (">200-500", 200.0, 500.0),
)


class PredictionModelDatasetV2Service:

    def __init__(self, environmental_service=None):
        self.environmental_service = environmental_service or EnvironmentalFeatureService(
            timeout=5
        )

    @staticmethod
    def _indices(latitude, longitude):
        return floor(latitude / GRID_SIZE), floor(longitude / GRID_SIZE)

    @staticmethod
    def _cell_id(indices):
        return f"{indices[0]}:{indices[1]}"

    @staticmethod
    def _center(indices):
        return (
            round((indices[0] + 0.5) * GRID_SIZE, 6),
            round((indices[1] + 0.5) * GRID_SIZE, 6),
        )

    @staticmethod
    def _block(latitude, longitude):
        return f"{floor((latitude - LATITUDE_MIN) / 2)}:{floor((longitude - LONGITUDE_MIN) / 2)}"

    @staticmethod
    def _stratum(depth):
        for name, lower, upper in DEPTH_STRATA:
            if lower < depth <= upper:
                return name
        return None

    @staticmethod
    def _depth_summary(values):
        array = np.asarray(values, dtype=float)
        return {
            "count": len(values),
            "min": float(array.min()),
            "p05": float(np.percentile(array, 5)),
            "p25": float(np.percentile(array, 25)),
            "median": float(np.median(array)),
            "p75": float(np.percentile(array, 75)),
            "p95": float(np.percentile(array, 95)),
            "max": float(array.max()),
            "mean": float(array.mean()),
            "std": float(array.std()),
        }

    def _seed_cache(self, db):
        existing = {
            value for (value,) in db.query(BathymetryGridCell.grid_cell_id).all()
        }
        rows = []
        for sample in db.query(PredictionModelSample).filter(
            PredictionModelSample.generation_version == "caribbean-grid-v1",
            PredictionModelSample.sample_type == "BACKGROUND",
            PredictionModelSample.depth_sampling_method == "EXACT",
            PredictionModelSample.depth.is_not(None),
        ):
            if sample.grid_cell_id not in existing:
                rows.append(BathymetryGridCell(
                    grid_cell_id=sample.grid_cell_id,
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    classification="MARINE",
                    depth=sample.depth,
                    source=sample.depth_source or DEPTH_SOURCE,
                ))
                existing.add(sample.grid_cell_id)
        for cell in db.query(HabitatSuitabilityGridCell).all():
            if cell.grid_cell_id not in existing:
                rows.append(BathymetryGridCell(
                    grid_cell_id=cell.grid_cell_id,
                    latitude=cell.latitude,
                    longitude=cell.longitude,
                    classification="MARINE",
                    depth=cell.depth,
                    source=cell.depth_source,
                ))
                existing.add(cell.grid_cell_id)
        db.add_all(rows)
        db.commit()

    def _classify_batch(self, db, indices_batch, workers):
        identifiers = [self._cell_id(indices) for indices in indices_batch]
        cached = {
            row.grid_cell_id: row
            for row in db.query(BathymetryGridCell).filter(
                BathymetryGridCell.grid_cell_id.in_(identifiers)
            ).all()
        }
        missing = [indices for indices in indices_batch if self._cell_id(indices) not in cached]

        def lookup(indices):
            latitude, longitude = self._center(indices)
            return indices, latitude, longitude, self.environmental_service.classify_marine_coordinate(
                latitude, longitude
            )

        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            results = list(executor.map(lookup, missing))
        new_rows = []
        unavailable = {}
        for indices, latitude, longitude, result in results:
            identifier = self._cell_id(indices)
            if result["classification"] == "UNAVAILABLE":
                unavailable[identifier] = result
                continue
            row = BathymetryGridCell(
                grid_cell_id=identifier,
                latitude=latitude,
                longitude=longitude,
                classification=result["classification"],
                depth=result["depth"],
                source=result["source"],
            )
            new_rows.append(row)
            cached[identifier] = row
        db.add_all(new_rows)
        db.commit()
        return {
            identifier: {
                "classification": row.classification,
                "depth": row.depth,
                "source": row.source,
            }
            for identifier, row in cached.items()
        } | unavailable

    @staticmethod
    def _balanced_by_block(candidates, target):
        by_block = defaultdict(deque)
        for candidate in candidates:
            by_block[candidate["block"]].append(candidate)
        selected = []
        block_names = sorted(by_block)
        while len(selected) < target and block_names:
            remaining = []
            for block in block_names:
                if by_block[block]:
                    selected.append(by_block[block].popleft())
                    if len(selected) >= target:
                        break
                if by_block[block]:
                    remaining.append(block)
            block_names = remaining
        return selected

    def generate(self, db, workers=24):
        existing = db.query(PredictionModelDatasetGeneration).filter(
            PredictionModelDatasetGeneration.scientific_name == SCIENTIFIC_NAME,
            PredictionModelDatasetGeneration.generation_version == GENERATION_VERSION,
        ).one_or_none()
        if existing is not None:
            return self.diagnostics(db) | {
                "already_generated": True,
                "new_samples_inserted": 0,
            }

        self._seed_cache(db)
        occurrences = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == SCIENTIFIC_NAME
        ).all()
        presence_groups = defaultdict(list)
        for occurrence in occurrences:
            presence_groups[self._indices(
                occurrence.latitude, occurrence.longitude
            )].append(occurrence)
        presence_indices = sorted(presence_groups)
        presence_results = self._classify_batch(db, presence_indices, workers)
        presence_samples = []
        excluded_over_depth = 0
        excluded_unavailable = 0
        excluded_non_marine = 0
        presence_strata = Counter()
        for indices in presence_indices:
            result = presence_results.get(self._cell_id(indices), {})
            if result.get("classification") == "UNAVAILABLE":
                excluded_unavailable += 1
                continue
            if result.get("classification") != "MARINE":
                excluded_non_marine += 1
                continue
            depth = result["depth"]
            if depth > MAX_DEPTH:
                excluded_over_depth += 1
                continue
            stratum = self._stratum(depth)
            if stratum is None:
                excluded_non_marine += 1
                continue
            values = presence_groups[indices]
            dates = sorted(value.event_date for value in values if value.event_date)
            latitude, longitude = self._center(indices)
            presence_strata[stratum] += 1
            presence_samples.append(PredictionModelSample(
                scientific_name=SCIENTIFIC_NAME,
                grid_cell_id=self._cell_id(indices),
                latitude=latitude,
                longitude=longitude,
                sample_type="PRESENCE",
                occurrence_count=len(values),
                unique_location_count=len({
                    (round(value.latitude, 6), round(value.longitude, 6)) for value in values
                }),
                earliest_occurrence_date=dates[0] if dates else None,
                latest_occurrence_date=dates[-1] if dates else None,
                depth=depth,
                sst=None,
                salinity=None,
                depth_source=result["source"],
                depth_sampling_method="EXACT",
                marine_filter_source=result["source"],
                generation_version=GENERATION_VERSION,
                generation_seed=SEED,
                background_ratio=BACKGROUND_RATIO,
            ))

        quotas = {
            name: presence_strata[name] * BACKGROUND_RATIO
            for name, _, _ in DEPTH_STRATA
        }
        pool_targets = {name: max(quota, int(quota * 1.25)) for name, quota in quotas.items()}
        all_cells = [
            (latitude_index, longitude_index)
            for latitude_index in range(round(LATITUDE_MIN / GRID_SIZE), round(LATITUDE_MAX / GRID_SIZE))
            for longitude_index in range(round(LONGITUDE_MIN / GRID_SIZE), round(LONGITUDE_MAX / GRID_SIZE))
        ]
        random.Random(SEED).shuffle(all_cells)
        candidates = [indices for indices in all_cells if indices not in presence_groups]
        candidate_pools = defaultdict(list)
        terrestrial_rejected = 0
        unavailable_rejected = 0
        eligible_candidates = 0
        candidates_evaluated = 0
        batch_size = max(200, workers * 20)
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start:start + batch_size]
            results = self._classify_batch(db, batch, workers)
            for indices in batch:
                candidates_evaluated += 1
                result = results.get(self._cell_id(indices), {})
                if result.get("classification") == "TERRESTRIAL":
                    terrestrial_rejected += 1
                    continue
                if result.get("classification") != "MARINE":
                    unavailable_rejected += 1
                    continue
                depth = result["depth"]
                stratum = self._stratum(depth)
                if stratum is None:
                    continue
                eligible_candidates += 1
                latitude, longitude = self._center(indices)
                candidate_pools[stratum].append({
                    "indices": indices,
                    "latitude": latitude,
                    "longitude": longitude,
                    "depth": depth,
                    "source": result["source"],
                    "block": self._block(latitude, longitude),
                })
            if all(len(candidate_pools[name]) >= target for name, target in pool_targets.items()):
                break

        selected = []
        shortages = {}
        for name, _, _ in DEPTH_STRATA:
            chosen = self._balanced_by_block(candidate_pools[name], quotas[name])
            selected.extend(chosen)
            shortages[name] = max(0, quotas[name] - len(chosen))
        background_samples = [
            PredictionModelSample(
                scientific_name=SCIENTIFIC_NAME,
                grid_cell_id=self._cell_id(item["indices"]),
                latitude=item["latitude"],
                longitude=item["longitude"],
                sample_type="BACKGROUND",
                occurrence_count=0,
                unique_location_count=0,
                depth=item["depth"],
                sst=None,
                salinity=None,
                depth_source=item["source"],
                depth_sampling_method="EXACT",
                marine_filter_source=item["source"],
                generation_version=GENERATION_VERSION,
                generation_seed=SEED,
                background_ratio=BACKGROUND_RATIO,
            )
            for item in selected
        ]
        configuration = {
            "seed": SEED,
            "grid_size": GRID_SIZE,
            "background_ratio": BACKGROUND_RATIO,
            "depth_domain_m": {"min_exclusive": 0, "max_inclusive": MAX_DEPTH},
            "depth_strata": [name for name, _, _ in DEPTH_STRATA],
            "depth_sampling": "NOAA ETOPO1 exact deterministic grid-cell center for both classes",
            "background_sampling": "presence-proportional depth-stratum quotas; deterministic round-robin across 2-degree blocks",
        }
        audit = {
            "original_presence_cells": len(presence_indices),
            "presence_excluded_over_500m": excluded_over_depth,
            "presence_excluded_bathymetry_unavailable": excluded_unavailable,
            "presence_excluded_non_marine": excluded_non_marine,
            "known_presence_candidates_rejected": len(presence_indices),
            "terrestrial_candidates_rejected": terrestrial_rejected,
            "unavailable_candidates_rejected": unavailable_rejected,
            "candidates_evaluated": candidates_evaluated,
            "eligible_background_candidates_available": eligible_candidates,
            "background_selected": len(background_samples),
            "background_shortages_by_stratum": shortages,
        }
        generation = PredictionModelDatasetGeneration(
            scientific_name=SCIENTIFIC_NAME,
            generation_version=GENERATION_VERSION,
            generation_seed=SEED,
            background_ratio=BACKGROUND_RATIO,
            grid_size=GRID_SIZE,
            training_region=TRAINING_REGION_NAME,
            marine_filter_source=DEPTH_SOURCE,
            terrestrial_candidates_rejected=terrestrial_rejected,
            unavailable_candidates_rejected=unavailable_rejected,
            presence_candidates_rejected=len(presence_indices),
            candidates_evaluated=candidates_evaluated,
        )
        db.add_all(presence_samples + background_samples)
        db.add(generation)
        db.add(PredictionModelDatasetAudit(
            scientific_name=SCIENTIFIC_NAME,
            generation_version=GENERATION_VERSION,
            configuration_json=json.dumps(configuration),
            diagnostics_json=json.dumps(audit),
        ))
        db.commit()
        return self.diagnostics(db) | {
            "already_generated": False,
            "new_samples_inserted": len(presence_samples) + len(background_samples),
        }

    def diagnostics(self, db):
        rows = db.query(PredictionModelSample).filter(
            PredictionModelSample.scientific_name == SCIENTIFIC_NAME,
            PredictionModelSample.generation_version == GENERATION_VERSION,
        ).all()
        audit_row = db.query(PredictionModelDatasetAudit).filter(
            PredictionModelDatasetAudit.scientific_name == SCIENTIFIC_NAME,
            PredictionModelDatasetAudit.generation_version == GENERATION_VERSION,
        ).one_or_none()
        audit = json.loads(audit_row.diagnostics_json) if audit_row else {}
        configuration = json.loads(audit_row.configuration_json) if audit_row else {}
        by_type = {
            name: [row for row in rows if row.sample_type == name]
            for name in ("PRESENCE", "BACKGROUND")
        }
        result = {}
        for name, values in by_type.items():
            depths = [value.depth for value in values]
            result[name.lower()] = {
                "depth": self._depth_summary(depths) if depths else None,
                "depth_bands": dict(Counter(self._stratum(value) for value in depths)),
                "spatial_blocks": dict(Counter(
                    self._block(value.latitude, value.longitude) for value in values
                )),
            }
        presence_depth = [value.depth for value in by_type["PRESENCE"]]
        background_depth = [value.depth for value in by_type["BACKGROUND"]]
        if presence_depth and background_depth:
            sample_type = np.array([1] * len(presence_depth) + [0] * len(background_depth))
            depth = np.array(presence_depth + background_depth)
            point = pointbiserialr(sample_type, depth)
            mann = mannwhitneyu(presence_depth, background_depth)
            association = {
                "point_biserial": float(point.statistic),
                "point_biserial_pvalue": float(point.pvalue),
                "rank_biserial_presence_vs_background": float(
                    2 * mann.statistic / (len(presence_depth) * len(background_depth)) - 1
                ),
                "mann_whitney_pvalue": float(mann.pvalue),
            }
        else:
            association = None
        return {
            "species": SCIENTIFIC_NAME,
            "generation_version": GENERATION_VERSION,
            "configuration": configuration,
            "presence_samples": len(by_type["PRESENCE"]),
            "background_samples": len(by_type["BACKGROUND"]),
            "presence": result.get("presence"),
            "background": result.get("background"),
            "depth_association": association,
            "generation_audit": audit,
        }
