import hashlib
import json
from pathlib import Path

from shapely.geometry import mapping, shape

from models import Jurisdiction, JurisdictionBoundary, Region
from jurisdiction_boundary_registry import BoundaryRegistration, JurisdictionBoundaryRegistry, sha256_bytes


JAMAICA_MRGID = 8459
BAHAMAS_MRGID = 8404
BOUNDARY_TYPE = "MARINE_MONITORING"
SOURCE = "Marine Regions / VLIZ"
SOURCE_VERSION = "Maritime Boundaries Geodatabase EEZ v12 (2023-10-25)"
SOURCE_REFERENCE = "https://doi.org/10.14284/632"


def canonical_geometry_json(geometry):
    return json.dumps(mapping(geometry), separators=(",", ":"), sort_keys=True)


def geometry_sha256(geometry_json):
    return hashlib.sha256(geometry_json.encode("utf-8")).hexdigest()


def load_jamaica_geometry(source_path):
    """Select only Jamaica's EEZ feature, excluding the Jamaica/Colombia joint regime."""
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    matches = [
        feature for feature in payload.get("features", [])
        if feature.get("properties", {}).get("mrgid") == JAMAICA_MRGID
        and feature.get("properties", {}).get("iso_ter1") == "JAM"
        and feature.get("properties", {}).get("pol_type") == "200NM"
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one Jamaica MRGID {JAMAICA_MRGID} feature; found {len(matches)}.")
    geometry = shape(matches[0]["geometry"])
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Unsupported geometry type: {geometry.geom_type}.")
    if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise ValueError("Jamaica source geometry is empty, invalid, or has zero area.")
    min_x, min_y, max_x, max_y = geometry.bounds
    if not (-90 < min_x < max_x < -60 and 10 < min_y < max_y < 30):
        raise ValueError(f"Implausible Jamaica geometry bounds: {geometry.bounds}.")
    return geometry, matches[0].get("properties", {})


def load_bahamas_geometry(source_path):
    """Select only the Bahamas primary 200NM EEZ; shared regimes are excluded."""
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if payload.get("crs", {}).get("properties", {}).get("name") not in {
        "urn:ogc:def:crs:EPSG::4326", "EPSG:4326",
    }:
        raise ValueError("Bahamas source must use EPSG:4326.")
    matches = [
        feature for feature in payload.get("features", [])
        if feature.get("properties", {}).get("mrgid") == BAHAMAS_MRGID
        and feature.get("properties", {}).get("iso_ter1") == "BHS"
        and feature.get("properties", {}).get("pol_type") == "200NM"
        and feature.get("properties", {}).get("territory2") is None
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one primary Bahamas MRGID {BAHAMAS_MRGID} feature; "
            f"found {len(matches)}."
        )
    geometry = shape(matches[0]["geometry"])
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Unsupported geometry type: {geometry.geom_type}.")
    if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
        raise ValueError("Bahamas source geometry is empty, invalid, or has zero area.")
    min_x, min_y, max_x, max_y = geometry.bounds
    if not (-85 < min_x < max_x < -65 and 18 < min_y < max_y < 32):
        raise ValueError(f"Implausible Bahamas geometry bounds: {geometry.bounds}.")
    return geometry, matches[0].get("properties", {})


def _activate_boundary(db, region_slug, jurisdiction_slug, geometry, properties, source_path=None):
    jurisdiction = (
        db.query(Jurisdiction)
        .join(Region)
        .filter(Region.slug == region_slug, Jurisdiction.slug == jurisdiction_slug)
        .one()
    )
    request = BoundaryRegistration(
        jurisdiction_id=jurisdiction.id, boundary_type=BOUNDARY_TYPE,
        provider=SOURCE, provider_version=SOURCE_VERSION,
        provider_boundary_identifier=str(properties["mrgid"]),
        source_reference=SOURCE_REFERENCE, crs="EPSG:4326",
        geometry=mapping(geometry),
        source_artifact_reference=None if source_path is None else str(Path(source_path)),
        source_artifact_sha256=None if source_path is None else sha256_bytes(Path(source_path).read_bytes()),
        acquisition_metadata={"provider_properties": properties},
    )
    boundary, inserted = JurisdictionBoundaryRegistry(db).register_and_activate(request)
    db.commit()
    db.refresh(boundary)
    return boundary, inserted, properties


def activate_jamaica_boundary(db, source_path):
    geometry, properties = load_jamaica_geometry(source_path)
    return _activate_boundary(db, "caribbean", "jamaica", geometry, properties, source_path)


def activate_bahamas_boundary(db, source_path):
    geometry, properties = load_bahamas_geometry(source_path)
    return _activate_boundary(db, "caribbean", "bahamas", geometry, properties, source_path)
