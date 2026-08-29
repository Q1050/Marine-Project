"""Phase 11C-8 controlled ECOREEF independent-validation acquisition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import floor
from pathlib import Path

import numpy as np
import requests
from shapely.geometry import Point, shape

from anomaly_repository import canonical_json
from geographic_utils import haversine_km
from geographic_validation_inputs import DatasetRole, IndependenceStatus


ECOREEF_DATASET_KEY = "62451278-f873-46a5-914e-a25e010a1a37"
ECOREEF_DOI = "10.15468/vqhret"
GBIF_DATASET_API = "https://api.gbif.org/v1/dataset"
GBIF_OCCURRENCE_API = "https://api.gbif.org/v1/occurrence/search"
ACQUISITION_VERSION = "ecoreef-independent-validation-v1"


@dataclass(frozen=True)
class EcoreefRecord:
    occurrence_id: str
    event_id: str
    gbif_key: int
    scientific_name: str
    canonical_name: str
    taxon_key: int
    latitude: float | None
    longitude: float | None
    event_date: str | None
    basis_of_record: str | None
    occurrence_status: str | None
    sampling_protocol: str | None
    institution_code: str | None
    dataset_key: str
    boundary_status: str
    raw_record_json: str


@dataclass(frozen=True)
class LinkageResult:
    event_id: str
    classification: str
    reason: str
    matching_ids: tuple[str, ...]


@dataclass(frozen=True)
class EcoreefControlledArtifact:
    source_provider: str
    project: str
    dataset_key: str
    doi: str
    target_species: str
    target_jurisdiction: str
    role: str
    independence_status: str
    acquisition_version: str
    acquisition_parameters_json: str
    dataset_metadata_json: str
    boundary_provenance_json: str
    records: tuple[EcoreefRecord, ...]
    calibration_linkage: tuple[LinkageResult, ...]
    nas_linkage: tuple[LinkageResult, ...]
    source_record_count: int
    survey_event_count: int
    unique_spatial_location_count: int
    retrieved_at: str
    license: str
    limitations: tuple[str, ...]
    experimental_only: bool
    content_fingerprint: str


def normalize_species(value):
    value = value.split("(", 1)[0]
    return " ".join(value.strip().casefold().split())


def _date(value):
    return None if not value else str(value)[:10]


def acquire_records(*, session, target_species, jurisdiction, boundary, http=requests,
                    retrieved_at=None):
    parameters = {
        "dataset_key": ECOREEF_DATASET_KEY, "scientific_name": target_species,
        "country": "JM", "limit": 300,
    }
    dataset_response = http.get(f"{GBIF_DATASET_API}/{ECOREEF_DATASET_KEY}", timeout=60)
    dataset_response.raise_for_status()
    dataset_metadata = dataset_response.json()
    occurrence_response = http.get(GBIF_OCCURRENCE_API, params=parameters, timeout=60)
    occurrence_response.raise_for_status()
    occurrence_payload = occurrence_response.json()
    if occurrence_payload.get("endOfRecords") is not True:
        raise RuntimeError("ECOREEF acquisition was not complete")

    geometry = shape(json.loads(boundary.geometry_json))
    records = tuple(sorted((normalize_record(row, target_species, geometry)
                            for row in occurrence_payload.get("results", [])),
                           key=lambda row: (row.event_id, row.occurrence_id)))
    if any(normalize_species(row.canonical_name) != normalize_species(target_species) for row in records):
        raise ValueError("Acquisition contains a non-exact target taxon")

    from models import HistoricalOccurrence
    calibration = session.query(HistoricalOccurrence).filter_by(
        scientific_name=target_species
    ).order_by(HistoricalOccurrence.id).all()
    calibration_linkage = tuple(link_calibration(row, calibration) for row in records)
    nas_events = load_nas_events(Path("artifacts/experimental_validation/usgs-nas-963-jm-2026-08-21.json"))
    nas_linkage = tuple(link_nas(row, nas_events) for row in records)
    independence = decide_independence(records, calibration_linkage, dataset_metadata,
                                       jurisdiction, boundary)
    role = (DatasetRole.INDEPENDENT_VALIDATION_INPUT.value
            if independence == IndependenceStatus.INDEPENDENT
            else "CONTEXTUAL_VALIDATION_CANDIDATE")
    metadata = {
        key: dataset_metadata.get(key) for key in (
            "key", "title", "description", "doi", "license", "citation", "pubDate",
            "created", "modified", "samplingDescription", "project", "contacts",
            "publishingOrganizationKey", "installationKey", "endpoints",
        )
    }
    stable = {
        "source_provider": "UWI Discovery Bay Marine Laboratory",
        "project": "ECOREEF monitoring, Discovery Bay, Jamaica (2015-2017)",
        "dataset_key": ECOREEF_DATASET_KEY, "doi": ECOREEF_DOI,
        "target_species": target_species, "target_jurisdiction": jurisdiction.slug,
        "role": role, "independence_status": independence.value,
        "acquisition_version": ACQUISITION_VERSION, "parameters": parameters,
        "dataset_metadata": metadata,
        "boundary": boundary_provenance(boundary),
        "records": [asdict(row) for row in records],
        "calibration_linkage": [asdict(row) for row in calibration_linkage],
        "nas_linkage": [asdict(row) for row in nas_linkage],
        "limitations": limitations(records), "experimental_only": True,
    }
    return EcoreefControlledArtifact(
        source_provider=stable["source_provider"], project=stable["project"],
        dataset_key=ECOREEF_DATASET_KEY, doi=ECOREEF_DOI,
        target_species=target_species, target_jurisdiction=jurisdiction.slug,
        role=role, independence_status=independence.value,
        acquisition_version=ACQUISITION_VERSION,
        acquisition_parameters_json=canonical_json(parameters),
        dataset_metadata_json=canonical_json(metadata),
        boundary_provenance_json=canonical_json(stable["boundary"]),
        records=records, calibration_linkage=calibration_linkage, nas_linkage=nas_linkage,
        source_record_count=len(records),
        survey_event_count=len({row.event_id for row in records}),
        unique_spatial_location_count=len({(row.latitude, row.longitude) for row in records
                                           if row.latitude is not None and row.longitude is not None}),
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
        license=str(dataset_metadata.get("license") or ""),
        limitations=limitations(records), experimental_only=True,
        content_fingerprint=hashlib.sha256(canonical_json(stable).encode()).hexdigest(),
    )


def normalize_record(row, target_species, geometry):
    canonical = row.get("species") or row.get("canonicalName") or row.get("scientificName") or ""
    if normalize_species(canonical) != normalize_species(target_species):
        raise ValueError(f"Non-exact target taxon: {canonical}")
    latitude, longitude = row.get("decimalLatitude"), row.get("decimalLongitude")
    if latitude is None or longitude is None:
        boundary_status = "UNRESOLVED_GEOGRAPHY"
    else:
        boundary_status = ("INSIDE_OR_ON_BOUNDARY" if geometry.covers(
            Point(float(longitude), float(latitude))) else "OUTSIDE_BOUNDARY")
    return EcoreefRecord(
        occurrence_id=str(row.get("occurrenceID") or ""), event_id=str(row.get("eventID") or ""),
        gbif_key=int(row["key"]), scientific_name=str(row.get("scientificName") or ""),
        canonical_name=str(canonical), taxon_key=int(row["taxonKey"]),
        latitude=None if latitude is None else float(latitude),
        longitude=None if longitude is None else float(longitude),
        event_date=_date(row.get("eventDate")), basis_of_record=row.get("basisOfRecord"),
        occurrence_status=row.get("occurrenceStatus"), sampling_protocol=row.get("samplingProtocol"),
        institution_code=row.get("institutionCode"), dataset_key=str(row.get("datasetKey") or ""),
        boundary_status=boundary_status, raw_record_json=canonical_json(row),
    )


def link_calibration(record, calibration):
    record_ids = {record.occurrence_id.casefold(), str(record.gbif_key).casefold()}
    matches = []
    for row in calibration:
        ids = {str(value).casefold() for value in (row.occurrence_id, row.raw_source_id) if value}
        exact_id = bool(record_ids & ids)
        exact_event = (
            normalize_species(row.scientific_name) == normalize_species(record.canonical_name)
            and float(row.latitude) == record.latitude and float(row.longitude) == record.longitude
            and _date(row.event_date.isoformat() if row.event_date else None) == record.event_date
        )
        if exact_id or exact_event:
            matches.append(str(row.id))
    return LinkageResult(
        record.event_id, "VERIFIED_OVERLAP" if matches else "DISTINCT",
        "EXACT_IDENTIFIER_OR_SPECIES_COORDINATE_DATE" if matches else "NO_EXACT_CALIBRATION_LINK",
        tuple(sorted(matches)),
    )


def load_nas_events(path):
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(item for item in payload.get("events", []))


def link_nas(record, nas_events):
    matches, references = [], []
    for event in nas_events:
        candidate = event.get("candidate", {})
        same_space_time = (
            candidate.get("latitude") == record.latitude
            and candidate.get("longitude") == record.longitude
            and _date(candidate.get("event_date")) == record.event_date
        )
        if same_space_time:
            matches.append(str(candidate.get("provider_record_id")))
        reference_text = " ".join(candidate.get("source_reference_titles") or ()).casefold()
        if "ecoreef" in reference_text or "discovery bay marine" in reference_text:
            references.append(str(candidate.get("provider_record_id")))
    linked = tuple(sorted(set(matches + references)))
    return LinkageResult(
        record.event_id, "POSSIBLE_OVERLAP" if linked else "DISTINCT_CONTEXT_ONLY",
        "EXACT_COORDINATE_DATE_OR_ECOREEF_REFERENCE" if linked else "NO_EXACT_NAS_CONTEXT_LINK",
        linked,
    )


def decide_independence(records, calibration_linkage, metadata, jurisdiction, boundary):
    exact_taxonomy = bool(records) and all(
        normalize_species(row.canonical_name) == "pterois volitans" for row in records
    )
    original_ids = all(row.event_id and row.occurrence_id for row in records)
    boundary_valid = all(row.boundary_status == "INSIDE_OR_ON_BOUNDARY" for row in records)
    no_overlap = all(row.classification == "DISTINCT" for row in calibration_linkage)
    description = canonical_json(metadata).casefold()
    separate_provenance = all(token in description for token in (
        "discovery bay", "university of the west indies", "survey"
    ))
    if exact_taxonomy and original_ids and boundary_valid and no_overlap and separate_provenance:
        return IndependenceStatus.INDEPENDENT
    if any(row.classification == "VERIFIED_OVERLAP" for row in calibration_linkage):
        return IndependenceStatus.OVERLAPPING
    return IndependenceStatus.INDEPENDENCE_UNKNOWN


def boundary_provenance(boundary):
    return {"id": boundary.id, "source": boundary.source,
            "source_version": boundary.source_version,
            "source_reference": boundary.source_reference,
            "geometry_hash": boundary.geometry_hash}


def limitations(records):
    locations = {(row.latitude, row.longitude) for row in records}
    return (
        "Experimental independent-validation artifact; not a production baseline.",
        f"{len(records)} temporal survey rows represent {len(locations)} spatial location(s).",
        "Site-level external validation does not establish Jamaica-wide geographic extent.",
        "Candidate quantiles are diagnostics only and are not anomaly thresholds.",
    )


def write_artifact(artifact, path):
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(asdict(artifact)), encoding="utf-8")
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def independent_validation(artifact, calibration_variant, grid_size=.1):
    if artifact.independence_status != IndependenceStatus.INDEPENDENT.value:
        raise ValueError("Only an independently qualified artifact may be validated")
    records = tuple(row for row in artifact.records if row.boundary_status == "INSIDE_OR_ON_BOUNDARY")
    training = calibration_variant.points
    leave_one_out = []
    for index, point in enumerate(training):
        others = training[:index] + training[index + 1:]
        if others:
            leave_one_out.append(min(haversine_km(point.latitude, point.longitude, other.latitude, other.longitude)
                                     for other in others))
    q90 = None if not leave_one_out else float(np.quantile(leave_one_out, .9))
    q95 = None if not leave_one_out else float(np.quantile(leave_one_out, .95))
    cells = {(round(floor(point.latitude / grid_size) * grid_size + grid_size / 2, 10),
              round(floor(point.longitude / grid_size) * grid_size + grid_size / 2, 10)) for point in training}
    latitudes = [point.latitude for point in training]; longitudes = [point.longitude for point in training]
    event_rows = []
    for row in records:
        nearest = min(haversine_km(row.latitude, row.longitude, point.latitude, point.longitude) for point in training)
        nearest_cell = min(haversine_km(row.latitude, row.longitude, lat, lon) for lat, lon in cells)
        event_rows.append({
            "event_id": row.event_id, "occurrence_id": row.occurrence_id,
            "latitude": row.latitude, "longitude": row.longitude, "event_date": row.event_date,
            "nearest_calibration_evidence_km": nearest,
            "nearest_occupied_cell_km": nearest_cell,
            "inside_documented_envelope": min(latitudes) <= row.latitude <= max(latitudes)
                                           and min(longitudes) <= row.longitude <= max(longitudes),
            "above_q90_diagnostic": None if q90 is None else nearest > q90,
            "above_q95_diagnostic": None if q95 is None else nearest > q95,
        })
    locations = {}
    for row in event_rows:
        locations.setdefault((row["latitude"], row["longitude"]), []).append(row)
    location_rows = [{
        "latitude": key[0], "longitude": key[1], "survey_event_count": len(value),
        "nearest_calibration_evidence_km": value[0]["nearest_calibration_evidence_km"],
        "nearest_occupied_cell_km": value[0]["nearest_occupied_cell_km"],
        "inside_documented_envelope": value[0]["inside_documented_envelope"],
    } for key, value in sorted(locations.items())]
    return {
        "independence_status": artifact.independence_status,
        "calibration_input_fingerprint": calibration_variant.input_fingerprint,
        "validation_event_count": len(event_rows), "unique_location_count": len(location_rows),
        "q90_diagnostic_km": q90, "q95_diagnostic_km": q95,
        "event_level": event_rows, "unique_location_level": location_rows,
        "validation_dimensions": {
            "TEMPORAL_REPEAT_VALIDATION": True, "SITE_LEVEL_EXTERNAL_VALIDATION": True,
            "GEOGRAPHIC_EXTENT_VALIDATION": False,
        },
        "production_threshold": False,
    }


__all__ = [name for name in globals() if not name.startswith("_")]
