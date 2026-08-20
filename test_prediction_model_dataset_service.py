import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import PredictionModelSample, PredictionTrainingOccurrence
from prediction_model_dataset_service import PredictionModelDatasetService


class MarineEnvironment:
    def classify_marine_coordinate(self, latitude, longitude):
        return {
            "classification": "MARINE",
            "depth": 100.0,
            "source": "TEST_BATHYMETRY",
            "error": None,
        }


class PredictionModelDatasetTests(unittest.TestCase):
    def test_generation_thins_presence_and_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        db.add_all([
            PredictionTrainingOccurrence(
                scientific_name="Pterois volitans",
                taxon_id=159559,
                latitude=18.11,
                longitude=-77.11,
                occurrence_id=f"test-{index}",
                source="TEST",
                deduplication_key=f"test-{index}",
            )
            for index in range(3)
        ])
        db.commit()
        service = PredictionModelDatasetService(MarineEnvironment())

        first = service.generate(
            db, background_ratio=1, seed=7, generation_version="test-v1", workers=1
        )
        second = service.generate(
            db, background_ratio=1, seed=7, generation_version="test-v1", workers=1
        )

        self.assertEqual(first["presence_samples"], 1)
        self.assertEqual(first["background_samples"], 1)
        self.assertEqual(first["strongest_original_cell"]["source_occurrences"], 3)
        self.assertEqual(second["new_samples_inserted"], 0)
        self.assertEqual(db.query(PredictionModelSample).count(), 2)


if __name__ == "__main__":
    unittest.main()
