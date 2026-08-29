"""Phase 11B-3 orchestration for evidence-readiness assessment snapshots.

The service persists what evidence was available. It does not calculate or
classify ecological anomaly signals.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from anomaly_domain import (
    ANOMALY_PROVENANCE_VERSION,
    AssessmentStatus,
    IdentificationConfidence,
    ReviewType,
)
from anomaly_evidence_readiness import (
    AvailabilityState,
    EvidenceReadiness,
    EvidenceReadinessResolver,
    IdentitySource,
)
from anomaly_repository import AnomalyRepository
from models import Observation, ScientificDataset, SpeciesProgram, SuitabilityDeployment


class AnomalyAssessmentService:
    """Create or reuse immutable readiness snapshots for observations."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = AnomalyRepository(session)
        self.readiness_resolver = EvidenceReadinessResolver(session)

    def assess_observation(self, observation_id: int):
        observation = self.session.get(Observation, observation_id)
        if observation is None:
            raise LookupError(f"Observation {observation_id} was not found")

        readiness = self.readiness_resolver.resolve(observation)
        current = self.repository.get_current_assessment(observation.id)
        if current is not None and current.dependency_fingerprint == readiness.dependency_fingerprint:
            return current

        previous = current
        if previous is not None:
            self.repository.mark_assessment_stale(previous)

        # A savepoint isolates replacement insertion. If insertion fails, the
        # prior snapshot remains STALE in the caller's unit of work and is not
        # falsely marked SUPERSEDED.
        with self.session.begin_nested():
            replacement = self._persist_snapshot(observation, readiness)

        if previous is not None:
            self.repository.mark_assessment_superseded(previous)
        return replacement

    def _persist_snapshot(self, observation: Observation, readiness: EvidenceReadiness):
        species_program_id = self._species_program_id(observation, readiness)
        status, requires_review, review_type = self._safe_outcome(
            readiness, species_program_id
        )
        provenance = self._provenance(readiness)
        evidence_summary = {
            key: value
            for key, value in readiness.as_dict().items()
            if key not in {"limitations", "dependency_fingerprint"}
        }
        return self.repository.create_assessment(
            observation_id=observation.id,
            jurisdiction_id=observation.jurisdiction_id,
            species_program_id=species_program_id,
            evaluated_species=readiness.resolved_species,
            evaluated_species_source=readiness.identity_source.value,
            overall_status=status,
            overall_classification=None,
            assessment_confidence=(
                IdentificationConfidence.VERIFIED
                if readiness.identity_source is IdentitySource.EXPERT_VERIFIED
                else IdentificationConfidence.NONE
            ),
            requires_review=requires_review,
            review_type=review_type,
            provenance_version=ANOMALY_PROVENANCE_VERSION,
            dependency_fingerprint=readiness.dependency_fingerprint,
            evidence_summary_json=evidence_summary,
            limitations_json=list(readiness.limitations),
            provenance_json=provenance,
        )

    @staticmethod
    def _safe_outcome(readiness: EvidenceReadiness, species_program_id: int | None):
        if readiness.identification_readiness is AvailabilityState.UNAVAILABLE:
            return AssessmentStatus.REQUIRES_IDENTIFICATION_REVIEW, True, ReviewType.IDENTIFICATION_REVIEW
        if readiness.is_duplicate:
            return AssessmentStatus.NOT_EVALUATED, False, ReviewType.NO_REVIEW
        # A jurisdiction-owned species program is the existing application's
        # explicit scientific-configuration boundary. Region data alone does
        # not silently configure a jurisdiction such as Bahamas.
        if species_program_id is None:
            return AssessmentStatus.NOT_CONFIGURED, False, ReviewType.NO_REVIEW
        complete = all(
            state is AvailabilityState.AVAILABLE
            for state in (
                readiness.occurrence_history_availability,
                readiness.suitability_model_availability,
                readiness.jurisdiction_compatibility,
                readiness.dataset_provenance_availability,
            )
        )
        if not complete:
            return AssessmentStatus.INSUFFICIENT_EVIDENCE, False, ReviewType.NO_REVIEW
        # Configuration is ready, but ecological evaluation is not authorized
        # in Phase 11B-3.
        return AssessmentStatus.NOT_EVALUATED, False, ReviewType.NO_REVIEW

    def _species_program_id(self, observation, readiness):
        if readiness.resolved_species is None or observation.jurisdiction_id is None:
            return None
        program = (
            self.session.query(SpeciesProgram)
            .filter(
                SpeciesProgram.jurisdiction_id == observation.jurisdiction_id,
                SpeciesProgram.scientific_name == readiness.resolved_species,
            )
            .one_or_none()
        )
        return None if program is None else program.id

    def _provenance(self, readiness: EvidenceReadiness) -> dict:
        datasets = []
        if readiness.compatible_dataset_ids:
            rows = (
                self.session.query(ScientificDataset)
                .filter(ScientificDataset.id.in_(readiness.compatible_dataset_ids))
                .order_by(ScientificDataset.id)
                .all()
            )
            datasets = [
                {
                    "id": row.id,
                    "slug": row.slug,
                    "source_name": row.source_name,
                    "source_version": row.source_version,
                    "artifact_sha256": row.artifact_sha256,
                    "geographic_scope_type": row.geographic_scope_type,
                    "region_id": row.region_id,
                    "jurisdiction_id": row.jurisdiction_id,
                }
                for row in rows
            ]
        deployment = None
        if readiness.suitability_deployment_id is not None:
            row = self.session.get(SuitabilityDeployment, readiness.suitability_deployment_id)
            if row is not None:
                deployment = {
                    "id": row.id,
                    "species_program_id": row.species_program_id,
                    "model_version": row.model_version,
                    "artifact_hash": row.artifact_hash,
                }
        return {
            "anomaly_provenance_version": ANOMALY_PROVENANCE_VERSION,
            "dependency_fingerprint": readiness.dependency_fingerprint,
            "identity_source": readiness.identity_source.value,
            "jurisdiction_id": readiness.jurisdiction_id,
            "duplicate_status": readiness.duplicate_status.value,
            "availability": {
                "identification": readiness.identification_readiness.value,
                "occurrence_history": readiness.occurrence_history_availability.value,
                "suitability_model": readiness.suitability_model_availability.value,
                "jurisdiction_compatibility": readiness.jurisdiction_compatibility.value,
                "dataset_provenance": readiness.dataset_provenance_availability.value,
            },
            "scientific_datasets": datasets,
            "suitability_deployment": deployment,
        }


__all__ = ["AnomalyAssessmentService"]
