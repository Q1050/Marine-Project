"""Focused Phase 11C-9 expert-reference contract tests."""

import inspect
from dataclasses import FrozenInstanceError

import pytest

from expert_geographic_reference import (
    ConsensusOutcome, ExpertCaseDefinition, ExpertReferenceArtifact,
    ExpertReviewerLabel, ReviewerProvenanceStatus, ReviewerQualification,
    consensus_for_case, descriptive_validation, pilot_readiness_status,
)
from geographic_validation_inputs import ExpertCaseLabel, RequirementStatus


def case(identifier="case-1", species="Example species", jurisdiction=2):
    return ExpertCaseDefinition(identifier, species, jurisdiction, 1.0, 2.0, None,
                                "source", "{}", "pilot-v1", ("experimental",))


def label(reviewer, value, identifier="case-1"):
    return ExpertReviewerLabel(
        identifier, reviewer, ReviewerQualification.MARINE_BIOLOGIST,
        ReviewerProvenanceStatus.ASSERTED_NOT_VERIFIED, value, "evidence",
        "Concise documented rationale.", "2026-01-01", "{}", "pilot-v1", ("pilot",),
    )


def test_cases_and_reviewer_labels_are_immutable_and_independent():
    item = case(); first = label("r1", ExpertCaseLabel.ORDINARY)
    second = label("r2", ExpertCaseLabel.QUESTIONABLE_OR_UNUSUAL)
    with pytest.raises(FrozenInstanceError):
        item.species = "changed"
    assert first.label != second.label


def test_disagreement_is_preserved_without_numeric_averaging():
    result = consensus_for_case((label("r1", ExpertCaseLabel.ORDINARY),
                                 label("r2", ExpertCaseLabel.QUESTIONABLE_OR_UNUSUAL)))
    assert result["outcome"] == ConsensusOutcome.DISAGREEMENT
    assert result["consensus_label"] is None


def test_unresolved_and_unanimous_rules_are_explicit():
    unresolved = consensus_for_case((label("r1", ExpertCaseLabel.UNRESOLVED),))
    agreed = consensus_for_case((label("r1", ExpertCaseLabel.ORDINARY),
                                 label("r2", ExpertCaseLabel.ORDINARY)))
    assert unresolved["outcome"] == ConsensusOutcome.UNRESOLVED
    assert agreed == {"outcome": "AGREED", "consensus_label": "ORDINARY",
                      "reason": "UNANIMOUS_REVIEWER_LABELS"}


def test_artifact_fingerprint_is_canonical_and_reviewer_duplicates_rejected():
    kwargs = dict(species="Example species", jurisdiction_id=2, version="pilot-v1",
                  cases=(case(),), reviewer_labels=(label("r1", ExpertCaseLabel.ORDINARY),),
                  provenance={"source": "controlled"}, limitations=("pilot",))
    assert ExpertReferenceArtifact.create(**kwargs).fingerprint == ExpertReferenceArtifact.create(**kwargs).fingerprint
    with pytest.raises(ValueError, match="one immutable label"):
        ExpertReferenceArtifact.create(**{**kwargs, "reviewer_labels": kwargs["reviewer_labels"] * 2})


def test_descriptive_usage_has_no_threshold_or_automatic_anomaly():
    point = type("P", (), {"latitude": 1.1, "longitude": 2.1})()
    output = descriptive_validation((case(),), (label("r1", ExpertCaseLabel.ORDINARY),),
                                    (point,), ((1.1, 2.1),), (0, 3, 0, 3))
    assert output["threshold_derived"] is False
    assert output["rows"][0]["expert_label"] == "ORDINARY"


def test_pilot_is_unknown_not_automatically_satisfied():
    status, _ = pilot_readiness_status((case(),),
                                       (label("r1", ExpertCaseLabel.ORDINARY),),
                                       ExpertCaseLabel.ORDINARY)
    assert status == RequirementStatus.UNKNOWN
    missing, _ = pilot_readiness_status((case(),), (), ExpertCaseLabel.ORDINARY)
    assert missing == RequirementStatus.NOT_SATISFIED


def test_generic_contract_has_no_place_taxon_threshold_or_production_activation():
    import expert_geographic_reference
    source = inspect.getsource(expert_geographic_reference).casefold()
    for forbidden in ("jamaica", "pterois", "bahamas", "geographic_range_anomaly",
                      "geographicoccurrencebaseline", "q90", "q95"):
        assert forbidden not in source
