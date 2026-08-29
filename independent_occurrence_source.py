"""Generic experimental independent-occurrence source integration.

No object in this module is a production baseline or anomaly decision.  Exact
linkage is deliberately conservative and never infers species identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from shapely.geometry import Point, shape

from anomaly_repository import canonical_json


SOURCE_INTEGRATION_VERSION = "independent-occurrence-source-v1"


class TaxonomicCompatibility(str, Enum):
    EXACT_SPECIES_MATCH = "EXACT_SPECIES_MATCH"
    SPECIES_COMPLEX_OR_AMBIGUOUS = "SPECIES_COMPLEX_OR_AMBIGUOUS"
    GENUS_ONLY = "GENUS_ONLY"
    INCOMPATIBLE = "INCOMPATIBLE"


class CandidateEventClassification(str, Enum):
    VERIFIED_OVERLAP = "VERIFIED_OVERLAP"
    POSSIBLE_OVERLAP = "POSSIBLE_OVERLAP"
    DISTINCT = "DISTINCT"
    INDEPENDENCE_UNKNOWN = "INDEPENDENCE_UNKNOWN"


@dataclass(frozen=True)
class SourceProvenance:
    provider: str
    dataset_name: str
    source_reference: str
    acquisition_method: str
    acquisition_parameters_json: str
    retrieved_at: str
    taxon_representation: str
    geographic_scope: str
    usage_constraints: str
    role: str


@dataclass(frozen=True)
class CandidateOccurrence:
    provider_record_id: str
    scientific_name: str
    latitude: float | None
    longitude: float | None
    event_date: str | None
    upstream_occurrence_id: str | None
    authoritative_id: str | None
    source_reference_ids: tuple[str, ...]
    source_reference_titles: tuple[str, ...]
    raw_provenance_json: str
    independence_basis_verified: bool = False


@dataclass(frozen=True)
class AuditedCandidateEvent:
    candidate: CandidateOccurrence
    taxonomic_compatibility: TaxonomicCompatibility
    boundary_status: str
    cross_source_classification: CandidateEventClassification
    matching_calibration_occurrence_ids: tuple[int, ...]
    classification_reason: str


@dataclass(frozen=True)
class ControlledSourceArtifact:
    provenance: SourceProvenance
    events: tuple[AuditedCandidateEvent, ...]
    integration_version: str
    experimental_only: bool
    content_sha256: str


def classify_taxonomy(candidate_name: str, target_species: str) -> TaxonomicCompatibility:
    candidate = " ".join(candidate_name.strip().casefold().split())
    target = " ".join(target_species.strip().casefold().split())
    if candidate == target:
        return TaxonomicCompatibility.EXACT_SPECIES_MATCH
    target_genus = target.split()[0] if target else ""
    if candidate in {target_genus, f"{target_genus} spp.", f"{target_genus} sp."}:
        return TaxonomicCompatibility.GENUS_ONLY
    if target_genus and candidate.startswith(target_genus + " ") and any(
        marker in candidate for marker in ("/", " complex", " spp.", " sp.")
    ):
        return TaxonomicCompatibility.SPECIES_COMPLEX_OR_AMBIGUOUS
    return TaxonomicCompatibility.INCOMPATIBLE


def reconcile_boundary(candidate: CandidateOccurrence, boundary_geometry) -> str:
    if candidate.latitude is None or candidate.longitude is None:
        return "UNRESOLVED_GEOGRAPHY"
    geometry = shape(boundary_geometry) if isinstance(boundary_geometry, dict) else boundary_geometry
    return "INSIDE_OR_ON_BOUNDARY" if geometry.covers(
        Point(candidate.longitude, candidate.latitude)
    ) else "OUTSIDE_BOUNDARY"


def audit_candidate(candidate, calibration_records, target_species, boundary_geometry):
    taxonomy = classify_taxonomy(candidate.scientific_name, target_species)
    boundary = reconcile_boundary(candidate, boundary_geometry)
    authoritative = candidate.authoritative_id.casefold() if candidate.authoritative_id else None
    upstream = candidate.upstream_occurrence_id.casefold() if candidate.upstream_occurrence_id else None
    exact_matches = []
    for row in calibration_records:
        identifiers = {
            str(value).strip().casefold() for value in (
                getattr(row, "occurrence_id", None), getattr(row, "raw_source_id", None),
                getattr(row, "authoritative_id", None), getattr(row, "upstream_occurrence_id", None),
            ) if value
        }
        if authoritative and authoritative in identifiers or upstream and upstream in identifiers:
            exact_matches.append(int(row.id))
    if exact_matches:
        classification = CandidateEventClassification.VERIFIED_OVERLAP
        reason = "IDENTICAL_AUTHORITATIVE_OR_UPSTREAM_IDENTIFIER"
    elif any("inaturalist" in title.casefold() for title in candidate.source_reference_titles):
        classification = CandidateEventClassification.POSSIBLE_OVERLAP
        reason = "INATURALIST_DERIVATION_WITHOUT_LINKABLE_OBSERVATION_ID"
    elif candidate.independence_basis_verified and (candidate.authoritative_id or candidate.upstream_occurrence_id):
        classification = CandidateEventClassification.DISTINCT
        reason = "VERIFIED_SEPARATE_ACQUISITION_AND_NO_EXACT_CALIBRATION_LINK"
    else:
        classification = CandidateEventClassification.INDEPENDENCE_UNKNOWN
        reason = "NO_CROSS_SOURCE_LINKAGE_IDENTIFIER"
    return AuditedCandidateEvent(candidate, taxonomy, boundary, classification,
                                 tuple(sorted(exact_matches)), reason)


def build_controlled_artifact(provenance, events):
    events = tuple(sorted(events, key=lambda item: item.candidate.provider_record_id))
    payload = {
        "provenance": asdict(provenance), "events": [asdict(item) for item in events],
        "integration_version": SOURCE_INTEGRATION_VERSION, "experimental_only": True,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return ControlledSourceArtifact(provenance, events, SOURCE_INTEGRATION_VERSION, True, digest)


def write_controlled_artifact(artifact, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(asdict(artifact)), encoding="utf-8")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, actual


def summarize_audit(events):
    events = tuple(events)
    count = lambda value, attr: sum(getattr(row, attr).value == value for row in events)
    return {
        "total_candidate_records": len(events),
        "exact_overlaps": count("VERIFIED_OVERLAP", "cross_source_classification"),
        "possible_overlaps": count("POSSIBLE_OVERLAP", "cross_source_classification"),
        "distinct_records": count("DISTINCT", "cross_source_classification"),
        "independence_unknown_records": count("INDEPENDENCE_UNKNOWN", "cross_source_classification"),
        "taxonomically_ambiguous_records": count("SPECIES_COMPLEX_OR_AMBIGUOUS", "taxonomic_compatibility"),
        "species_compatible_boundary_distinct_records": sum(
            row.taxonomic_compatibility == TaxonomicCompatibility.EXACT_SPECIES_MATCH
            and row.boundary_status == "INSIDE_OR_ON_BOUNDARY"
            and row.cross_source_classification == CandidateEventClassification.DISTINCT
            for row in events
        ),
        "with_coordinates": sum(row.candidate.latitude is not None and row.candidate.longitude is not None for row in events),
        "inside_or_on_boundary": sum(row.boundary_status == "INSIDE_OR_ON_BOUNDARY" for row in events),
        "outside_boundary": sum(row.boundary_status == "OUTSIDE_BOUNDARY" for row in events),
        "unresolved_geography": sum(row.boundary_status == "UNRESOLVED_GEOGRAPHY" for row in events),
    }


__all__ = [name for name in globals() if not name.startswith("_")]
