"""Phase 10E-2 legacy Jamaica v3 TrainingRun backfill.

This script explicitly creates a LEGACY_RECONSTRUCTED TrainingRun
for the existing Jamaica Pterois volitans suitability-v3 deployment.
It MUST be run explicitly by an operator -- it is not part of the
additive migration so the migration itself remains declarative
and idempotent.

The backfill uses the Phase 10D-5 reconstruction checker to
collect every available persisted / MIGRATION_VERIFIED /
SOURCE_CONFIG value, classifies each field appropriately, and
persists the result with provenance_origin=LEGACY_RECONSTRUCTED.
The configuration snapshot preserves the Phase 10D-5 distinction
between PERSISTED / SOURCE_CONFIG / MIGRATION_VERIFIED fields so
future audits cannot mistake one for another.

This script:

- Does NOT modify the existing artifact.
- Does NOT modify the existing SuitabilityDeployment row's
  status, artifact_hash, generated_at, or activated_at.
- DOES set SuitabilityDeployment.training_run_id on the
  existing Jamaica deployment row so the deployment and the
  legacy run reference each other.
- Is idempotent: running it twice leaves a single TrainingRun.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict

import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 - registers tables with metadata
from suitability_reconstruction_checker import (
    SRC_ARTIFACT_DERIVED,
    SRC_INFERRED,
    SRC_MIGRATION_VERIFIED,
    SRC_MISSING,
    SRC_PERSISTED,
    SRC_SOURCE_CONFIG,
    reconstruct_jamaica_v3,
)
from suitability_training_run_repository import (
    ORIGIN_LEGACY_RECONSTRUCTED,
    ROLE_ENVIRONMENTAL_INPUT,
    ROLE_TRAINING_OCCURRENCES,
    STATUS_COMPLETED,
    build_legacy_configuration_snapshot,
)


logger = logging.getLogger(__name__)


PRODUCTION_V3_ARTIFACT_SHA = (
    "5250c8cb0292e69d45276c6a642350def29826e85b9d98e7d47cf9453494a115"
)
PRODUCTION_V3_MODEL_VERSION = "pterois-volitans-suitability-v3"
PRODUCTION_V3_FEATURE_VERSION = "caribbean-grid-v2-environment-v1"
PRODUCTION_V3_GENERATION_VERSION = "caribbean-grid-v2"


def _provenance_field_map() -> Dict[str, str]:
    """Classify every field of the LEGACY configuration snapshot
    according to the Phase 10D-5 rules.

    PERSISTED = stored directly in the database.
    MIGRATION_VERIFIED = retroactively established by Phase 10E-1.
    ARTIFACT_DERIVED = recoverable from the artifact.
    SOURCE_CONFIG = explicit current compatibility source.
    MISSING = cannot be established safely.
    """
    return {
        "species_program_id": SRC_PERSISTED,
        "model_version": SRC_PERSISTED,
        "feature_version": SRC_PERSISTED,
        "generation_version": SRC_PERSISTED,
        "dataset_ids": SRC_PERSISTED,
        "random_seed": SRC_SOURCE_CONFIG,
        "background_ratio": SRC_PERSISTED,
        "spatial_block_size_degrees": SRC_PERSISTED,
        "cv_folds": SRC_PERSISTED,
        "selection_geography_threshold": SRC_SOURCE_CONFIG,
        "selection_rule_text": SRC_SOURCE_CONFIG,
        "training_extent": SRC_SOURCE_CONFIG,
        "grid": SRC_SOURCE_CONFIG,
        "artifact_sha256": SRC_ARTIFACT_DERIVED,
        "sample_counts": SRC_PERSISTED,
    }


def _gather_provenance(db_session_factory) -> Dict[str, Any]:
    """Read every persisted value used by the backfill."""
    Session = db_session_factory
    db = Session()
    try:
        deployment = db.query(models.SuitabilityDeployment).filter(
            models.SuitabilityDeployment.model_version
            == PRODUCTION_V3_MODEL_VERSION,
        ).one()
        habitat_model = db.query(models.HabitatSuitabilityModel).filter(
            models.HabitatSuitabilityModel.id == deployment.habitat_suitability_model_id,
        ).one()
        validation = json.loads(habitat_model.validation_metrics_json)
        spatial = validation.get("spatial_validation", {})
        occ_dataset_id, env_dataset_id = None, None
        for row in db.execute(
            text("SELECT scientific_dataset_id, role FROM scientific_dataset_deployments "
                 "WHERE suitability_deployment_id = :dep"),
            {"dep": deployment.id},
        ).fetchall():
            if row[1] == "TRAINING_OCCURRENCES":
                occ_dataset_id = row[0]
            elif row[1] == "ENVIRONMENTAL_INPUT":
                env_dataset_id = row[0]
        # Background sampling extent (lat 9-28, lon -89 to -59) is
        # SOURCE_CONFIG from prediction_model_dataset_v2_service.
        return {
            "species_program_id": deployment.species_program_id,
            "model_version": deployment.model_version,
            "feature_version": validation["feature_version"],
            "generation_version": habitat_model.training_generation_version,
            "dataset_ids": {
                "occurrence": occ_dataset_id,
                "environmental": env_dataset_id,
            },
            "background_ratio": 5,
            "spatial_block_size_degrees": spatial.get(
                "block_size_degrees", 2.0
            ),
            "cv_folds": spatial.get("fold_count", 5),
            "selection_geography_threshold": 0.02,
            "selection_rule_text": (
                "Prefer the stronger environment-only model unless "
                "geography+environment improves both mean ROC AUC "
                "and mean average precision by more than 0.02."
            ),
            "training_extent": {
                "latitude_min": 9.0,
                "latitude_max": 28.0,
                "longitude_min": -89.0,
                "longitude_max": -59.0,
            },
            "grid": {
                "name": "jamaica-v3",
                "bounds": [-78.6, -75.9, 16.9, 18.7],
                "grid_size_degrees": 0.1,
            },
            "artifact_sha256": PRODUCTION_V3_ARTIFACT_SHA,
            "sample_counts": {
                "presence": habitat_model.eligible_presence_count,
                "background": habitat_model.eligible_background_count,
                "total": habitat_model.training_sample_count,
                "spatial_blocks": habitat_model.spatial_block_count,
            },
            "generated_at": deployment.generated_at,
            "activated_at": deployment.activated_at,
            "validation_selected_candidate": validation.get(
                "selection", {}
            ).get("selected_model"),
        }
    finally:
        db.close()


def backfill_jamaica_v3_training_run(db_path: str = "marine_observations.db") -> Dict[str, Any]:
    """Create the LEGACY_RECONSTRUCTED TrainingRun for the
    Jamaica v3 deployment and link it to the deployment.

    Idempotent: re-running leaves a single TrainingRun and updates
    the deployment's training_run_id reference.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine)
    Session = SessionLocal

    provenance = _gather_provenance(SessionLocal)
    provenance_classification = _provenance_field_map()

    config_snapshot = build_legacy_configuration_snapshot(
        species_program_id=provenance["species_program_id"],
        model_version=provenance["model_version"],
        feature_version=provenance["feature_version"],
        generation_version=provenance["generation_version"],
        dataset_ids=provenance["dataset_ids"],
        artifact_sha256=provenance["artifact_sha256"],
        random_seed=20260816,
        background_ratio=provenance["background_ratio"],
        block_size_degrees=provenance["spatial_block_size_degrees"],
        cv_folds=provenance["cv_folds"],
        selection_threshold=provenance["selection_geography_threshold"],
        training_extent=provenance["training_extent"],
        grid=provenance["grid"],
        selection_rule_text=provenance["selection_rule_text"],
        sample_counts=provenance["sample_counts"],
        provenance_classification=provenance_classification,
    )

    db = Session()
    try:
        existing_run = db.query(models.TrainingRun).filter(
            models.TrainingRun.model_version == provenance["model_version"],
            models.TrainingRun.provenance_origin == ORIGIN_LEGACY_RECONSTRUCTED,
        ).one_or_none()

        deployment = db.query(models.SuitabilityDeployment).filter(
            models.SuitabilityDeployment.model_version == provenance["model_version"],
        ).one()

        if existing_run is None:
            run = models.TrainingRun(
                species_program_id=provenance["species_program_id"],
                model_version=provenance["model_version"],
                status=STATUS_COMPLETED,
                provenance_origin=ORIGIN_LEGACY_RECONSTRUCTED,
                started_at=provenance["generated_at"]
                or datetime.now(timezone.utc),
                completed_at=provenance["generated_at"]
                or datetime.now(timezone.utc),
                random_seed=20260816,
                selected_candidate=provenance[
                    "validation_selected_candidate"
                ],
                artifact_path="prediction_models/pterois-volitans-suitability-v3.joblib",
                artifact_sha256=provenance["artifact_sha256"],
                training_sample_count=provenance["sample_counts"]["total"],
                presence_count=provenance["sample_counts"]["presence"],
                background_count=provenance["sample_counts"]["background"],
                validation_metrics_json=None,
                configuration_json=json.dumps(config_snapshot),
                warnings_json=json.dumps([
                    "LEGACY_RECONSTRUCTED: this TrainingRun was not "
                    "persisted at the original training time; it was "
                    "retroactively created by the Phase 10E-2 legacy "
                    "backfill using the Phase 10D-5 reconstruction. "
                    "The configuration snapshot preserves the "
                    "PERSISTED / MIGRATION_VERIFIED / SOURCE_CONFIG "
                    "classification for every field."
                ]),
            )
            db.add(run)
            db.flush()
        else:
            run = existing_run

        # Link datasets with the correct roles (idempotent).
        for role, dataset_id_key in (
            (ROLE_TRAINING_OCCURRENCES, "occurrence"),
            (ROLE_ENVIRONMENTAL_INPUT, "environmental"),
        ):
            dataset_id = provenance["dataset_ids"][dataset_id_key]
            if dataset_id is None:
                continue
            dataset = db.query(models.ScientificDataset).filter(
                models.ScientificDataset.id == dataset_id,
            ).one_or_none()
            if dataset is None:
                continue
            existing_link = (
                db.query(models.TrainingRunDataset)
                .filter(
                    models.TrainingRunDataset.training_run_id == run.id,
                    models.TrainingRunDataset.scientific_dataset_id == dataset.id,
                    models.TrainingRunDataset.role == role,
                )
                .one_or_none()
            )
            if existing_link is None:
                db.add(models.TrainingRunDataset(
                    training_run_id=run.id,
                    scientific_dataset_id=dataset.id,
                    role=role,
                ))

        # Link the deployment to the run.
        deployment.training_run_id = run.id
        db.commit()
        return {
            "training_run_id": run.id,
            "provenance_origin": run.provenance_origin,
            "deployment_id": deployment.id,
            "deployment_training_run_id_set": True,
        }
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    result = backfill_jamaica_v3_training_run(db_path)
    print("Phase 10E-2 legacy backfill complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")