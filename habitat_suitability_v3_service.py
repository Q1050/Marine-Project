import hashlib
import json
from math import floor
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from habitat_suitability_service import ARTIFACT_DIRECTORY
from models import (
    HabitatSuitabilityModel,
    PredictionModelSample,
    PredictionSampleEnvironmentalFeature,
)


MODEL_VERSION = "pterois-volitans-suitability-v3"
GENERATION_VERSION = "caribbean-grid-v2"
FEATURE_VERSION = "caribbean-grid-v2-environment-v1"
SEED = 20260816

PHYSICAL = [
    "bathymetry_center_depth",
    "bathymetry_neighbor_mean",
    "bathymetry_neighbor_std",
    "bathymetry_local_relief",
    "bathymetry_max_slope",
    "distance_to_land_km",
]
CLIMATE = [
    "sst_climatology_annual_mean",
    "sst_climatology_monthly_min",
    "sst_climatology_monthly_max",
    "sst_climatology_seasonal_range",
    "salinity_climatology_annual_mean",
]
GROUPS = {
    "model_a_geography": ["latitude", "longitude"],
    "model_b_physical_habitat": PHYSICAL,
    "model_c_ocean_climate": CLIMATE,
    "model_d_environment_combined": PHYSICAL + CLIMATE,
    "model_e_geography_environment": ["latitude", "longitude"] + PHYSICAL + CLIMATE,
    "model_f_nonlinear_environment": PHYSICAL + CLIMATE,
}


