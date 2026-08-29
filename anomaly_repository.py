"""Persistence and lifecycle operations for immutable anomaly snapshots.

No scientific signal calculation or classification is performed here.
"""

from __future__ import annotations

import enum
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from anomaly_domain import AssessmentLifecycleState
from models import AnomalyAssessment, AnomalySignal


def canonical_json(value) -> str:
    """Serialize evidence/provenance deterministically for reproducible rows."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _value(value):
    return value.value if isinstance(value, enum.Enum) else value


class AnomalyRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_assessment(self, **values) -> AnomalyAssessment:
        observation_id = values["observation_id"]
        existing = self.get_current_assessment(observation_id)
        if existing is not None:
            raise ValueError(f"Observation {observation_id} already has a CURRENT assessment")
        for field in ("overall_status", "overall_classification", "assessment_confidence", "review_type", "current_state"):
            if field in values and values[field] is not None:
                values[field] = _value(values[field])
        values.setdefault("current_state", AssessmentLifecycleState.CURRENT.value)
        values.setdefault("generated_at", datetime.now(timezone.utc))
        for field in ("evidence_summary_json", "limitations_json", "provenance_json"):
            if field in values and not isinstance(values[field], str):
                values[field] = canonical_json(values[field])
        row = AnomalyAssessment(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def create_signal(self, **values) -> AnomalySignal:
        for field in ("signal_type", "status", "evidence_confidence"):
            if field in values:
                values[field] = _value(values[field])
        values.setdefault("generated_at", datetime.now(timezone.utc))
        for field in ("evidence_summary_json", "limitations_json", "source_dataset_ids_json", "supporting_observation_ids_json"):
            if field in values and not isinstance(values[field], str):
                values[field] = canonical_json(values[field])
        row = AnomalySignal(**values)
        self.session.add(row)
        self.session.flush()
        return row

    def get_current_assessment(self, observation_id: int) -> AnomalyAssessment | None:
        return (
            self.session.query(AnomalyAssessment)
            .filter(
                AnomalyAssessment.observation_id == observation_id,
                AnomalyAssessment.current_state == AssessmentLifecycleState.CURRENT.value,
            )
            .one_or_none()
        )

    def mark_assessment_stale(self, assessment: AnomalyAssessment) -> AnomalyAssessment:
        self._transition(assessment, AssessmentLifecycleState.CURRENT, AssessmentLifecycleState.STALE)
        assessment.invalidated_at = datetime.now(timezone.utc)
        self.session.flush()
        return assessment

    def mark_assessment_superseded(self, assessment: AnomalyAssessment) -> AnomalyAssessment:
        self._transition(assessment, AssessmentLifecycleState.STALE, AssessmentLifecycleState.SUPERSEDED)
        assessment.superseded_at = datetime.now(timezone.utc)
        self.session.flush()
        return assessment

    @staticmethod
    def _transition(assessment, expected, target) -> None:
        if assessment.current_state != expected.value:
            raise ValueError(
                f"Invalid anomaly lifecycle transition: {assessment.current_state} -> {target.value}"
            )
        assessment.current_state = target.value


__all__ = ["AnomalyRepository", "canonical_json"]
