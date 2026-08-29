"""Experimental expert geographic reference-set contract (Phase 11C-9)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from anomaly_repository import canonical_json
from geographic_utils import haversine_km
from geographic_validation_inputs import ExpertCaseLabel, RequirementStatus


REFERENCE_SET_VERSION = "expert-geographic-reference-v1"


LABEL_SEMANTICS = {
    ExpertCaseLabel.ORDINARY: (
        "Geographic context is consistent with the expert's documented domain evidence; "
        "this is not a statement of universal normality."
    ),
    ExpertCaseLabel.QUESTIONABLE_OR_UNUSUAL: (
        "Geographic context deserves scientific scrutiny; this is not confirmation of an ecological anomaly."
    ),
    ExpertCaseLabel.UNRESOLVED: (
        "Available evidence is insufficient for the reviewer to classify geographic context safely."
    ),
}


class ReviewerQualification(str, Enum):
    MARINE_BIOLOGIST = "MARINE_BIOLOGIST"
    FISHERIES_SCIENTIST = "FISHERIES_SCIENTIST"
    INVASIVE_SPECIES_SPECIALIST = "INVASIVE_SPECIES_SPECIALIST"
    TRAINED_AGENCY_REVIEWER = "TRAINED_AGENCY_REVIEWER"
    QUALIFIED_REEF_MONITORING_SCIENTIST = "QUALIFIED_REEF_MONITORING_SCIENTIST"


class ReviewerProvenanceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    ASSERTED_NOT_VERIFIED = "ASSERTED_NOT_VERIFIED"


class ConsensusOutcome(str, Enum):
    AGREED = "AGREED"
    DISAGREEMENT = "DISAGREEMENT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ExpertCaseDefinition:
    case_id: str
    species: str
    jurisdiction_id: int
    latitude: float
    longitude: float
    event_date: str | None
    source_reference: str
    provenance_json: str
    version: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ExpertReviewerLabel:
    case_id: str
    reviewer_id: str
    reviewer_qualification: ReviewerQualification
    reviewer_provenance_status: ReviewerProvenanceStatus
    label: ExpertCaseLabel
    evidence_reference: str
    rationale_summary: str
    labelled_at: str
    provenance_json: str
    version: str
    limitations: tuple[str, ...]

    def __post_init__(self):
        if not self.reviewer_id or not self.evidence_reference:
            raise ValueError("Reviewer identity and evidence reference are required")
        if len(self.rationale_summary) > 1000:
            raise ValueError("Rationale must be a concise summary, not extended reasoning")


@dataclass(frozen=True)
class ExpertCaseCandidate:
    case_id: str
    species: str
    jurisdiction_id: int
    latitude: float
    longitude: float
    event_date: str | None
    source: str
    source_reference: str
    existing_identity_status: str
    nearest_historical_distance_km: float | None
    envelope_membership: str
    boundary_membership: str
    suitability_score: float | None
    suitability_band: str | None
    review_sampling_reason: str
    proposed_label: None = None


@dataclass(frozen=True)
class ExpertReferenceArtifact:
    species: str
    jurisdiction_id: int
    version: str
    cases: tuple[ExpertCaseDefinition, ...]
    reviewer_labels: tuple[ExpertReviewerLabel, ...]
    consensus_json: str
    provenance_json: str
    limitations: tuple[str, ...]
    experimental_only: bool
    fingerprint: str

    @classmethod
    def create(cls, *, species, jurisdiction_id, version, cases, reviewer_labels,
               provenance, limitations):
        cases = tuple(sorted(cases, key=lambda row: row.case_id))
        labels = tuple(sorted(reviewer_labels, key=lambda row: (row.case_id, row.reviewer_id)))
        case_ids = {row.case_id for row in cases}
        if len(case_ids) != len(cases):
            raise ValueError("case_id must be unique")
        if any(row.species != species or row.jurisdiction_id != jurisdiction_id for row in cases):
            raise ValueError("Case ownership is incompatible with the reference set")
        if any(row.case_id not in case_ids for row in labels):
            raise ValueError("Reviewer label references an unknown case")
        reviewer_keys = {(row.case_id, row.reviewer_id) for row in labels}
        if len(reviewer_keys) != len(labels):
            raise ValueError("A reviewer may submit only one immutable label per case/version")
        consensus = {case.case_id: consensus_for_case(
            tuple(row for row in labels if row.case_id == case.case_id)
        ) for case in cases}
        stable = {
            "contract_version": REFERENCE_SET_VERSION, "species": species,
            "jurisdiction_id": jurisdiction_id, "version": version,
            "cases": [asdict(row) for row in cases],
            "reviewer_labels": [asdict(row) for row in labels],
            "consensus": consensus, "provenance": provenance,
            "limitations": list(limitations), "experimental_only": True,
        }
        return cls(
            species, jurisdiction_id, version, cases, labels,
            canonical_json(consensus), canonical_json(provenance), tuple(limitations), True,
            hashlib.sha256(canonical_json(stable).encode()).hexdigest(),
        )

    def write(self, path):
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(asdict(self)), encoding="utf-8")
        return target


def consensus_for_case(labels):
    labels = tuple(labels)
    if not labels:
        return {"outcome": ConsensusOutcome.UNRESOLVED.value, "consensus_label": None,
                "reason": "NO_REVIEWER_LABELS"}
    values = {row.label for row in labels}
    if values == {ExpertCaseLabel.UNRESOLVED}:
        return {"outcome": ConsensusOutcome.UNRESOLVED.value,
                "consensus_label": ExpertCaseLabel.UNRESOLVED.value,
                "reason": "ALL_REVIEWERS_UNRESOLVED"}
    if len(values) == 1:
        label = next(iter(values))
        return {"outcome": ConsensusOutcome.AGREED.value, "consensus_label": label.value,
                "reason": "UNANIMOUS_REVIEWER_LABELS"}
    return {"outcome": ConsensusOutcome.DISAGREEMENT.value, "consensus_label": None,
            "reason": "REVIEWER_LABELS_DIFFER"}


def staged_review_disclosure():
    return {
        "stage_1": {
            "visible": ["species", "location", "date", "basic_source_evidence"],
            "hidden": ["candidate_distance_metrics", "suitability_output", "candidate_operating_points"],
            "purpose": "MINIMIZE_MODEL_AND_DISTANCE_ANCHORING",
        },
        "stage_2": {
            "visible": ["historical_occurrence_context", "suitability_context",
                        "candidate_distance_metrics", "source_limitations"],
            "purpose": "DOCUMENT_CONTEXT_SENSITIVITY_WITHOUT_REPLACING_STAGE_1_LABEL",
        },
    }


def descriptive_validation(cases, reviewer_labels, calibration_points, occupied_cells,
                           envelope, suitability_lookup=None):
    """Calculate context by expert label without deriving an operating threshold."""
    case_map = {row.case_id: row for row in cases}
    rows = []
    for label in reviewer_labels:
        case = case_map[label.case_id]
        nearest = None if not calibration_points else min(
            haversine_km(case.latitude, case.longitude, point.latitude, point.longitude)
            for point in calibration_points
        )
        cell_distance = None if not occupied_cells else min(
            haversine_km(case.latitude, case.longitude, latitude, longitude)
            for latitude, longitude in occupied_cells
        )
        suitability = None if suitability_lookup is None else suitability_lookup(case.latitude, case.longitude)
        rows.append({
            "case_id": case.case_id, "reviewer_id": label.reviewer_id,
            "expert_label": label.label.value,
            "nearest_calibration_evidence_km": nearest,
            "nearest_occupied_cell_km": cell_distance,
            "inside_documented_envelope": (
                envelope[0] <= case.latitude <= envelope[1]
                and envelope[2] <= case.longitude <= envelope[3]
            ),
            "suitability_context": suitability,
        })
    return {
        "rows": rows,
        "labels_preserved_independently": True,
        "threshold_derived": False,
        "interpretation": "DESCRIPTIVE_EXPERT_REFERENCE_COMPARISON_ONLY",
    }


def pilot_readiness_status(cases, labels, target_label):
    relevant = [row for row in labels if row.label == target_label]
    if not relevant:
        return RequirementStatus.NOT_SATISFIED, "No expert labels of this type exist."
    return RequirementStatus.UNKNOWN, (
        "Pilot labels exist, but adequacy and reviewer agreement have not been scientifically approved."
    )


__all__ = [name for name in globals() if not name.startswith("_")]
