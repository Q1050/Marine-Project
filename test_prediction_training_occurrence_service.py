import unittest

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import PredictionTrainingOccurrence
from prediction_training_occurrence_service import (
    PredictionTrainingOccurrenceService,
)


class FakeProvider:
    def resolve_taxon(self, scientific_name):
        return {"id": 159559}

    def get_taxon_id(self, taxon):
        return taxon["id"]

    def query_occurrences(self, taxon_id, geometry, size, offset):
        if offset:
            return 3, []
        return 3, [
            {
                "occurrenceID": "one",
                "scientificName": "Pterois volitans",
                "decimalLatitude": 18.1,
                "decimalLongitude": -77.1,
                "eventDate": "2020-01-02",
            },
            {
                "occurrenceID": "two",
                "scientificName": "Pterois volitans",
                "decimalLatitude": 18.1,
                "decimalLongitude": -77.1,
                "eventDate": "2020-01-02",
            },
            {
                "occurrenceID": "three",
                "scientificName": "Pterois volitans",
                "decimalLatitude": 18.2,
                "decimalLongitude": -77.2,
            },
        ]

    def clean_occurrences(self, records):
        return pd.DataFrame(records)


class PredictionTrainingImportTests(unittest.TestCase):
    def test_coordinate_date_duplicates_and_rerun_are_deduplicated(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        service = PredictionTrainingOccurrenceService(FakeProvider())

        first = service.import_occurrences(db)
        second = service.import_occurrences(db)

        self.assertEqual(first["usable_records"], 2)
        self.assertEqual(first["coordinate_date_duplicates_removed"], 1)
        self.assertEqual(first["new_records_inserted"], 2)
        self.assertEqual(second["new_records_inserted"], 0)
        self.assertEqual(db.query(PredictionTrainingOccurrence).count(), 2)


if __name__ == "__main__":
    unittest.main()
