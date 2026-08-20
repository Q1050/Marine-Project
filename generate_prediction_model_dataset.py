import argparse
import json

from database import SessionLocal
from init_db import initialize_database
from prediction_model_dataset_service import (
    DEFAULT_BACKGROUND_RATIO,
    DEFAULT_SEED,
    GENERATION_VERSION,
    PredictionModelDatasetService,
)
from prediction_training_occurrence_service import DEFAULT_SCIENTIFIC_NAME


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--background-ratio", type=float, default=DEFAULT_BACKGROUND_RATIO)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--generation-version", default=GENERATION_VERSION)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        result = PredictionModelDatasetService().generate(
            db,
            DEFAULT_SCIENTIFIC_NAME,
            background_ratio=args.background_ratio,
            seed=args.seed,
            generation_version=args.generation_version,
            workers=args.workers,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
