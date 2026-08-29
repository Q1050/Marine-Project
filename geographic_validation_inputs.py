"""Experimental Phase 11C-5 validation-input and readiness contracts.

These frozen objects are artifacts for scientific evaluation only.  They do
not persist or activate a production geographic occurrence baseline.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from anomaly_repository import canonical_json


SNAPSHOT_VERSION = "geographic-validation-snapshot-v1"
DEDUPLICATION_VERSION = "cross-source-exact-linkage-v1"


class DatasetRole(str, Enum):
    CALIBRATION_OCCURRENCE_INPUT = "CALIBRATION_OCCURRENCE_INPUT"
    INDEPENDENT_VALIDATION_INPUT = "INDEPENDENT_VALIDATION_INPUT"
    EXPERT_REFERENCE_INPUT = "EXPERT_REFERENCE_INPUT"


class IndependenceStatus(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    OVERLAPPING = "OVERLAPPING"
    INDEPENDENCE_UNKNOWN = "INDEPENDENCE_UNKNOWN"


class EventIndependence(str, Enum):
    VERIFIED = "VERIFIED"
    POSSIBLE_OVERLAP = "POSSIBLE_OVERLAP"
    DISTINCT = "DISTINCT"


class ExpertCaseLabel(str, Enum):
    ORDINARY = "ORDINARY"
    QUESTIONABLE_OR_UNUSUAL = "QUESTIONABLE_OR_UNUSUAL"
    UNRESOLVED = "UNRESOLVED"


class RequirementStatus(str, Enum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ValidationDataset:
    scientific_dataset_id: int
    role: DatasetRole
    species: str
    jurisdiction_id: int | None
    region_id: int | None
    provider: str
    source_reference: str | None
    version: str | None
    artifact_sha256: str | None

    def __post_init__(self):
        if not self.species or not self.provider:
            raise ValueError("Dataset species and provider ownership are required")
        if self.jurisdiction_id is None and self.region_id is None:
            raise ValueError("Dataset jurisdiction or region ownership is required")


@dataclass(frozen=True)
class ValidationOccurrence:
    dataset_id: int
    occurrence_id: int
    scientific_name: str
    latitude: float
    longitude: float
    event_date: str | None
    provider: str
    authoritative_id: str | None = None
    upstream_occurrence_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class DeduplicatedEvent:
    canonical_event_id: str
    scientific_name: str
    latitude: float
    longitude: float
    event_date: str | None
    contributing_dataset_ids: tuple[int, ...]
    contributing_occurrence_ids: tuple[int, ...]
    contributing_provider_ids: tuple[str, ...]
    deduplication_method: str
    independence: EventIndependence


def deduplicate_cross_source(records) -> tuple[DeduplicatedEvent, ...]:
    """Collapse exact cross-source links without spatial or temporal fuzziness."""
    groups: dict[tuple, list[ValidationOccurrence]] = {}
    methods: dict[tuple, str] = {}
    for row in records:
        if row.authoritative_id:
            key = ("AUTHORITATIVE_ID", row.authoritative_id.strip().casefold())
            method = "IDENTICAL_AUTHORITATIVE_IDENTIFIER"
        elif row.upstream_occurrence_id:
            key = ("UPSTREAM_ID", row.upstream_occurrence_id.strip().casefold())
            method = "IDENTICAL_UPSTREAM_OCCURRENCE_ID"
        else:
            key = (
                "EXACT_EVENT", row.scientific_name.strip().casefold(),
                float(row.latitude), float(row.longitude), row.event_date,
                (row.source or row.provider).strip().casefold(),
            )
            method = "EXACT_SPECIES_COORDINATE_DATE_SOURCE"
        groups.setdefault(key, []).append(row)
        methods[key] = method

    events = []
    for key, members in sorted(groups.items(), key=lambda item: canonical_json(item[0])):
        dataset_ids = tuple(sorted({row.dataset_id for row in members}))
        occurrence_ids = tuple(sorted({row.occurrence_id for row in members}))
        provider_ids = tuple(sorted({
            f"{row.provider}:{row.authoritative_id or row.upstream_occurrence_id or row.occurrence_id}"
            for row in members
        }))
        payload = {"key": key, "datasets": dataset_ids, "occurrences": occurrence_ids}
        independence = (
            EventIndependence.VERIFIED if len(dataset_ids) > 1 and key[0] in {"AUTHORITATIVE_ID", "UPSTREAM_ID"}
            else EventIndependence.POSSIBLE_OVERLAP if len(dataset_ids) > 1
            else EventIndependence.DISTINCT
        )
        first = members[0]
        events.append(DeduplicatedEvent(
            canonical_event_id=hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
            scientific_name=first.scientific_name, latitude=first.latitude,
            longitude=first.longitude, event_date=first.event_date,
            contributing_dataset_ids=dataset_ids,
            contributing_occurrence_ids=occurrence_ids,
            contributing_provider_ids=provider_ids,
            deduplication_method=methods[key], independence=independence,
        ))
    return tuple(events)


@dataclass(frozen=True)
class GeographicValidationSnapshot:
    species: str
    species_program_id: int | None
    jurisdiction_id: int
    region_id: int | None
    datasets: tuple[ValidationDataset, ...]
    source_occurrence_ids: tuple[int, ...]
    boundary_provenance_json: str
    deduplication_method_version: str
    effective_events: tuple[DeduplicatedEvent, ...]
    configuration_json: str
    configuration_sha256: str
    input_fingerprint: str
    generated_at: str
    limitations: tuple[str, ...]
    experimental_only: bool = True

    @classmethod
    def create(cls, *, species, species_program_id, jurisdiction_id, region_id,
               datasets, occurrences, boundary_provenance, configuration,
               generated_at=None, limitations=()):
        datasets = tuple(sorted(datasets, key=lambda item: item.scientific_dataset_id))
        occurrences = tuple(sorted(occurrences, key=lambda item: (item.dataset_id, item.occurrence_id)))
        events = deduplicate_cross_source(occurrences)
        config_json = canonical_json(configuration)
        boundary_json = canonical_json(boundary_provenance)
        stable = {
            "version": SNAPSHOT_VERSION, "species": species,
            "species_program_id": species_program_id, "jurisdiction_id": jurisdiction_id,
            "region_id": region_id, "datasets": [asdict(item) for item in datasets],
            "occurrences": [asdict(item) for item in occurrences],
            "events": [asdict(item) for item in events], "boundary": boundary_provenance,
            "deduplication_version": DEDUPLICATION_VERSION, "configuration": configuration,
        }
        return cls(
            species=species, species_program_id=species_program_id,
            jurisdiction_id=jurisdiction_id, region_id=region_id, datasets=datasets,
            source_occurrence_ids=tuple(row.occurrence_id for row in occurrences),
            boundary_provenance_json=boundary_json,
            deduplication_method_version=DEDUPLICATION_VERSION,
            effective_events=events, configuration_json=config_json,
            configuration_sha256=hashlib.sha256(config_json.encode()).hexdigest(),
            input_fingerprint=hashlib.sha256(canonical_json(stable).encode()).hexdigest(),
            generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
            limitations=tuple(limitations), experimental_only=True,
        )

    def write(self, path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(asdict(self)), encoding="utf-8")
        return target


@dataclass(frozen=True)
class ExpertGeographicCase:
    case_id: str
    species: str
    jurisdiction_id: int
    latitude: float
    longitude: float
    label: ExpertCaseLabel
    expert_reference_id: str
    evidence_reference: str
    labelled_at: str
    provenance_json: str
    version: str
    notes: str | None = None


@dataclass(frozen=True)
class ReadinessRequirement:
    name: str
    status: RequirementStatus
    explanation: str


@dataclass(frozen=True)
class ValidationReadinessReport:
    species: str
    jurisdiction_id: int
    purpose: str
    requirements: tuple[ReadinessRequirement, ...]
    ready: bool
    input_fingerprint: str
    experimental_only: bool = True


BASELINE_REQUIREMENTS = (
    "BOUNDARY_RECONCILED_CALIBRATION", "EFFECTIVE_SPATIAL_EVENTS_SUFFICIENT",
    "SPATIAL_FOLD_BEHAVIOR_STABLE", "INDEPENDENT_OCCURRENCE_SOURCE",
    "CROSS_SOURCE_DEDUPLICATION_COMPLETE", "COMPLETE_PROVENANCE",
    "SCIENTIFIC_REVIEWER_APPROVAL",
)
ACTIVATION_REQUIREMENTS = BASELINE_REQUIREMENTS + (
    "EXPERT_ORDINARY_CASES", "EXPERT_QUESTIONABLE_CASES",
    "KNOWN_OCCURRENCE_FALSE_FLAG_PROXY_ACCEPTABLE",
    "BLOCK_AND_RESAMPLING_STABILITY_ACCEPTABLE",
)


def readiness_report(species, jurisdiction_id, purpose, statuses, input_fingerprint):
    required = BASELINE_REQUIREMENTS if purpose == "BASELINE_PERSISTENCE" else ACTIVATION_REQUIREMENTS
    rows = tuple(ReadinessRequirement(
        name=name,
        status=statuses.get(name, (RequirementStatus.UNKNOWN, "Evidence has not been established."))[0],
        explanation=statuses.get(name, (RequirementStatus.UNKNOWN, "Evidence has not been established."))[1],
    ) for name in required)
    return ValidationReadinessReport(
        species=species, jurisdiction_id=jurisdiction_id, purpose=purpose,
        requirements=rows,
        ready=all(row.status == RequirementStatus.SATISFIED for row in rows),
        input_fingerprint=input_fingerprint,
    )


__all__ = [name for name in globals() if not name.startswith("_")]
