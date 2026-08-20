from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from database import SessionLocal
from models import (
    HabitatSuitabilityV3GridCell,
    NextAreaPredictionCell,
    NextAreaSnapshotCell,
    Observation,
)
from next_area_prediction_service import NextAreaPredictionService


class NextAreaPredictionScoringTests(unittest.TestCase):

    def setUp(self):
        self.service = NextAreaPredictionService()
        self.cell = SimpleNamespace(latitude=18.0, longitude=-77.0, suitability_score=0.8)

    @staticmethod
    def evidence(identifier=1, latitude=18.0, longitude=-77.0, level="CONFIRMED", evidence_weight=1.0, recency_weight=1.0):
        return {
            "id": identifier,
            "latitude": latitude,
            "longitude": longitude,
            "level": level,
            "evidence_weight": evidence_weight,
            "recency_weight": recency_weight,
            "age_days": 1,
        }

    def test_stronger_verification_increases_evidence(self):
        confirmed = self.service.score_cell(self.cell, [self.evidence()])
        ai = self.service.score_cell(self.cell, [self.evidence(level="AI_SUPPORTED", evidence_weight=0.6)])
        self.assertGreater(confirmed["current_score"], ai["current_score"])

    def test_newer_evidence_outranks_older_evidence(self):
        recent = self.service.score_cell(self.cell, [self.evidence(recency_weight=1.0)])
        old = self.service.score_cell(self.cell, [self.evidence(recency_weight=0.1)])
        self.assertGreater(recent["current_score"], old["current_score"])

    def test_nearer_evidence_outranks_distant_evidence(self):
        near = self.service.score_cell(self.cell, [self.evidence(latitude=18.05)])
        distant = self.service.score_cell(self.cell, [self.evidence(latitude=18.7)])
        self.assertGreater(near["current_score"], distant["current_score"])

    def test_high_suitability_without_evidence_scores_moderate(self):
        result = self.service.score_cell(
            SimpleNamespace(latitude=18.0, longitude=-77.0, suitability_score=0.9),
            [],
        )
        self.assertAlmostEqual(result["priority"], 0.495)
        self.assertEqual(result["band"], "MODERATE")

    def test_duplicate_contribution_does_not_increase_max_signal(self):
        one = self.service.score_cell(self.cell, [self.evidence()])
        repeated = self.service.score_cell(
            self.cell, [self.evidence(), self.evidence(identifier=2)]
        )
        self.assertEqual(one["current_score"], repeated["current_score"])
        self.assertEqual(one["priority"], repeated["priority"])

    def test_scoring_is_deterministic(self):
        evidence = [self.evidence(latitude=18.1, recency_weight=0.8)]
        self.assertEqual(
            self.service.score_cell(self.cell, evidence),
            self.service.score_cell(self.cell, evidence),
        )

    def test_recency_boundaries(self):
        expected = [(7, 1.0), (8, 0.8), (30, 0.8), (31, 0.5), (90, 0.5), (91, 0.25), (365, 0.25), (366, 0.1)]
        for days, weight in expected:
            self.assertEqual(self.service.recency_weight(days), weight)

    def test_generation_excludes_duplicates_and_occupied_cells(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        now = datetime(2026, 8, 16, tzinfo=timezone.utc)
        session.add_all([
            HabitatSuitabilityV3GridCell(
                scientific_name="Pterois volitans",
                model_version="pterois-volitans-suitability-v3",
                grid_cell_id="180:-770",
                latitude=18.05,
                longitude=-76.95,
                grid_size=0.1,
                suitability_score=0.8,
                suitability_band="VERY_HIGH",
                prediction_status="SCORED",
                feature_values_json="{}",
                missing_features_json="[]",
            ),
            HabitatSuitabilityV3GridCell(
                scientific_name="Pterois volitans",
                model_version="pterois-volitans-suitability-v3",
                grid_cell_id="181:-770",
                latitude=18.15,
                longitude=-76.95,
                grid_size=0.1,
                suitability_score=0.8,
                suitability_band="VERY_HIGH",
                prediction_status="SCORED",
                feature_values_json="{}",
                missing_features_json="[]",
            ),
            Observation(
                id=1, image_filename="one.jpg", latitude=18.01, longitude=-76.99,
                identification_status="accepted", species="Pterois volitans",
                ecological_status="INVASIVE", decision="ACCEPT", priority="NORMAL",
                verification_status="CONFIRMED", verified_species="Pterois volitans",
                is_possible_duplicate=False, created_at=now,
            ),
            Observation(
                id=2, image_filename="duplicate.jpg", latitude=18.01, longitude=-76.99,
                identification_status="accepted", species="Pterois volitans",
                ecological_status="INVASIVE", decision="ACCEPT", priority="NORMAL",
                verification_status="CONFIRMED", verified_species="Pterois volitans",
                is_possible_duplicate=True, duplicate_of_observation_id=1, created_at=now,
            ),
        ])
        session.commit()
        result = self.service.generate(
            session, prediction_version="test-next-area-v1", now=now
        )
        diagnostics = result["diagnostics"]
        self.assertEqual(diagnostics["observations_eligible_as_current_evidence"], 1)
        self.assertEqual(diagnostics["duplicates_excluded"], 1)
        self.assertEqual(diagnostics["cells_excluded_as_currently_occupied"], 1)
        self.assertEqual(session.query(NextAreaSnapshotCell).count(), 1)
        first = self.service.recommendations(
            session, prediction_version="test-next-area-v1"
        )
        second = self.service.recommendations(
            session, prediction_version="test-next-area-v1"
        )
        self.assertEqual(first, second)
        session.close()

    def test_explainability_matches_persisted_production_scores_without_writes(self):
        session = SessionLocal()
        before = {
            row.id: row.current_evidence_score
            for row in session.query(NextAreaPredictionCell).all()
        }
        result = self.service.recommendations(session, limit=390)
        after = {
            row.id: row.current_evidence_score
            for row in session.query(NextAreaPredictionCell).all()
        }
        self.assertEqual(before, after)
        for cell in result["cells"]:
            if cell["current_evidence_score"]:
                product = (
                    cell["contributing_verification_weight"]
                    * cell["contributing_recency_weight"]
                    * cell["contributing_distance_weight"]
                )
                self.assertAlmostEqual(product, cell["contributing_evidence_score"])
                self.assertAlmostEqual(cell["current_evidence_score"], product)
            else:
                self.assertIsNone(cell["contributing_observation_id"])
                self.assertEqual(cell["contributing_evidence_score"], 0.0)
        session.close()


if __name__ == "__main__":
    unittest.main()
