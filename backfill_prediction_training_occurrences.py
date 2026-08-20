import json

from database import Base, SessionLocal, engine
import models  # noqa: F401 - registers all tables with SQLAlchemy metadata
from prediction_training_occurrence_service import (
    DEFAULT_SCIENTIFIC_NAME,
    PredictionTrainingOccurrenceService,
)


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        summary = PredictionTrainingOccurrenceService().import_occurrences(
            db,
            DEFAULT_SCIENTIFIC_NAME,
        )
        print(json.dumps(summary, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
