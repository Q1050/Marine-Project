"""Repository and compatibility rules for scientific dataset applicability."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import ScientificDataset, ScientificDatasetApplicability
from scientific_applicability_domain import ApplicabilityStatus, EvidenceRole


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def provenance_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def authorized_applicability(
    session: Session, dataset_id: int, jurisdiction_id: int, evidence_role: EvidenceRole | str,
) -> ScientificDatasetApplicability | None:
    role = evidence_role.value if isinstance(evidence_role, EvidenceRole) else str(evidence_role)
    rows = session.query(ScientificDatasetApplicability).filter(
        ScientificDatasetApplicability.scientific_dataset_id == dataset_id,
        ScientificDatasetApplicability.jurisdiction_id == jurisdiction_id,
        ScientificDatasetApplicability.evidence_role == role,
        ScientificDatasetApplicability.applicability_status == ApplicabilityStatus.AUTHORIZED.value,
    ).order_by(ScientificDatasetApplicability.id).all()
    if len(rows) > 1:
        raise ValueError("Multiple active applicability assertions exist for dataset/jurisdiction/role")
    return rows[0] if rows else None


def dataset_is_jurisdiction_compatible(
    session: Session,
    dataset: ScientificDataset,
    jurisdiction,
    evidence_role: EvidenceRole | str,
) -> bool:
    """Fail closed except for exact jurisdiction ownership or explicit authorization."""
    if jurisdiction is None:
        return False
    scope = (dataset.geographic_scope_type or "").upper()
    if scope == "JURISDICTION":
        return dataset.jurisdiction_id == jurisdiction.id
    if scope == "REGION":
        if dataset.region_id is None or dataset.region_id != jurisdiction.region_id:
            return False
        return authorized_applicability(
            session, dataset.id, jurisdiction.id, evidence_role
        ) is not None
    if scope == "GLOBAL":
        return authorized_applicability(
            session, dataset.id, jurisdiction.id, evidence_role
        ) is not None
    return False


def create_applicability(
    session: Session,
    *,
    scientific_dataset_id: int,
    jurisdiction_id: int,
    evidence_role: EvidenceRole | str,
    applicability_status: ApplicabilityStatus | str,
    reconciliation_method: str,
    reconciliation_version: str,
    provenance_reference: str,
    provenance: dict,
    jurisdiction_boundary_id: int | None = None,
    reviewed_by: str | None = None,
    reviewed_at=None,
    approved_by: str | None = None,
    approved_at=None,
) -> ScientificDatasetApplicability:
    role = evidence_role.value if isinstance(evidence_role, EvidenceRole) else str(evidence_role)
    status = applicability_status.value if isinstance(applicability_status, ApplicabilityStatus) else str(applicability_status)
    provenance_json = canonical_json(provenance)
    fingerprint = provenance_fingerprint(provenance)
    existing = session.query(ScientificDatasetApplicability).filter_by(
        scientific_dataset_id=scientific_dataset_id,
        jurisdiction_id=jurisdiction_id,
        evidence_role=role,
        provenance_fingerprint=fingerprint,
    ).one_or_none()
    if existing is not None:
        return existing
    if status == ApplicabilityStatus.AUTHORIZED.value and authorized_applicability(
        session, scientific_dataset_id, jurisdiction_id, role
    ) is not None:
        raise ValueError("Supersede the current authorization before creating another")
    row = ScientificDatasetApplicability(
        scientific_dataset_id=scientific_dataset_id,
        jurisdiction_id=jurisdiction_id,
        evidence_role=role,
        applicability_status=status,
        reconciliation_method=reconciliation_method,
        reconciliation_version=reconciliation_version,
        jurisdiction_boundary_id=jurisdiction_boundary_id,
        provenance_reference=provenance_reference,
        provenance_json=provenance_json,
        provenance_fingerprint=fingerprint,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        approved_by=approved_by,
        approved_at=approved_at,
    )
    session.add(row)
    session.flush()
    return row


def supersede_applicability(session: Session, row: ScientificDatasetApplicability):
    if row.applicability_status == ApplicabilityStatus.SUPERSEDED.value:
        return row
    row.applicability_status = ApplicabilityStatus.SUPERSEDED.value
    row.superseded_at = datetime.now(timezone.utc)
    session.flush()
    return row


def applicability_dependency(row: ScientificDatasetApplicability | None):
    if row is None:
        return None
    return {
        "id": row.id,
        "dataset_id": row.scientific_dataset_id,
        "jurisdiction_id": row.jurisdiction_id,
        "evidence_role": row.evidence_role,
        "status": row.applicability_status,
        "reconciliation_method": row.reconciliation_method,
        "reconciliation_version": row.reconciliation_version,
        "jurisdiction_boundary_id": row.jurisdiction_boundary_id,
        "provenance_fingerprint": row.provenance_fingerprint,
    }


__all__ = [
    "applicability_dependency", "authorized_applicability", "canonical_json",
    "create_applicability", "dataset_is_jurisdiction_compatible",
    "provenance_fingerprint", "supersede_applicability",
]
