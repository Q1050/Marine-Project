"""Phase 11B-4 descriptive signal persistence.

Signals created here describe available evidence. They do not score or classify
ecological anomaly and never alter the parent assessment's scientific result.
"""

from __future__ import annotations

from math import floor

from sqlalchemy import func
from sqlalchemy.orm import Session

from anomaly_domain import EvidenceConfidence, SignalStatus, SignalType
from anomaly_evidence_readiness import EvidenceReadinessResolver, IdentitySource
from anomaly_repository import AnomalyRepository
from models import (
    AnomalyAssessment,
    AnomalySignal,
    HabitatSuitabilityV3GridCell,
    HistoricalOccurrence,
    Observation,
    ScientificDataset,
    ScientificDatasetDeployment,
    SuitabilityDeployment,
)


class AnomalySignalService:
    """Generate immutable, idempotent descriptive signals for a current snapshot."""

    GRID_SIZE = 0.1

    def __init__(self, session: Session):
        self.session = session
        self.repository = AnomalyRepository(session)
        self.readiness_resolver = EvidenceReadinessResolver(session)

    def generate_for_observation(self, observation_id: int) -> list[AnomalySignal]:
        observation = self.session.get(Observation, observation_id)
        if observation is None:
            raise LookupError(f"Observation {observation_id} was not found")
        assessment = self.repository.get_current_assessment(observation_id)
        if assessment is None:
            raise ValueError("A CURRENT AnomalyAssessment is required")
        readiness = self.readiness_resolver.resolve(observation)
        if assessment.dependency_fingerprint != readiness.dependency_fingerprint:
            raise ValueError("CURRENT assessment dependencies are stale; replace it before signals")

        builders = (
            (SignalType.HABITAT_SUITABILITY_CONTEXT, self._habitat_signal),
            (SignalType.HISTORICAL_OCCURRENCE_CONTEXT, self._historical_signal),
            (SignalType.IDENTIFICATION_CONTEXT, self._identification_signal),
            (SignalType.DUPLICATE_CONTEXT, self._duplicate_signal),
        )
        existing = {
            row.signal_type: row
            for row in self.session.query(AnomalySignal).filter(
                AnomalySignal.anomaly_assessment_id == assessment.id
            )
        }
        rows = []
        for signal_type, builder in builders:
            row = existing.get(signal_type.value)
            if row is None:
                row = builder(observation, assessment, readiness)
            rows.append(row)
        return rows

    def _create(self, assessment, signal_type, summary, limitations, dataset_ids=(), deployment_id=None, supporting_ids=()):
        provenance = {
            "observation_id": assessment.observation_id,
            "jurisdiction_id": assessment.jurisdiction_id,
            "evaluated_species": assessment.evaluated_species,
            "dependency_fingerprint": assessment.dependency_fingerprint,
            "provenance_version": assessment.provenance_version,
        }
        return self.repository.create_signal(
            anomaly_assessment_id=assessment.id,
            signal_type=signal_type,
            status=SignalStatus.NOT_EVALUATED,
            anomaly_strength=None,
            evidence_confidence=EvidenceConfidence.NONE,
            evidence_summary_json={"evidence": summary, "provenance": provenance},
            limitations_json=limitations,
            source_dataset_ids_json=sorted(dataset_ids),
            suitability_deployment_id=deployment_id,
            supporting_observation_ids_json=sorted(supporting_ids),
            provenance_version=assessment.provenance_version,
        )

    @classmethod
    def _grid_cell_id(cls, latitude: float, longitude: float) -> str:
        return f"{floor(latitude / cls.GRID_SIZE)}:{floor(longitude / cls.GRID_SIZE)}"

    def _habitat_signal(self, observation, assessment, readiness):
        deployment = None
        cell = None
        if readiness.suitability_deployment_id is not None:
            deployment = self.session.get(
                SuitabilityDeployment, readiness.suitability_deployment_id
            )
        if deployment is not None:
            cell = (
                self.session.query(HabitatSuitabilityV3GridCell)
                .filter(
                    HabitatSuitabilityV3GridCell.suitability_deployment_id == deployment.id,
                    HabitatSuitabilityV3GridCell.scientific_name == assessment.evaluated_species,
                    HabitatSuitabilityV3GridCell.model_version == deployment.model_version,
                    HabitatSuitabilityV3GridCell.grid_cell_id == self._grid_cell_id(
                        observation.latitude, observation.longitude
                    ),
                )
                .one_or_none()
            )
        deployment_dataset_ids = []
        if deployment is not None:
            deployment_dataset_ids = sorted(
                dataset_id for (dataset_id,) in self.session.query(
                    ScientificDatasetDeployment.scientific_dataset_id
                ).filter(
                    ScientificDatasetDeployment.suitability_deployment_id == deployment.id
                ).all()
            )
        available = bool(
            cell is not None
            and cell.prediction_status == "SCORED"
            and cell.suitability_score is not None
            and cell.suitability_band is not None
        )
        summary = {
            "availability": "AVAILABLE" if available else "UNAVAILABLE",
            "grid_cell_id": None if cell is None else cell.grid_cell_id,
            "grid_size": None if cell is None else cell.grid_size,
            "prediction_status": None if cell is None else cell.prediction_status,
            "suitability_score": None if cell is None else cell.suitability_score,
            "suitability_band": None if cell is None else cell.suitability_band,
            "deployment_id": None if deployment is None else deployment.id,
            "model_version": None if deployment is None else deployment.model_version,
            "artifact_hash": None if deployment is None else deployment.artifact_hash,
            "training_generation_version": (
                None if deployment is None or deployment.model is None
                else deployment.model.training_generation_version
            ),
            "feature_list_json": (
                None if deployment is None or deployment.model is None
                else deployment.model.feature_list_json
            ),
        }
        limitations = [
            "Suitability score and band are descriptive model outputs, not anomaly or normality conclusions."
        ]
        if not available:
            limitations.append("No compatible scored suitability cell is available for this observation.")
        return self._create(
            assessment, SignalType.HABITAT_SUITABILITY_CONTEXT, summary,
            limitations, dataset_ids=deployment_dataset_ids,
            deployment_id=None if deployment is None else deployment.id,
        )

    def _historical_signal(self, observation, assessment, readiness):
        dataset_ids = tuple(sorted(
            dataset_id for (dataset_id,) in self.session.query(ScientificDataset.id)
            .filter(
                ScientificDataset.id.in_(readiness.compatible_dataset_ids),
                ScientificDataset.dataset_type.ilike("%OCCURRENCE%"),
            ).all()
        )) if readiness.compatible_dataset_ids else ()
        query = self.session.query(
            func.count(HistoricalOccurrence.id),
            func.min(HistoricalOccurrence.event_date),
            func.max(HistoricalOccurrence.event_date),
        ).filter(HistoricalOccurrence.scientific_name == assessment.evaluated_species)
        if dataset_ids:
            query = query.filter(HistoricalOccurrence.dataset_id.in_(dataset_ids))
            count, earliest, latest = query.one()
        else:
            count, earliest, latest = 0, None, None
        summary = {
            "availability": "AVAILABLE" if dataset_ids else "UNAVAILABLE",
            "record_count": int(count),
            "earliest_record": None if earliest is None else earliest.isoformat(),
            "latest_record": None if latest is None else latest.isoformat(),
            "scientific_dataset_ids": list(dataset_ids),
            "current_observation_representation": "UNKNOWN",
        }
        limitations = [
            "Historical record counts are descriptive and do not establish rarity, absence, novelty, or range expansion.",
            "The current observation cannot be linked to historical occurrence identifiers from existing observation fields.",
        ]
        return self._create(
            assessment, SignalType.HISTORICAL_OCCURRENCE_CONTEXT, summary,
            limitations, dataset_ids=dataset_ids,
        )

    def _identification_signal(self, observation, assessment, readiness):
        summary = {
            "availability": readiness.identification_readiness.value,
            "evaluated_species": assessment.evaluated_species,
            "identity_source": readiness.identity_source.value,
            "expert_verification_state": readiness.expert_verification_status.value,
            "verification_status": observation.verification_status,
            "accepted_ai_identity": (
                observation.species
                if readiness.identity_source is IdentitySource.ACCEPTED_AI
                else None
            ),
            "ai_identification_status": observation.identification_status,
            "ai_score": observation.score,
        }
        return self._create(
            assessment, SignalType.IDENTIFICATION_CONTEXT, summary,
            ["AI identification confidence is descriptive and is not ecological anomaly strength."],
        )

    def _duplicate_signal(self, observation, assessment, readiness):
        supporting = (
            [observation.duplicate_of_observation_id]
            if observation.duplicate_of_observation_id is not None else []
        )
        summary = {
            "duplicate_state": readiness.duplicate_status.value,
            "duplicate_of_observation_id": observation.duplicate_of_observation_id,
            "contributes_independent_evidence": readiness.contributes_independent_evidence,
        }
        return self._create(
            assessment, SignalType.DUPLICATE_CONTEXT, summary,
            ["Existing duplicate semantics determine independent-evidence eligibility."],
            supporting_ids=supporting,
        )


__all__ = ["AnomalySignalService"]
