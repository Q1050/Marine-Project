"""Administrative repositories for onboarding audit and sovereign parentage."""
from datetime import datetime, timezone
from models import ArtifactReference, Jurisdiction, JurisdictionOnboardingRecord
from jurisdiction_boundary_registry import canonical_json


def set_sovereign_parent(session, jurisdiction: Jurisdiction, parent: Jurisdiction | None):
    if jurisdiction.jurisdiction_type == "SOVEREIGN_STATE":
        if parent is not None: raise ValueError("Sovereign jurisdictions cannot have a sovereign parent")
        jurisdiction.sovereign_parent_id = None; return jurisdiction
    if parent is None or parent.jurisdiction_type != "SOVEREIGN_STATE":
        raise ValueError("Non-sovereign jurisdiction requires a sovereign-state parent")
    if jurisdiction.id is not None and parent.id == jurisdiction.id:
        raise ValueError("Jurisdiction cannot be its own sovereign parent")
    cursor = parent
    seen = set()
    while cursor is not None:
        if cursor.id in seen or (jurisdiction.id is not None and cursor.id == jurisdiction.id):
            raise ValueError("Circular sovereign-parent relationship")
        seen.add(cursor.id); cursor = cursor.sovereign_parent
    jurisdiction.sovereign_parent_id = parent.id; return jurisdiction


def create_artifact_reference(session, **values):
    if not values.get("local_path") and not values.get("external_uri"):
        raise ValueError("Artifact reference requires local_path or external_uri")
    sha = values["sha256"]
    if len(sha) != 64: raise ValueError("Artifact SHA-256 must contain 64 hexadecimal characters")
    int(sha, 16)
    existing=session.query(ArtifactReference).filter_by(sha256=sha).one_or_none()
    if existing: return existing
    row=ArtifactReference(**values); session.add(row); session.flush(); return row


def create_onboarding_record(session, *, jurisdiction, boundary, artifact_reference,
                             manifest, action_performed, execution_mode,
                             before_state, after_state, operator_reference=None):
    fingerprint=manifest["manifest_fingerprint"]
    existing=session.query(JurisdictionOnboardingRecord).filter_by(
        manifest_fingerprint=fingerprint, execution_mode=execution_mode).one_or_none()
    if existing: return existing
    row=JurisdictionOnboardingRecord(
        jurisdiction_id=jurisdiction.id, manifest_version=manifest["manifest_version"],
        manifest_fingerprint=fingerprint,
        canonical_identifier_scheme=manifest["jurisdiction"]["canonical_identifier_scheme"],
        canonical_identifier=manifest["jurisdiction"]["canonical_identifier"],
        boundary_id=boundary.id, source_artifact_reference_id=artifact_reference.id,
        boundary_source_sha256=boundary.source_artifact_sha256,
        geometry_sha256=boundary.geometry_hash, action_performed=action_performed,
        execution_mode=execution_mode, approval_state=manifest["approval_state"],
        applied_at=datetime.now(timezone.utc) if execution_mode == "APPLY" else None,
        operator_reference=operator_reference,
        before_state_json=canonical_json(before_state), after_state_json=canonical_json(after_state),
    )
    session.add(row); session.flush(); return row


__all__=["create_artifact_reference","create_onboarding_record","set_sovereign_parent"]
