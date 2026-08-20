import json

from database import SessionLocal
from init_db import initialize_database
from next_area_prediction_service import NextAreaPredictionService


def main():
    initialize_database()
    db = SessionLocal()
    try:
        result = NextAreaPredictionService().generate(db)
        print(json.dumps(result, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
