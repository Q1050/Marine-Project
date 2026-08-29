"""Phase 11B-6 conservative synthesis gate.

This service returns an immutable synthesis result from persisted descriptive
evidence. It deliberately cannot produce an ecological classification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from anomaly_domain import AssessmentStatus, ReviewType, SignalType
from anomaly_evidence_readiness import EvidenceReadinessResolver, IdentitySource
from anomaly_repository import AnomalyRepository, canonical_json
from models import AnomalySignal, Observation


SYNTHESIS_RULES_VERSION = "conservative-synthesis-v1"

DESCRIPTIVE_SIGNAL_TYPES = (
    SignalType.IDENTIFICATION_CONTEXT.value,
    SignalType.DUPLICATE_CONTEXT.value,
    SignalType.HABITAT_SUITABILITY_CONTEXT.value,
    SignalType.HISTORICAL_OCCURRENCE_CONTEXT.value,
)

AUTHORIZED_STATUSES = frozenset({
    AssessmentStatus.NOT_CONFIGURED.value,
    AssessmentStatus.NOT_EVALUATED.value,
    AssessmentStatus.INSUFFICIENT_EVIDENCE.value,
    AssessmentStatus.REQUIRES_IDENTIFICATION_REVIEW.value,
})


@dataclass(frozen=True)
class SynthesisResult:
    assessment_id: int
    observation_id: int
    overall_status: str
    overall_classification: None
    requires_review: bool
    review_type: str
    assessment_confidence: str
    dependency_fingerprint: str
    synthesis_rules_version: str
    synthesis_fingerprint: str
    provenance_json: str
    limitations_json: str

    def as_dict(self) -> dict:
        return asdict(self)


class AnomalySynthesisService:
    """Apply only non-ecological readiness gates to current signal snapshots."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = AnomalyRepository(session)
        self.readiness_resolver = EvidenceReadinessResolver(session)

    def synthesize_observation(self, observation_id: int) -> SynthesisResult:
        observation = self.session.get(Observation, observation_id)
        if observation is None:
            raise LookupError(f"Observation {observation_id} was not found")
        if observation.jurisdiction_id is None:
            raise ValueError("Explicit observation jurisdiction is required for synthesis")

        assessment = self.repository.get_current_assessment(observation_id)
        if assessment is None:
            raise ValueError("A CURRENT AnomalyAssessment is required for synthesis")
        readiness = self.readiness_resolver.resolve(observation)
        if assessment.dependency_fingerprint != readiness.dependency_fingerprint:
            raise ValueError("Assessment dependencies are stale; refresh the assessment")

        signals = self._load_and_validate_signals(assessment)
        evidence = {
            signal_type: json.loads(signals[signal_type].evidence_summary_json)["evidence"]
            for signal_type in DESCRIPTIVE_SIGNAL_TYPES
        }
        identification = evidence[SignalType.IDENTIFICATION_CONTEXT.value]
        duplicate = evidence[SignalType.DUPLICATE_CONTEXT.value]

        if (
            readiness.identity_source is IdentitySource.UNRESOLVED
            or not assessment.evaluated_species
        ):
            status = AssessmentStatus.REQUIRES_IDENTIFICATION_REVIEW.value
            requires_review = True
            review_type = ReviewType.IDENTIFICATION_REVIEW.value
            outcome_reason = "Ecological synthesis is unavailable because species identity is unresolved."
        elif not duplicate["contributes_independent_evidence"]:
            status = AssessmentStatus.NOT_EVALUATED.value
            requires_review = False
            review_type = ReviewType.NO_REVIEW.value
            outcome_reason = "Duplicate evidence is not evaluated as an independent ecological observation."
        elif assessment.species_program_id is None:
            status = AssessmentStatus.NOT_CONFIGURED.value
            requires_review = False
            review_type = ReviewType.NO_REVIEW.value
            outcome_reason = "No jurisdiction-owned scientific species configuration is available."
        else:
            status = AssessmentStatus.INSUFFICIENT_EVIDENCE.value
            requires_review = False
            review_type = ReviewType.NO_REVIEW.value
            outcome_reason = "Only descriptive evidence is available; ecological classification is not scientifically authorized."

        if status not in AUTHORIZED_STATUSES:
            raise AssertionError(f"Unauthorized synthesis status: {status}")

        dataset_ids = sorted({
            dataset_id
            for signal in signals.values()
            for dataset_id in (json.loads(signal.source_dataset_ids_json or "[]"))
        })
        deployment_ids = sorted({
            signal.suitability_deployment_id
            for signal in signals.values()
            if signal.suitability_deployment_id is not None
        })
        consumed = [
            {"id": signals[signal_type].id, "type": signal_type}
            for signal_type in DESCRIPTIVE_SIGNAL_TYPES
        ]
        limitations = [
            outcome_reason,
            "Habitat suitability bands are descriptive only.",
            "Historical occurrence records do not establish absence, rarity, novelty, or range.",
            "AI identification confidence is not ecological anomaly strength.",
            "No positive or negative ecological classification is authorized by these rules.",
        ]
        provenance = {
            "synthesis_rules_version": SYNTHESIS_RULES_VERSION,
            "assessment_id": assessment.id,
            "dependency_fingerprint": assessment.dependency_fingerprint,
            "observation_id": observation.id,
            "jurisdiction_id": observation.jurisdiction_id,
            "evaluated_species": assessment.evaluated_species,
            "identity_source": identification["identity_source"],
            "duplicate_state": duplicate["duplicate_state"],
            "consumed_signals": consumed,
            "scientific_dataset_ids": dataset_ids,
            "suitability_deployment_ids": deployment_ids,
            "classification_available": False,
            "classification_unavailable_reason": outcome_reason,
            "limitations": limitations,
        }
        provenance_json = canonical_json(provenance)
        synthesis_fingerprint = hashlib.sha256(
            provenance_json.encode("utf-8")
        ).hexdigest()
        return SynthesisResult(
            assessment_id=assessment.id,
            observation_id=observation.id,
            overall_status=status,
            overall_classification=None,
            requires_review=requires_review,
            review_type=review_type,
            assessment_confidence=assessment.assessment_confidence,
            dependency_fingerprint=assessment.dependency_fingerprint,
            synthesis_rules_version=SYNTHESIS_RULES_VERSION,
            synthesis_fingerprint=synthesis_fingerprint,
            provenance_json=provenance_json,
            limitations_json=canonical_json(limitations),
        )

    def synthesize_and_persist(self, observation_id: int):
        """Persist a valid conservative result; refused synthesis is not stored."""
        result = self.synthesize_observation(observation_id)
        # Local import keeps computation and persistence modules independently
        # importable while retaining one authoritative outcome allowlist.
        from anomaly_synthesis_repository import AnomalySynthesisRepository

        snapshot = AnomalySynthesisRepository(self.session).create_or_get_snapshot(result)
        if snapshot.synthesis_fingerprint != result.synthesis_fingerprint:
            raise ValueError("Persisted synthesis fingerprint verification failed")
        return snapshot

    def _load_and_validate_signals(self, assessment) -> dict[str, AnomalySignal]:
        rows = self.session.query(AnomalySignal).filter(
            AnomalySignal.anomaly_assessment_id == assessment.id,
            AnomalySignal.signal_type.in_(DESCRIPTIVE_SIGNAL_TYPES),
        ).all()
        signals = {row.signal_type: row for row in rows}
        missing = sorted(set(DESCRIPTIVE_SIGNAL_TYPES) - set(signals))
        if missing:
            raise ValueError("Required descriptive signals are missing: " + ", ".join(missing))
        for signal_type in DESCRIPTIVE_SIGNAL_TYPES:
            summary = json.loads(signals[signal_type].evidence_summary_json)
            provenance = summary.get("provenance", {})
            if provenance.get("dependency_fingerprint") != assessment.dependency_fingerprint:
                raise ValueError(f"Signal dependency fingerprint mismatch: {signal_type}")
            if provenance.get("observation_id") != assessment.observation_id:
                raise ValueError(f"Signal observation mismatch: {signal_type}")
        return signals


__all__ = [
    "AnomalySynthesisService", "SynthesisResult", "SYNTHESIS_RULES_VERSION",
    "AUTHORIZED_STATUSES", "DESCRIPTIVE_SIGNAL_TYPES",
]
