import hashlib
import json
from pathlib import Path

from database import SessionLocal
from habitat_suitability_service import HabitatSuitabilityService
from init_db import initialize_database
from models import HabitatSuitabilityModel


MODEL_VERSION = "pterois-volitans-suitability-v2"
GENERATION_VERSION = "caribbean-grid-v2"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    initialize_database()
    db = SessionLocal()
    try:
        summary = HabitatSuitabilityService().train(
            db,
            model_version=MODEL_VERSION,
            training_generation_version=GENERATION_VERSION,
            generate_jamaica_grid=False,
        )
        record = db.query(HabitatSuitabilityModel).filter_by(
            model_version=MODEL_VERSION
        ).one()
        artifact_path = Path(record.artifact_path)
        output = {
            **summary,
            "artifact_sha256": sha256_file(artifact_path),
            "jamaica_grid_generated": False,
        }
        print(json.dumps(output, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
