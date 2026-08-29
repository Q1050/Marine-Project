"""Focused Phase 11C-5 validation input hardening tests."""

import inspect

from geographic_baseline_experiment import ExperimentPoint
from geographic_baseline_validation import GeographicBaselineValidator, IndependentValidationInput
from geographic_validation_inputs import (
    DatasetRole, ExpertCaseLabel, ExpertGeographicCase, GeographicValidationSnapshot,
    IndependenceStatus, RequirementStatus, ValidationDataset, ValidationOccurrence,
    deduplicate_cross_source, readiness_report,
)
from test_phase11b2_evidence_readiness import context
from test_phase11c3_geographic_baseline_experiment import _fixture_variants


def _dataset(identifier, role, jurisdiction_id=1):
    return ValidationDataset(identifier, role, "Example species", jurisdiction_id, None,
                             "provider", "reference", "v1", "a" * 64)


def _occ(dataset, identifier, authoritative=None):
    return ValidationOccurrence(dataset, identifier, "Example species", 18.0, -77.0,
                                "2020-01-01", "provider", authoritative, None, "upstream")


def test_snapshot_is_frozen_deterministic_role_separated_and_artifact_only(tmp_path):
    datasets = (_dataset(2, DatasetRole.INDEPENDENT_VALIDATION_INPUT),
                _dataset(1, DatasetRole.CALIBRATION_OCCURRENCE_INPUT))
    kwargs = dict(species="Example species", species_program_id=None, jurisdiction_id=1,
                  region_id=None, datasets=datasets, occurrences=(_occ(1, 10),),
                  boundary_provenance={"version": "v1"}, configuration={"block": .2},
                  generated_at="2026-01-01T00:00:00+00:00")
    first = GeographicValidationSnapshot.create(**kwargs)
    second = GeographicValidationSnapshot.create(**kwargs)
    assert first.input_fingerprint == second.input_fingerprint
    assert first.configuration_sha256 == second.configuration_sha256
    assert first.experimental_only is True
    assert [row.role for row in first.datasets] == [DatasetRole.CALIBRATION_OCCURRENCE_INPUT,
                                                     DatasetRole.INDEPENDENT_VALIDATION_INPUT]
    assert first.write(tmp_path / "snapshot.json").exists()
    try:
        first.species = "Changed"
        assert False
    except Exception:
        pass


def test_exact_cross_source_duplicate_preserves_contributors_and_no_fuzzy_match():
    rows = (_occ(1, 10, "inat:100"), _occ(2, 20, "inat:100"),
            ValidationOccurrence(3, 30, "Example species", 18.0001, -77.0,
                                 "2020-01-01", "provider", None, None, "upstream"))
    events = deduplicate_cross_source(rows)
    linked = next(row for row in events if len(row.contributing_dataset_ids) == 2)
    assert linked.contributing_dataset_ids == (1, 2)
    assert linked.contributing_occurrence_ids == (10, 20)
    assert linked.independence.value == "VERIFIED"
    assert len(events) == 2


def test_independence_overlap_and_unknown_are_conservative(context):
    _, jurisdiction, dataset, _, variants = _fixture_variants(context)
    variant = variants["FULL_SOURCE"]
    point = (ExperimentPoint(18.6, -77.6, None, "external", (9999,)),)
    validator = GeographicBaselineValidator(.2, 3, [7])
    unknown = IndependentValidationInput((dataset.id + 1,), jurisdiction.id, variant.species, point)
    assert validator.assess_independence(variant, unknown)["independence_status"] == IndependenceStatus.INDEPENDENCE_UNKNOWN
    overlap = IndependentValidationInput(variant.source_dataset_ids, jurisdiction.id, variant.species, point)
    assert validator.assess_independence(variant, overlap)["independence_status"] == IndependenceStatus.OVERLAPPING


def test_expert_cases_are_descriptive_and_unresolved_abstains(context):
    _, jurisdiction, _, _, variants = _fixture_variants(context)
    variant = variants["FULL_SOURCE"]
    case = ExpertGeographicCase("case-1", variant.species, jurisdiction.id, 18.2, -77.2,
                                ExpertCaseLabel.UNRESOLVED, "expert-1", "ref", "2026-01-01",
                                "{}", "v1")
    result = GeographicBaselineValidator(.2, 3, [7]).validate_expert_cases(variant, (case,), {"q90": 5.0})
    assert result["unresolved_abstention_count"] == 1
    assert "NOT_CLASSIFIER_ACCURACY" in result["interpretation"]


def test_contiguous_folds_deterministic_no_leakage_and_sensitivity_explicit(context):
    _, _, _, _, variants = _fixture_variants(context)
    variant = variants["FULL_SOURCE"]
    validator = GeographicBaselineValidator(.2, 3, [7, 11])
    first = validator.spatial_folds(variant, "CONTIGUOUS_LONGITUDE_STRIPS")
    assert first == validator.spatial_folds(variant, "CONTIGUOUS_LONGITUDE_STRIPS")
    for fold in first:
        assert set(fold.training_event_indices).isdisjoint(fold.held_out_event_indices)
    result = validator.block_size_sensitivity(variant, (.1, .2, .5), 3, (7, 11))
    assert result["block_sizes_degrees"] == [.1, .2, .5]
    assert result["production_block_size_selected"] is False


def test_readiness_requires_independent_and_expert_evidence():
    report = readiness_report("Example species", 99, "ANOMALY_ACTIVATION", {
        "INDEPENDENT_OCCURRENCE_SOURCE": (RequirementStatus.NOT_SATISFIED, "No independent source."),
        "EXPERT_ORDINARY_CASES": (RequirementStatus.NOT_SATISFIED, "No ordinary cases."),
        "EXPERT_QUESTIONABLE_CASES": (RequirementStatus.NOT_SATISFIED, "No questionable cases."),
    }, "fingerprint")
    statuses = {row.name: row.status for row in report.requirements}
    assert statuses["INDEPENDENT_OCCURRENCE_SOURCE"] == RequirementStatus.NOT_SATISFIED
    assert statuses["EXPERT_ORDINARY_CASES"] == RequirementStatus.NOT_SATISFIED
    assert report.ready is False


def test_generic_contract_has_no_activation_or_numeric_science_thresholds():
    import geographic_validation_inputs
    source = inspect.getsource(geographic_validation_inputs).lower()
    for forbidden in ("jamaica", "bahamas", "pterois", "geographic_range_anomaly", "q90", "q95"):
        assert forbidden not in source
    assert "geographicoccurrencebaseline" not in source
