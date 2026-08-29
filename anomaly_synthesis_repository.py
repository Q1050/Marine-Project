"""Persistence boundary for immutable conservative synthesis snapshots."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from anomaly_synthesis_service import AUTHORIZED_STATUSES, SynthesisResult
from models import AnomalySynthesisSnapshot


class AnomalySynthesisRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_or_get_snapshot(self, result: SynthesisResult) -> AnomalySynthesisSnapshot:
        self._validate_result(result)
        existing = self.get_snapshot(
            result.assessment_id,
            result.synthesis_rules_version,
            result.synthesis_fingerprint,
        )
        values = self._values(result)
        if existing is not None:
            for field, value in values.items():
                if getattr(existing, field) != value:
                    raise ValueError(f"Existing synthesis snapshot differs at {field}")
            return existing
        snapshot = AnomalySynthesisSnapshot(**values)
        self.session.add(snapshot)
        self.session.flush()
        if snapshot.synthesis_fingerprint != result.synthesis_fingerprint:
            raise ValueError("Persisted synthesis fingerprint differs from computed result")
        return snapshot

    def get_snapshot(self, assessment_id: int, rules_version: str, fingerprint: str):
        return self.session.query(AnomalySynthesisSnapshot).filter(
            AnomalySynthesisSnapshot.anomaly_assessment_id == assessment_id,
            AnomalySynthesisSnapshot.synthesis_rules_version == rules_version,
            AnomalySynthesisSnapshot.synthesis_fingerprint == fingerprint,
        ).one_or_none()

    def list_snapshots_for_assessment(self, assessment_id: int):
        return self.session.query(AnomalySynthesisSnapshot).filter(
            AnomalySynthesisSnapshot.anomaly_assessment_id == assessment_id
        ).order_by(AnomalySynthesisSnapshot.id).all()

    def get_latest_snapshot_for_observation(self, observation_id: int):
        return self.session.query(AnomalySynthesisSnapshot).filter(
            AnomalySynthesisSnapshot.observation_id == observation_id
        ).order_by(AnomalySynthesisSnapshot.id.desc()).first()

    @staticmethod
    def _validate_result(result: SynthesisResult) -> None:
        if result.overall_status not in AUTHORIZED_STATUSES:
            raise ValueError(f"Unauthorized synthesis outcome: {result.overall_status}")
        if result.overall_classification is not None:
            raise ValueError("Conservative synthesis classification must remain NULL")
        calculated = hashlib.sha256(result.provenance_json.encode("utf-8")).hexdigest()
        if calculated != result.synthesis_fingerprint:
            raise ValueError("Synthesis provenance does not match its SHA-256 fingerprint")

    @staticmethod
    def _values(result: SynthesisResult) -> dict:
        provenance = json.loads(result.provenance_json)
        return {
            "anomaly_assessment_id": result.assessment_id,
            "observation_id": result.observation_id,
            "jurisdiction_id": provenance["jurisdiction_id"],
            "synthesis_rules_version": result.synthesis_rules_version,
            "dependency_fingerprint": result.dependency_fingerprint,
            "synthesis_fingerprint": result.synthesis_fingerprint,
            "overall_status": result.overall_status,
            "overall_classification": result.overall_classification,
            "requires_review": result.requires_review,
            "review_type": result.review_type,
            "assessment_confidence": result.assessment_confidence,
            "provenance_json": result.provenance_json,
            "limitations_json": result.limitations_json,
        }


__all__ = ["AnomalySynthesisRepository"]
