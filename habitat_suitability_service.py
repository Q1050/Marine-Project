from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from math import floor
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from environmental_feature_service import DEPTH_SOURCE, EnvironmentalFeatureService
from models import (
    HabitatSuitabilityGridCell,
    HabitatSuitabilityModel,
    HabitatSuitabilityV3GridCell,
    PredictionModelSample,
)


MODEL_VERSION = "pterois-volitans-suitability-v1"
TRAINING_GENERATION_VERSION = "caribbean-grid-v1"
GRID_SIZE = 0.1
SPATIAL_BLOCK_SIZE = 2.0
JAMAICA_BOUNDS = (-78.6, -75.9, 16.9, 18.7)
ARTIFACT_DIRECTORY = Path("prediction_models")


class HabitatSuitabilityService:

    def __init__(self, environmental_service=None):
        self.environmental_service = environmental_service or EnvironmentalFeatureService(
            timeout=5
        )

    @staticmethod
    def _pipeline():
        return Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(
                class_weight="balanced",
                max_iter=1000,
                random_state=20260816,
            )),
        ])

    @staticmethod
    def _spatial_group(latitude, longitude):
        return (
            floor((latitude - 9.0) / SPATIAL_BLOCK_SIZE),
            floor((longitude + 89.0) / SPATIAL_BLOCK_SIZE),
        )

    def _evaluate(self, matrix, labels, groups, features, splits):
        folds = []
        for fold_number, (train_index, test_index) in enumerate(
            splits, start=1
        ):
            model = self._pipeline()
            model.fit(matrix[train_index], labels[train_index])
            scores = model.predict_proba(matrix[test_index])[:, 1]
            predicted = (scores >= 0.5).astype(int)
            test_labels = labels[test_index]
            folds.append({
                "fold": fold_number,
                "samples": int(len(test_index)),
                "presence": int(test_labels.sum()),
                "background": int(len(test_labels) - test_labels.sum()),
                "spatial_blocks": int(len(set(groups[test_index]))),
                "roc_auc": float(roc_auc_score(test_labels, scores)),
                "average_precision": float(average_precision_score(test_labels, scores)),
                "precision": float(precision_score(test_labels, predicted, zero_division=0)),
                "recall": float(recall_score(test_labels, predicted, zero_division=0)),
                "f1": float(f1_score(test_labels, predicted, zero_division=0)),
            })
        metric_names = (
            "roc_auc", "average_precision", "precision", "recall", "f1"
        )
        aggregate = {
            name: {
                "mean": float(np.mean([fold[name] for fold in folds])),
                "std": float(np.std([fold[name] for fold in folds])),
            }
            for name in metric_names
        }
        final_model = self._pipeline().fit(matrix, labels)
        coefficients = {
            feature: float(value)
            for feature, value in zip(
                features,
                final_model.named_steps["classifier"].coef_[0],
            )
        }
        return {
            "features": features,
            "folds": folds,
            "aggregate": aggregate,
            "standardized_coefficients": coefficients,
        }, final_model

    def _jamaica_grid(self, model, scientific_name, model_version, workers):
        longitude_min, longitude_max, latitude_min, latitude_max = JAMAICA_BOUNDS
        cells = [
            (latitude_index, longitude_index)
            for latitude_index in range(
                round(latitude_min / GRID_SIZE), round(latitude_max / GRID_SIZE)
            )
            for longitude_index in range(
                round(longitude_min / GRID_SIZE), round(longitude_max / GRID_SIZE)
            )
        ]

        def classify(indices):
            latitude = round((indices[0] + 0.5) * GRID_SIZE, 6)
            longitude = round((indices[1] + 0.5) * GRID_SIZE, 6)
            return indices, latitude, longitude, self.environmental_service.classify_marine_coordinate(
                latitude, longitude
            )

        rows = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            for indices, latitude, longitude, result in executor.map(classify, cells):
                if result["classification"] != "MARINE":
                    continue
                depth = float(result["depth"])
                score = float(model.predict_proba(
                    np.array([[latitude, longitude, depth]], dtype=float)
                )[0, 1])
                rows.append(HabitatSuitabilityGridCell(
                    model_version=model_version,
                    scientific_name=scientific_name,
                    grid_cell_id=f"{indices[0]}:{indices[1]}",
                    latitude=latitude,
                    longitude=longitude,
                    grid_size=GRID_SIZE,
                    depth=depth,
                    suitability_score=score,
                    depth_source=result["source"],
                ))
        return rows

    def train(
        self,
        db,
        scientific_name="Pterois volitans",
        model_version=MODEL_VERSION,
        training_generation_version=TRAINING_GENERATION_VERSION,
        generate_jamaica_grid=True,
        workers=24,
    ):
        existing = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.model_version == model_version
        ).one_or_none()
        if existing is not None:
            raise FileExistsError(f"Model version already exists: {model_version}")

        samples = db.query(PredictionModelSample).filter(
            PredictionModelSample.scientific_name == scientific_name,
            PredictionModelSample.generation_version == training_generation_version,
            PredictionModelSample.depth.is_not(None),
        ).all()
        presence_count = sum(sample.sample_type == "PRESENCE" for sample in samples)
        background_count = sum(sample.sample_type == "BACKGROUND" for sample in samples)
        matrix_b = np.array([
            [sample.latitude, sample.longitude, sample.depth] for sample in samples
        ], dtype=float)
        matrix_a = matrix_b[:, :2]
        labels = np.array([
            1 if sample.sample_type == "PRESENCE" else 0 for sample in samples
        ], dtype=int)
        group_tuples = [
            self._spatial_group(sample.latitude, sample.longitude) for sample in samples
        ]
        group_ids = {value: index for index, value in enumerate(sorted(set(group_tuples)))}
        groups = np.array([group_ids[value] for value in group_tuples], dtype=int)
        splits = list(GroupKFold(n_splits=5).split(matrix_b, labels, groups))
        metrics_a, _ = self._evaluate(
            matrix_a, labels, groups, ["latitude", "longitude"], splits
        )
        metrics_b, final_model = self._evaluate(
            matrix_b, labels, groups, ["latitude", "longitude", "depth"], splits
        )

        ARTIFACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        artifact_path = ARTIFACT_DIRECTORY / f"{model_version}.joblib"
        if artifact_path.exists():
            raise FileExistsError(f"Model artifact already exists: {artifact_path}")
        joblib.dump(final_model, artifact_path)

        grid_rows = (
            self._jamaica_grid(final_model, scientific_name, model_version, workers)
            if generate_jamaica_grid else []
        )
        validation = {
            "spatial_block_size_degrees": SPATIAL_BLOCK_SIZE,
            "spatial_block_count": len(group_ids),
            "fold_count": 5,
            "model_a": metrics_a,
            "model_b": metrics_b,
            "depth_improved_mean_roc_auc": (
                metrics_b["aggregate"]["roc_auc"]["mean"]
                > metrics_a["aggregate"]["roc_auc"]["mean"]
            ),
            "depth_improved_mean_average_precision": (
                metrics_b["aggregate"]["average_precision"]["mean"]
                > metrics_a["aggregate"]["average_precision"]["mean"]
            ),
        }
        record = HabitatSuitabilityModel(
            model_version=model_version,
            scientific_name=scientific_name,
            algorithm="LogisticRegression",
            feature_list_json=json.dumps(["latitude", "longitude", "depth"]),
            training_generation_version=training_generation_version,
            training_sample_count=len(samples),
            eligible_presence_count=presence_count,
            eligible_background_count=background_count,
            spatial_block_count=len(group_ids),
            validation_metrics_json=json.dumps(validation),
            coefficients_json=json.dumps(metrics_b["standardized_coefficients"]),
            artifact_path=str(artifact_path),
            trained_at=datetime.now(timezone.utc),
        )
        db.add(record)
        db.add_all(grid_rows)
        try:
            db.commit()
        except Exception:
            db.rollback()
            artifact_path.unlink(missing_ok=True)
            raise
        return self.model_summary(db, scientific_name, model_version)

    def summary(self, db, scientific_name, model_version=None, suitability_deployment_id=None):
        if model_version == "pterois-volitans-suitability-v3":
            return self._v3_summary(db, scientific_name, model_version, suitability_deployment_id)
        record = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.scientific_name == scientific_name,
            *([HabitatSuitabilityModel.model_version == model_version] if model_version else []),
            HabitatSuitabilityModel.model_version.in_(
                db.query(HabitatSuitabilityGridCell.model_version).distinct()
            ),
        ).order_by(HabitatSuitabilityModel.trained_at.desc()).first()
        return self._summary_for_record(db, scientific_name, record)

    def _v3_summary(self, db, scientific_name, model_version, suitability_deployment_id=None):
        record = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.scientific_name == scientific_name,
            HabitatSuitabilityModel.model_version == model_version,
        ).one_or_none()
        if record is None:
            return None
        cells_query = db.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
            HabitatSuitabilityV3GridCell.model_version == model_version,
        )
        if suitability_deployment_id is not None:
            cells_query = cells_query.filter(HabitatSuitabilityV3GridCell.suitability_deployment_id == suitability_deployment_id)
        cells = cells_query.all()
        validation = json.loads(record.validation_metrics_json)
        selected = validation["selection"]["selected_model"]
        aggregate = validation["models"][selected]["aggregate"]
        scored = [cell for cell in cells if cell.suitability_score is not None]
        scores = [cell.suitability_score for cell in scored]
        bands = {name: 0 for name in ("VERY_LOW", "LOW", "MODERATE", "HIGH", "VERY_HIGH")}
        for cell in scored:
            bands[cell.suitability_band] += 1
        missing = [json.loads(cell.missing_features_json) for cell in cells]
        return {
            "species": scientific_name,
            "model_version": record.model_version,
            "algorithm": record.algorithm,
            "features": json.loads(record.feature_list_json),
            "training_generation_version": record.training_generation_version,
            "feature_version": validation.get("feature_version"),
            "spatial_validation_roc_auc": aggregate["roc_auc"],
            "spatial_validation_pr_auc": aggregate["average_precision"],
            "jamaica_grid_cell_count": len(cells),
            "scored_cells": len(scored),
            "incomplete_cells": len(cells) - len(scored),
            "suitability_score_label": "relative habitat-suitability score",
            "suitability_score": {
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "mean": float(np.mean(scores)) if scores else None,
                "median": float(np.median(scores)) if scores else None,
            },
            "suitability_band_counts": bands,
            "feature_failures": {
                "woa": sum(any(name.startswith("sst_") or name.startswith("salinity_") for name in names) for names in missing),
                "bathymetry": sum(any(name.startswith("bathymetry_") for name in names) for names in missing),
                "coastline": sum("distance_to_land_km" in names for names in missing),
            },
            "top_20_scoring_cells": [
                {
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "grid_size": cell.grid_size,
                    "suitability_score": cell.suitability_score,
                    "suitability_band": cell.suitability_band,
                    "prediction_status": cell.prediction_status,
                }
                for cell in sorted(scored, key=lambda item: item.suitability_score, reverse=True)[:20]
            ],
        }

    def model_summary(self, db, scientific_name, model_version):
        record = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.scientific_name == scientific_name,
            HabitatSuitabilityModel.model_version == model_version,
        ).one_or_none()
        return self._summary_for_record(db, scientific_name, record)

    def _summary_for_record(self, db, scientific_name, record):
        if record is None:
            return None
        cells = db.query(HabitatSuitabilityGridCell).filter(
            HabitatSuitabilityGridCell.model_version == record.model_version
        ).all()
        scores = [cell.suitability_score for cell in cells]
        highest = sorted(cells, key=lambda cell: cell.suitability_score, reverse=True)[:10]
        return {
            "species": scientific_name,
            "model_version": record.model_version,
            "algorithm": record.algorithm,
            "features": json.loads(record.feature_list_json),
            "training_generation_version": record.training_generation_version,
            "training_sample_count": record.training_sample_count,
            "eligible_presence_count": record.eligible_presence_count,
            "eligible_background_count": record.eligible_background_count,
            "spatial_block_count": record.spatial_block_count,
            "spatial_validation_metrics": json.loads(record.validation_metrics_json),
            "standardized_coefficients": json.loads(record.coefficients_json),
            "artifact_path": record.artifact_path,
            "trained_at": record.trained_at.isoformat(),
            "jamaica_grid_cell_count": len(cells),
            "suitability_score": {
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "mean": float(np.mean(scores)) if scores else None,
            },
            "highest_scoring_cells": [
                {
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "grid_size": cell.grid_size,
                    "suitability_score": cell.suitability_score,
                    "depth": cell.depth,
                }
                for cell in highest
            ],
        }

    def grid(self, db, scientific_name, model_version=None, suitability_deployment_id=None):
        if model_version == "pterois-volitans-suitability-v3":
            cells_query = db.query(HabitatSuitabilityV3GridCell).filter(
                HabitatSuitabilityV3GridCell.scientific_name == scientific_name,
                HabitatSuitabilityV3GridCell.model_version == model_version,
            )
            if suitability_deployment_id is not None:
                cells_query = cells_query.filter(HabitatSuitabilityV3GridCell.suitability_deployment_id == suitability_deployment_id)
            cells = cells_query.order_by(HabitatSuitabilityV3GridCell.latitude, HabitatSuitabilityV3GridCell.longitude).all()
            if not cells:
                return None
            return {
                "species": scientific_name,
                "model_version": model_version,
                "grid_size": GRID_SIZE,
                "score_interpretation": "relative habitat-suitability score; not an occurrence, invasion, or spread probability",
                "cells": [
                    {
                        "latitude": cell.latitude,
                        "longitude": cell.longitude,
                        "grid_size": cell.grid_size,
                        "suitability_score": cell.suitability_score,
                        "suitability_band": cell.suitability_band,
                        "prediction_status": cell.prediction_status,
                    }
                    for cell in cells
                ],
            }
        record = db.query(HabitatSuitabilityModel).filter(
            HabitatSuitabilityModel.scientific_name == scientific_name,
            *([HabitatSuitabilityModel.model_version == model_version] if model_version else []),
            HabitatSuitabilityModel.model_version.in_(
                db.query(HabitatSuitabilityGridCell.model_version).distinct()
            ),
        ).order_by(HabitatSuitabilityModel.trained_at.desc()).first()
        if record is None:
            return None
        cells = db.query(HabitatSuitabilityGridCell).filter(
            HabitatSuitabilityGridCell.model_version == record.model_version
        ).order_by(HabitatSuitabilityGridCell.latitude, HabitatSuitabilityGridCell.longitude).all()
        return {
            "species": scientific_name,
            "model_version": record.model_version,
            "grid_size": GRID_SIZE,
            "cells": [
                {
                    "latitude": cell.latitude,
                    "longitude": cell.longitude,
                    "grid_size": cell.grid_size,
                    "suitability_score": cell.suitability_score,
                    "depth": cell.depth,
                }
                for cell in cells
            ],
        }
