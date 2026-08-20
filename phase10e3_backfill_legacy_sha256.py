"""Phase 10E-3 legacy SHA-256 backfill for the Jamaica v3
LEGACY_RECONSTRUCTED TrainingRun.

The Phase 10E-3 additive migration added the
``configuration_sha256`` column to ``training_runs``. This script
explicitly computes the SHA-256 of the existing legacy
TrainingRun's configuration snapshot and persists it.

The script is:

- explicit (must be invoked by an operator)
- idempotent (running twice leaves the same hash)
- preserves provenance classification (does NOT change
  ``provenance_origin`` or any other field)

The hash verifies the reconstructed record as stored NOW; it
does not prove this exact configuration JSON existed at the
original training time. The Phase 10E-3 docs are explicit about
this distinction.
"""

from __future__ import annotations

import json
import logging
import sys

import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 - registers tables with metadata
from suitability_training_run_repository import compute_configuration_sha256


logger = logging.getLogger(__name__)


def backfill_legacy_configuration_sha256(db_path: str = "marine_observations.db") -> dict:
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
            snapshot = json.loads(run.configuration_json)
            computed = compute_configuration_sha256(snapshot)
            if run.configuration_sha256 != computed:
                run.configuration_sha256 = computed
                results.append({
                    "id": run.id,
                    "configuration_sha256_set": True,
                })
            else:
                results.append({
                    "id": run.id,
                    "configuration_sha256_unchanged": True,
                })
        db.commit()
        return {"updated_runs": results}
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = sys.argv[1] if len(sys.argv) > 1 else "marine_observations.db"
    result = backfill_legacy_configuration_sha256(db_path)
    print("Phase 10E-3 legacy SHA backfill complete:")
    for entry in result["updated_runs"]:
        print(f"  run {entry}")