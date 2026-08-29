"""Generic, provider-neutral jurisdiction boundary registration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape

from models import JurisdictionBoundary


BOUNDARY_STATES = frozenset({"DRAFT", "ACTIVE", "SUPERSEDED", "REJECTED"})


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class BoundaryRegistration:
    jurisdiction_id: int
    boundary_type: str
    provider: str
    provider_version: str
    provider_boundary_identifier: str
    source_reference: str
    crs: str
    geometry: dict
    source_artifact_reference: str | None = None
    source_artifact_sha256: str | None = None
    acquisition_metadata: dict | None = None
    limitations: tuple[str, ...] = ()


def validate_registration(request: BoundaryRegistration) -> tuple[str, str]:
    if not all((request.boundary_type, request.provider, request.provider_version,
                request.provider_boundary_identifier, request.source_reference, request.crs)):
        raise ValueError("Boundary provider, identifier, version, type, reference, and CRS are required")
    geometry = shape(request.geometry)
    if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise ValueError("Boundary geometry must be a valid non-empty Polygon or MultiPolygon")
    geometry_json = canonical_json(mapping(geometry))
    geometry_hash = sha256_bytes(geometry_json.encode("utf-8"))
    reference = request.source_artifact_reference
    if reference and Path(reference).is_file():
        actual = sha256_bytes(Path(reference).read_bytes())
        if request.source_artifact_sha256 and actual != request.source_artifact_sha256:
            raise ValueError("Source artifact SHA-256 does not match")
    return geometry_json, geometry_hash


class JurisdictionBoundaryRegistry:
    def __init__(self, session): self.session = session

    def register_draft(self, request: BoundaryRegistration) -> JurisdictionBoundary:
        geometry_json, geometry_hash = validate_registration(request)
        duplicate = self.session.query(JurisdictionBoundary).filter_by(
            jurisdiction_id=request.jurisdiction_id, boundary_type=request.boundary_type,
            geometry_hash=geometry_hash, source=request.provider,
            source_version=request.provider_version,
        ).order_by(JurisdictionBoundary.id).first()
        if duplicate: return duplicate
        row = JurisdictionBoundary(
            jurisdiction_id=request.jurisdiction_id, boundary_type=request.boundary_type,
            geometry_json=geometry_json, source=request.provider,
            source_version=request.provider_version, source_reference=request.source_reference,
            provider_boundary_identifier=request.provider_boundary_identifier, crs=request.crs,
            source_artifact_reference=request.source_artifact_reference,
            source_artifact_sha256=request.source_artifact_sha256,
            geometry_hash=geometry_hash,
            acquisition_metadata_json=canonical_json(request.acquisition_metadata or {}),
            limitations_json=canonical_json(list(request.limitations)), status="DRAFT",
        )
        self.session.add(row); self.session.flush(); return row

    def activate(self, boundary: JurisdictionBoundary) -> JurisdictionBoundary:
        if boundary.status not in {"DRAFT", "ACTIVE"}:
            raise ValueError(f"Cannot activate boundary in {boundary.status} state")
        if boundary.status == "ACTIVE": return boundary
        active = self.session.query(JurisdictionBoundary).filter(
            JurisdictionBoundary.jurisdiction_id == boundary.jurisdiction_id,
            JurisdictionBoundary.boundary_type == boundary.boundary_type,
            JurisdictionBoundary.status == "ACTIVE",
        ).order_by(JurisdictionBoundary.id).all()
        if len(active) > 1: raise ValueError("Multiple active boundaries already exist")
        now = datetime.now(timezone.utc)
        if active:
            predecessor = active[0]
            predecessor.status = "SUPERSEDED"; predecessor.superseded_at = now
            boundary.predecessor_boundary_id = predecessor.id
            self.session.flush()
        boundary.status = "ACTIVE"; boundary.activated_at = now
        self.session.flush(); return boundary

    def reject(self, boundary: JurisdictionBoundary) -> JurisdictionBoundary:
        if boundary.status != "DRAFT": raise ValueError("Only DRAFT boundaries may be rejected")
        boundary.status = "REJECTED"; self.session.flush(); return boundary

    def register_and_activate(self, request: BoundaryRegistration):
        row = self.register_draft(request)
        inserted = row.status == "DRAFT"
        if row.status == "ACTIVE": return row, False
        return self.activate(row), inserted


__all__ = ["BoundaryRegistration", "JurisdictionBoundaryRegistry", "validate_registration"]
