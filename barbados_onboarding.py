"""Manifest-gated, single-jurisdiction Barbados geographic onboarding."""
from __future__ import annotations

import hashlib, json
from pathlib import Path
from shapely.geometry import shape

from jurisdiction_boundary_registry import BoundaryRegistration, JurisdictionBoundaryRegistry, canonical_json
from models import Jurisdiction, JurisdictionBoundary, Region


def load_boundary_artifact(path):
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    source = Path(artifact["source_artifact_reference"])
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != artifact["source_artifact_sha256"]:
        raise ValueError("Barbados source artifact SHA-256 mismatch")
    payload = json.loads(source_bytes)
    matches = [f for f in payload.get("features", []) if
               f.get("properties", {}).get("mrgid") == 8418 and
               f.get("properties", {}).get("iso_ter1") == "BRB" and
               f.get("properties", {}).get("pol_type") == "200NM" and
               f.get("properties", {}).get("territory2") is None]
    if len(matches) != 1: raise ValueError("Expected exactly one primary Barbados EEZ feature")
    geometry = shape(matches[0]["geometry"])
    if not geometry.is_valid or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Invalid Barbados geometry")
    from jurisdiction_boundary_registry import sha256_bytes
    geometry_hash = sha256_bytes(canonical_json(geometry.__geo_interface__).encode("utf-8"))
    if geometry_hash != artifact["geometry_sha256"]:
        raise ValueError("Barbados canonical geometry SHA-256 mismatch")
    return artifact, matches[0]


def load_reviewed_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    supplied = manifest.pop("manifest_fingerprint")
    actual = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
    if supplied != actual: raise ValueError("Onboarding manifest fingerprint mismatch")
    manifest["manifest_fingerprint"] = supplied
    if manifest.get("approval_state") != "APPROVED_FOR_CONTROLLED_PHASE_12A_4_APPLY":
        raise ValueError("Manifest is not approved for controlled apply")
    if manifest.get("scientific_configuration_expected") is not False:
        raise ValueError("Manifest must require an empty scientific configuration")
    if manifest.get("jurisdiction", {}).get("canonical_identifier") != "BB":
        raise ValueError("This apply path accepts only Barbados (BB)")
    return manifest


def plan_barbados(session, manifest_path):
    manifest = load_reviewed_manifest(manifest_path)
    artifact, _ = load_boundary_artifact(manifest["boundary_artifact_reference"])
    region = session.query(Region).filter_by(slug="caribbean").one()
    row = session.query(Jurisdiction).filter_by(canonical_identifier_scheme="ISO_3166_1_ALPHA_2", canonical_identifier="BB").one_or_none()
    action = "NO-OP" if row else "CREATE"
    boundary_action = "CREATE"
    if row:
        active = session.query(JurisdictionBoundary).filter_by(jurisdiction_id=row.id,boundary_type="MARINE_MONITORING",status="ACTIVE").all()
        if len(active)>1: boundary_action="CONFLICT"
        elif len(active)==1: boundary_action="NO-OP" if active[0].geometry_hash==artifact["geometry_sha256"] else "CONFLICT"
    return {"mode":"DRY_RUN","jurisdiction_action":action,"boundary_action":boundary_action,"region_id":region.id,"manifest_fingerprint":manifest["manifest_fingerprint"]}


def apply_barbados(session, manifest_path):
    plan = plan_barbados(session, manifest_path)
    if "CONFLICT" in {plan["jurisdiction_action"], plan["boundary_action"]}:
        raise ValueError("Barbados onboarding conflict")
    manifest = load_reviewed_manifest(manifest_path); artifact, feature = load_boundary_artifact(manifest["boundary_artifact_reference"])
    region = session.query(Region).filter_by(slug="caribbean").one()
    row = session.query(Jurisdiction).filter_by(canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="BB").one_or_none()
    if row is None:
        row=Jurisdiction(region_id=region.id,name="Barbados",slug="barbados",country_code="BB",canonical_identifier_scheme="ISO_3166_1_ALPHA_2",canonical_identifier="BB",jurisdiction_type="SOVEREIGN_STATE",status="ACTIVE",center_latitude=feature["properties"]["y_1"],center_longitude=feature["properties"]["x_1"],default_zoom=6)
        session.add(row); session.flush()
    if plan["boundary_action"] == "CREATE":
        request=BoundaryRegistration(row.id,artifact["boundary_type"],artifact["provider"],artifact["provider_version"],artifact["provider_boundary_identifier"],artifact["source_reference"],artifact["crs"],feature["geometry"],artifact["source_artifact_reference"],artifact["source_artifact_sha256"],{"acquired_at":artifact["acquired_at"],"acquisition_uri":artifact["acquisition_uri"],"inventory_version":artifact["inventory_version"],"manifest_fingerprint":manifest["manifest_fingerprint"]},tuple(artifact["limitations"]))
        JurisdictionBoundaryRegistry(session).register_and_activate(request)
    session.flush()
    return {**plan,"mode":"APPLY","jurisdiction_id":row.id}


__all__=["apply_barbados","load_boundary_artifact","load_reviewed_manifest","plan_barbados"]
