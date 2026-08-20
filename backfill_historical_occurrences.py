from database import Base, SessionLocal, engine
from historical_occurrence_service import (
    DEFAULT_SCIENTIFIC_NAME,
    HistoricalOccurrenceService,
)
import models  # noqa: F401


def main():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        summary = HistoricalOccurrenceService().backfill(
            db,
            DEFAULT_SCIENTIFIC_NAME,
        )
    finally:
        db.close()

    labels = [
        ("Species", "species"),
        ("OBIS records retrieved", "obis_records_retrieved"),
        ("Clean records", "clean_records"),
        ("New records inserted", "new_records_inserted"),
        ("Duplicates skipped", "duplicates_skipped"),
        ("Records with dates", "records_with_dates"),
        ("Earliest date", "earliest_date"),
        ("Latest date", "latest_date"),
    ]

    for label, key in labels:
        print(f"{label}: {summary[key]}")


if __name__ == "__main__":
    main()
