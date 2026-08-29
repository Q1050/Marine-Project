"""Focused Phase 11C-4 spatial validation tests."""

import inspect as pyinspect
import json

import pytest

from geographic_baseline_experiment import ExperimentPoint
from geographic_baseline_validation import (
    GeographicBaselineValidator,
    IndependentValidationInput,
)
from test_phase11b2_evidence_readiness import context
from test_phase11c3_geographic_baseline_experiment import _fixture_variants


def _validator():
    return GeographicBaselineValidator(0.2, 3, seeds=[7, 11, 19], subsample_fraction=0.8)


def test_spatial_folds_deterministic_and_have_no_block_or_id_leakage(context):
    _, _, _, _, variants = _fixture_variants(context)
    variant = variants["FULL_SOURCE"]
    validator = _validator()
    first = validator.spatial_folds(variant)
    second = validator.spatial_folds(variant)
    assert first == second
    for fold in first:
        assert set(fold.training_source_occurrence_ids).isdisjoint(fold.held_out_source_occurrence_ids)
        assert set(fold.training_event_indices).isdisjoint(fold.held_out_event_indices)
        assert set(fold.training_event_indices) | set(fold.held_out_event_indices) == set(range(len(variant.points)))


def test_grouped_source_ids_are_held_out_together(context):
    _, _, _, _, variants = _fixture_variants(context)
    variant = variants["EVENT_GROUPED"]
    grouped_ids = next(point.source_occurrence_ids for point in variant.points if len(point.source_occurrence_ids) > 1)
    fold = next(fold for fold in _validator().spatial_folds(variant) if grouped_ids[0] in fold.held_out_source_occurrence_ids)
    assert set(grouped_ids) <= set(fold.held_out_source_occurrence_ids)
    assert set(grouped_ids).isdisjoint(fold.training_source_occurrence_ids)


def test_held_out_distributions_operating_points_and_grid_are_descriptive(context):
    _, _, _, _, variants = _fixture_variants(context)
    report = _validator().validate(variants["FULL_SOURCE"])[0]
    metrics = json.loads(report.descriptive_metrics_json)
    operating = json.loads(report.operating_point_analysis_json)
    assert metrics["known_occurrence_distance_summary"]["n"] == len(variants["FULL_SOURCE"].points)
    assert metrics["known_occurrence_distance_summary"]["q95_km"] is not None
    assert metrics["terminology"] == "KNOWN_OCCURRENCE_FALSE_FLAG_PROXY"
    assert all(item["production_threshold"] is False for item in operating.values())
    assert set(metrics["folds"][0]["grid_resolution_sensitivity"]) == {"0.05", "0.1", "0.2"}


def test_subsampling_and_report_fingerprints_are_deterministic(context):
    _, _, _, _, variants = _fixture_variants(context)
    validator = _validator()
    first = validator.validate(variants["JURISDICTION_RECONCILED_EVENT_GROUPED"])
    second = validator.validate(variants["JURISDICTION_RECONCILED_EVENT_GROUPED"])
    assert first == second
    stability = json.loads(first[0].stability_metrics_json)
    uncertainty = json.loads(first[0].uncertainty_json)
    assert [row["seed"] for row in stability["runs"]] == [7, 11, 19]
    assert stability["sampling"] == "without_replacement"
    assert "not_confidence_interval" in uncertainty["interval_type"]


def test_changed_input_changes_validation_fingerprint(context):
    db, _, dataset, experiment, variants = _fixture_variants(context)
    validator = _validator()
    first = validator.validate(variants["FULL_SOURCE"])[0]
    from test_phase11c2_geographic_evidence import _occurrence
    _occurrence(db, dataset, "changed", 18.7, -77.7); db.commit()
    changed = experiment.create_variants()["FULL_SOURCE"]
    second = validator.validate(changed)[0]
    assert first.input_fingerprint != second.input_fingerprint
    assert first.result_fingerprint != second.result_fingerprint


def test_external_validation_is_isolated_from_calibration(context):
    _, jurisdiction, dataset, _, variants = _fixture_variants(context)
    variant = variants["FULL_SOURCE"]
    external = IndependentValidationInput(
        scientific_dataset_ids=(dataset.id + 1000,), jurisdiction_id=jurisdiction.id,
        species=variant.species,
        points=(ExperimentPoint(18.6, -77.6, None, "external", (9999,)),),
    )
    result = _validator().validate_independent_input(variant, external)
    assert result["calibration_input_unchanged"] == variant.input_fingerprint
    assert result["distance_summary"]["n"] == 1
    with pytest.raises(ValueError, match="overlap"):
        _validator().validate_independent_input(
            variant,
            IndependentValidationInput(variant.source_dataset_ids, jurisdiction.id, variant.species, external.points),
        )


def test_artifact_reproducible_and_no_production_or_anomaly_fields(tmp_path, context):
    _, _, _, _, variants = _fixture_variants(context)
    report = _validator().validate(variants["FULL_SOURCE"])[0]
    first = _validator().write_report(report, tmp_path)
    content = first.read_text(encoding="utf-8")
    assert _validator().write_report(report, tmp_path).read_text(encoding="utf-8") == content
    payload = json.loads(content)
    assert json.loads(payload["provenance_json"])["experimental_only"] is True
    assert "overall_status" not in payload and "overall_classification" not in payload


def test_generic_source_has_no_place_species_threshold_or_production_approval():
    import geographic_baseline_validation

    source = pyinspect.getsource(geographic_baseline_validation).lower()
    for forbidden in (
        "jamaica", "bahamas", "pterois", "lionfish", "caribbean",
        "geographic_range_anomaly", "production_approved", "<= 10", "<= 50",
    ):
        assert forbidden not in source