class HabitatSuitabilityV3Service:

    @staticmethod
    def _logistic():
        return Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(
                class_weight="balanced", max_iter=1000, random_state=SEED
            )),
        ])

    @staticmethod
    def _nonlinear():
        return HistGradientBoostingClassifier(
            learning_rate=0.08,
            max_iter=200,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=SEED,
        )

    @staticmethod
    def _block(latitude, longitude):
        return floor((latitude - 9.0) / 2.0), floor((longitude + 89.0) / 2.0)

    @staticmethod
    def _metrics(labels, scores):
        predicted = (scores >= 0.5).astype(int)
        return {
            "roc_auc": float(roc_auc_score(labels, scores)),
            "average_precision": float(average_precision_score(labels, scores)),
            "precision": float(precision_score(labels, predicted, zero_division=0)),
            "recall": float(recall_score(labels, predicted, zero_division=0)),
            "f1": float(f1_score(labels, predicted, zero_division=0)),
        }

    def _cohort(self, db):
        samples = db.query(PredictionModelSample).filter(
            PredictionModelSample.generation_version == GENERATION_VERSION
        ).order_by(PredictionModelSample.id).all()
        feature_rows = db.query(PredictionSampleEnvironmentalFeature).filter(
            PredictionSampleEnvironmentalFeature.feature_version == FEATURE_VERSION
        ).all()
        by_sample = {}
        for row in feature_rows:
            by_sample.setdefault(row.prediction_model_sample_id, {})[row.feature_name] = row.value
        required = PHYSICAL + CLIMATE
        cohort = [
            sample for sample in samples
            if all(by_sample.get(sample.id, {}).get(name) is not None for name in required)
        ]
        values = {
            sample.id: {
                "latitude": sample.latitude,
                "longitude": sample.longitude,
                **by_sample[sample.id],
            }
            for sample in cohort
        }
        return samples, cohort, values

    def _evaluate(self, name, features, matrix, labels, groups, splits, nonlinear=False):
        folds = []
        importances = []
        for fold_number, (train_index, test_index) in enumerate(splits, 1):
            model = self._nonlinear() if nonlinear else self._logistic()
            fit_kwargs = {}
            if nonlinear:
                fit_kwargs["sample_weight"] = compute_sample_weight(
                    class_weight="balanced", y=labels[train_index]
                )
            model.fit(matrix[train_index], labels[train_index], **fit_kwargs)
            scores = model.predict_proba(matrix[test_index])[:, 1]
            fold_metrics = self._metrics(labels[test_index], scores)
            fold_metrics.update({
                "fold": fold_number,
                "samples": int(len(test_index)),
                "presence": int(labels[test_index].sum()),
                "background": int(len(test_index) - labels[test_index].sum()),
                "spatial_blocks": int(len(set(groups[test_index]))),
            })
            folds.append(fold_metrics)
            if nonlinear:
                importance = permutation_importance(
                    model,
                    matrix[test_index],
                    labels[test_index],
                    scoring="roc_auc",
                    n_repeats=10,
                    random_state=SEED + fold_number,
                )
                importances.append(importance.importances_mean)
        metric_names = ("roc_auc", "average_precision", "precision", "recall", "f1")
        aggregate = {
            metric: {
                "mean": float(np.mean([fold[metric] for fold in folds])),
                "std": float(np.std([fold[metric] for fold in folds])),
            }
            for metric in metric_names
        }
        result = {"features": features, "folds": folds, "aggregate": aggregate}
        if nonlinear:
            importance_matrix = np.asarray(importances)
            result["held_out_permutation_importance_roc_auc"] = {
                feature: {
                    "mean": float(importance_matrix[:, index].mean()),
                    "std_across_folds": float(importance_matrix[:, index].std()),
                }
                for index, feature in enumerate(features)
            }
        else:
            final = self._logistic().fit(matrix, labels)
            result["standardized_coefficients"] = {
                feature: float(coefficient)
                for feature, coefficient in zip(
                    features, final.named_steps["classifier"].coef_[0]
                )
            }
        return result

    @staticmethod
    def _select_candidate(results):
        environment_names = (
            "model_d_environment_combined",
            "model_f_nonlinear_environment",
        )
        best_environment = max(
            environment_names,
            key=lambda name: (
                results[name]["aggregate"]["roc_auc"]["mean"]
                + results[name]["aggregate"]["average_precision"]["mean"]
            ),
        )
        environment = results[best_environment]["aggregate"]
        geography_environment = results["model_e_geography_environment"]["aggregate"]
        geography_material = (
            geography_environment["roc_auc"]["mean"]
            > environment["roc_auc"]["mean"] + 0.02
            and geography_environment["average_precision"]["mean"]
            > environment["average_precision"]["mean"] + 0.02
        )
        selected = (
            "model_e_geography_environment" if geography_material else best_environment
        )
        return selected, {
            "rule": (
                "Prefer the stronger environment-only model unless geography+environment "
                "improves both mean ROC AUC and mean average precision by more than 0.02."
            ),
            "geography_material_improvement": geography_material,
        }

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def train(self, db):
        if db.query(HabitatSuitabilityModel).filter_by(
            model_version=MODEL_VERSION
        ).one_or_none() is not None:
            raise FileExistsError(f"Model version already exists: {MODEL_VERSION}")
        all_samples, cohort, value_map = self._cohort(db)
        counts = {
            sample_type: sum(sample.sample_type == sample_type for sample in cohort)
            for sample_type in ("PRESENCE", "BACKGROUND")
        }
        if counts != {"PRESENCE": 389, "BACKGROUND": 1893}:
            raise ValueError(f"Unexpected complete-case cohort: {counts}")
        labels = np.array([
            1 if sample.sample_type == "PRESENCE" else 0 for sample in cohort
        ])
        group_tuples = [self._block(sample.latitude, sample.longitude) for sample in cohort]
        group_map = {value: index for index, value in enumerate(sorted(set(group_tuples)))}
        groups = np.array([group_map[value] for value in group_tuples])
        splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
        base_matrix = np.array([[sample.latitude, sample.longitude] for sample in cohort])
        splits = list(splitter.split(base_matrix, labels, groups))
        fold_group_sets = [set(groups[test]) for _, test in splits]
        for left in range(len(fold_group_sets)):
            for right in range(left + 1, len(fold_group_sets)):
                if fold_group_sets[left] & fold_group_sets[right]:
                    raise AssertionError("Spatial group leaked across validation folds.")

        results = {}
        matrices = {}
        for name, features in GROUPS.items():
            matrix = np.array([
                [value_map[sample.id][feature] for feature in features]
                for sample in cohort
            ], dtype=float)
            matrices[name] = matrix
            results[name] = self._evaluate(
                name,
                features,
                matrix,
                labels,
                groups,
                splits,
                nonlinear=name == "model_f_nonlinear_environment",
            )

        environmental_matrix = matrices["model_d_environment_combined"]
        correlation = np.corrcoef(environmental_matrix, rowvar=False)
        correlations = sorted(
            (
                {
                    "feature_a": GROUPS["model_d_environment_combined"][left],
                    "feature_b": GROUPS["model_d_environment_combined"][right],
                    "correlation": float(correlation[left, right]),
                }
                for left in range(correlation.shape[0])
                for right in range(left + 1, correlation.shape[1])
            ),
            key=lambda item: abs(item["correlation"]),
            reverse=True,
        )
        selected_name, selection = self._select_candidate(results)
        selected_features = GROUPS[selected_name]
        selected_matrix = matrices[selected_name]
        nonlinear = selected_name == "model_f_nonlinear_environment"
        final_model = self._nonlinear() if nonlinear else self._logistic()
        fit_kwargs = {}
        if nonlinear:
            fit_kwargs["sample_weight"] = compute_sample_weight(
                class_weight="balanced", y=labels
            )
        final_model.fit(selected_matrix, labels, **fit_kwargs)
        ARTIFACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        artifact_path = ARTIFACT_DIRECTORY / f"{MODEL_VERSION}.joblib"
        if artifact_path.exists():
            raise FileExistsError(f"Model artifact already exists: {artifact_path}")
        joblib.dump(final_model, artifact_path)
        validation = {
            "feature_version": FEATURE_VERSION,
            "complete_case_exclusions": {
                "woa_missing_background": 51,
                "additional_physical_feature_missing_background": 1,
                "retained_presence": counts["PRESENCE"],
                "retained_background": counts["BACKGROUND"],
            },
            "spatial_validation": {
                "method": "StratifiedGroupKFold",
                "block_size_degrees": 2.0,
                "spatial_group_count": len(group_map),
                "fold_count": 5,
            },
            "models": results,
            "strongest_absolute_correlations": correlations[:20],
            "selection": {"selected_model": selected_name, **selection},
        }
        record = HabitatSuitabilityModel(
            model_version=MODEL_VERSION,
            scientific_name="Pterois volitans",
            algorithm=(
                "HistGradientBoostingClassifier" if nonlinear else "LogisticRegression"
            ),
            feature_list_json=json.dumps(selected_features),
            training_generation_version=GENERATION_VERSION,
            training_sample_count=len(cohort),
            eligible_presence_count=counts["PRESENCE"],
            eligible_background_count=counts["BACKGROUND"],
            spatial_block_count=len(group_map),
            validation_metrics_json=json.dumps(validation),
            coefficients_json=json.dumps(
                results[selected_name].get("standardized_coefficients", {})
            ),
            artifact_path=str(artifact_path),
        )
        db.add(record)
        try:
            db.commit()
        except Exception:
            db.rollback()
            artifact_path.unlink(missing_ok=True)
            raise
        return {
            "model_version": MODEL_VERSION,
            "dataset_generation_version": GENERATION_VERSION,
            "feature_version": FEATURE_VERSION,
            "training_sample_count": len(cohort),
            "presence": counts["PRESENCE"],
            "background": counts["BACKGROUND"],
            "spatial_groups": len(group_map),
            "results": results,
            "strongest_absolute_correlations": correlations[:20],
            "selection": validation["selection"],
            "selected_algorithm": record.algorithm,
            "selected_features": selected_features,
            "artifact_path": str(artifact_path),
            "artifact_sha256": self._sha256(artifact_path),
            "jamaica_grid_generated": False,
        }
