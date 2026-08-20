import argparse
import json

from database import SessionLocal
from habitat_suitability_service import HabitatSuitabilityService, MODEL_VERSION
from init_db import initialize_database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        summary = HabitatSuitabilityService().train(
            db,
            model_version=args.model_version,
            workers=args.workers,
        )
        print(json.dumps(summary, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
