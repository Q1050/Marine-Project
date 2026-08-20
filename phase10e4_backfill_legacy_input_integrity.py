"""Phase 10E-4 legacy Jamaica input-integrity state backfill.

The legacy LEGACY_RECONSTRUCTED Jamaica v3 TrainingRun has NULL
dataset artifact_sha256 on both production ScientificDataset rows
(id=1 occurrence, id=2 environmental). Phase 10E-4's
``compute_training_input_sha256`` still produces a deterministic
hash over the available fields; ``input_integrity_status`` is set
to ``PARTIAL`` because at least one linked dataset lacks a
controlled artifact.

This script:

- computes the deterministic hash and stores it
- sets ``input_integrity_status='PARTIAL'``
- documents the limitation honestly: the hash is computed over
  the legacy reconstructed snapshot's known fields; it does not
  prove historical provenance.

The script is idempotent.
"""

from __future__ import annotations

import logging
import sys

import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 - registers tables with metadata
from suitability_dataset_artifact_repository import (
    compute_training_input_sha256,
)


logger = logging.getLogger(__name__)


def backfill_legacy_training_input_sha256(
    db_path: str = "marine_observations.db",
) -> dict:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        legacy_runs = (
            db.query(models.TrainingRun)
            .filter(models.TrainingRun.provenance_origin == "LEGACY_RECONSTRUCTED")
            .all()
        )
        results = []
        for run in legacy_runs:
            sha, integrity = compute_training_input_sha256(db, run)
            run.training_input_sha256 = sha
            run.input_integrity_status = integrity
            results.append({
                "id": run.id,
                "training_input_sha256": sha,
                "input_integrity_status": integrity,
            })
        db.commit()
        return {"legacy_runs": results}
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    result = backfill_legacy_training_input_sha256(db_path)
    print("Phase 10E-4 legacy input-integrity backfill complete:")
    for entry in result["legacy_runs"]:
        print(f"  run {entry}")