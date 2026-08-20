import argparse
import json

from database import SessionLocal
from init_db import initialize_database
from prediction_model_dataset_v2_service import PredictionModelDatasetV2Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        result = PredictionModelDatasetV2Service().generate(db, workers=args.workers)
        print(json.dumps(result, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
