"""Focused Phase 11C-6 independent source integration tests."""

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError

import pytest
from shapely.geometry import box

from geographic_validation_inputs import RequirementStatus, readiness_report
from independent_occurrence_source import (
    CandidateEventClassification, CandidateOccurrence, SourceProvenance,
    TaxonomicCompatibility, audit_candidate, build_controlled_artifact,
    classify_taxonomy, summarize_audit, write_controlled_artifact,
)


class Calibration:
    def __init__(self, identifier, occurrence_id=None, raw_source_id=None):
        self.id = identifier
        self.occurrence_id = occurrence_id
        self.raw_source_id = raw_source_id


def candidate(**changes):
    values = dict(provider_record_id="nas-1", scientific_name="Pterois volitans",
                  latitude=18.0, longitude=-77.0, event_date="2020-01-01",
                  upstream_occurrence_id=None, authoritative_id="NAS:1",
                  source_reference_ids=(), source_reference_titles=(),
                  raw_provenance_json="{}", independence_basis_verified=False)
    values.update(changes)
    return CandidateOccurrence(**values)


def test_exact_and_upstream_overlap_across_provider():
    event = audit_candidate(candidate(upstream_occurrence_id="inat:10"),
                            [Calibration(7, occurrence_id="INAT:10")],
                            "Pterois volitans", box(-78, 17, -76, 19))
    assert event.cross_source_classification == CandidateEventClassification.VERIFIED_OVERLAP
    assert event.matching_calibration_occurrence_ids == (7,)


def test_provider_difference_does_not_imply_independence_and_unknown_is_conservative():
    event = audit_candidate(candidate(), [], "Pterois volitans", box(-78, 17, -76, 19))
    assert event.cross_source_classification == CandidateEventClassification.INDEPENDENCE_UNKNOWN


def test_verified_separate_distinct_event():
    event = audit_candidate(candidate(independence_basis_verified=True), [],
                            "Pterois volitans", box(-78, 17, -76, 19))
    assert event.cross_source_classification == CandidateEventClassification.DISTINCT


def test_ambiguous_taxon_not_promoted_to_species():
    assert classify_taxonomy("Pterois volitans/miles", "Pterois volitans") == TaxonomicCompatibility.SPECIES_COMPLEX_OR_AMBIGUOUS
    assert classify_taxonomy("Pterois spp.", "Pterois volitans") == TaxonomicCompatibility.GENUS_ONLY


def test_boundary_reconciliation_reports_all_states():
    boundary = box(-78, 17, -76, 19)
    rows = [
        audit_candidate(candidate(), [], "Pterois volitans", boundary),
        audit_candidate(candidate(provider_record_id="2", latitude=20), [], "Pterois volitans", boundary),
        audit_candidate(candidate(provider_record_id="3", latitude=None), [], "Pterois volitans", boundary),
    ]
    summary = summarize_audit(rows)
    assert (summary["inside_or_on_boundary"], summary["outside_boundary"],
            summary["unresolved_geography"]) == (1, 1, 1)


def test_controlled_artifact_sha_and_immutability(tmp_path):
    provenance = SourceProvenance("provider", "dataset", "reference", "API", "{}",
                                  "2026-01-01", "species", "region", "public", "candidate")
    event = audit_candidate(candidate(), [], "Pterois volitans", box(-78, 17, -76, 19))
    artifact = build_controlled_artifact(provenance, (event,))
    path, file_sha = write_controlled_artifact(artifact, tmp_path / "source.json")
    assert file_sha == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FrozenInstanceError):
        artifact.experimental_only = False


def test_ambiguous_source_never_enters_calibration_or_independent_validation():
    event = audit_candidate(candidate(scientific_name="Pterois volitans/miles"), [],
                            "Pterois volitans", box(-78, 17, -76, 19))
    summary = summarize_audit((event,))
    assert summary["species_compatible_boundary_distinct_records"] == 0


def test_readiness_stays_blocked_without_experts_or_independent_source():
    statuses = {
        "INDEPENDENT_OCCURRENCE_SOURCE": (RequirementStatus.NOT_SATISFIED, "No qualifying events"),
        "EXPERT_ORDINARY_CASES": (RequirementStatus.NOT_SATISFIED, "Absent"),
        "EXPERT_QUESTIONABLE_CASES": (RequirementStatus.NOT_SATISFIED, "Absent"),
    }
    report = readiness_report("Pterois volitans", 1, "ANOMALY_ACTIVATION", statuses, "fp")
    assert report.ready is False


def test_generic_module_has_no_production_activation_or_place_taxon_literals():
    import independent_occurrence_source
    source = inspect.getsource(independent_occurrence_source).lower()
    for forbidden in ("jamaica", "bahamas", "pterois", "geographic_range_anomaly",
                      "geographicoccurrencebaseline"):
        assert forbidden not in source
