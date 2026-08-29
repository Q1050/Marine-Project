"""Focused Phase 11C-3 candidate geographic-baseline experiment tests."""

import inspect as pyinspect
import json

from geographic_baseline_experiment import GeographicBaselineExperiment
from models import HistoricalOccurrence, ScientificDataset
from test_phase11b2_evidence_readiness import context
from test_phase11c2_geographic_evidence import _boundary, _occurrence, _jamaica_dataset


def _fixture_variants(context):
    db, _, jurisdiction, _, _ = context
    _boundary(db, jurisdiction)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "a", 18.0, -77.0)
    _occurrence(db, dataset, "b", 18.0, -77.0)
    # Make the first two a deterministic exact event group (both dates NULL).
    _occurrence(db, dataset, "c", 18.2, -77.2)
    _occurrence(db, dataset, "d", 18.4, -77.4)
    _occurrence(db, dataset, "outside", 18.3, -74.0)
    db.commit()
    experiment = GeographicBaselineExperiment(
        db, "Pterois volitans", jurisdiction.id, [dataset.id]
    )
    return db, jurisdiction, dataset, experiment, experiment.create_variants()


def test_variant_creation_mapping_grouping_and_reconciliation(context):
    _, _, _, _, variants = _fixture_variants(context)
    assert set(variants) == {
        "FULL_SOURCE", "JURISDICTION_RECONCILED", "EVENT_GROUPED",
        "JURISDICTION_RECONCILED_EVENT_GROUPED",
    }
    assert len(variants["FULL_SOURCE"].source_occurrence_ids) == 5
    assert len(variants["JURISDICTION_RECONCILED"].source_occurrence_ids) == 4
    assert len(variants["EVENT_GROUPED"].points) == 4
    assert len(variants["JURISDICTION_RECONCILED_EVENT_GROUPED"].points) == 3
    assert len(variants["JURISDICTION_RECONCILED"].excluded_occurrence_ids) == 1
    grouped = [point for point in variants["EVENT_GROUPED"].points if len(point.source_occurrence_ids) == 2]
    assert len(grouped) == 1


def test_production_occurrence_rows_are_unchanged(context):
    db, _, dataset, experiment, _ = _fixture_variants(context)
    before = [(row.id, row.latitude, row.longitude, row.dataset_id) for row in db.query(HistoricalOccurrence).order_by(HistoricalOccurrence.id)]
    variants = experiment.create_variants()
    for variant in variants.values():
        experiment.analyze_variant(variant, [0.05, 0.1, 0.2])
    assert [(row.id, row.latitude, row.longitude, row.dataset_id) for row in db.query(HistoricalOccurrence).order_by(HistoricalOccurrence.id)] == before
    assert db.query(ScientificDataset).filter_by(id=dataset.id).one().record_count == 54


def test_leave_one_out_excludes_held_out_event(context):
    _, _, _, experiment, variants = _fixture_variants(context)
    variant = variants["JURISDICTION_RECONCILED_EVENT_GROUPED"]
    results = {row.method: row for row in experiment.analyze_variant(variant, [0.1])}
    output = json.loads(results["NEAREST_EVIDENCE_DISTRIBUTION"].output_json)
    assert output["self_exclusion"] is True
    assert all(row["remaining_candidate_event_count"] == len(variant.points) - 1 for row in output["held_out"])
    assert all(row["nearest_distance_km"] > 0 for row in output["held_out"])


def test_envelope_convex_hull_and_quantiles_are_deterministic(context):
    _, _, _, experiment, variants = _fixture_variants(context)
    first = experiment.analyze_variant(variants["FULL_SOURCE"], [0.1])
    second = experiment.analyze_variant(variants["FULL_SOURCE"], [0.1])
    assert [(row.method, row.output_json, row.result_fingerprint) for row in first] == [
        (row.method, row.output_json, row.result_fingerprint) for row in second
    ]
    by_method = {row.method: json.loads(row.output_json) for row in first}
    assert by_method["OBSERVED_ENVELOPE"]["maximum_longitude"] == -74.0
    assert by_method["DOCUMENTED_CONVEX_ENVELOPE"]["geometry_type"] == "Polygon"
    assert by_method["DOCUMENTED_CONVEX_ENVELOPE"]["interpretation"] == "documented_convex_envelope_only"
    assert by_method["DISTANCE_QUANTILE_CANDIDATE"]["q95_km"] is not None


def test_grid_resolution_is_explicit_and_sensitive(context):
    _, _, _, experiment, variants = _fixture_variants(context)
    result = next(
        row for row in experiment.analyze_variant(variants["FULL_SOURCE"], [0.05, 0.1, 0.2])
        if row.method == "OCCUPIED_CELL_SENSITIVITY"
    )
    configuration = json.loads(result.configuration_json)
    output = json.loads(result.output_json)
    assert configuration["grid_resolutions_degrees"] == [0.05, 0.1, 0.2]
    assert set(output) == {"0.05", "0.1", "0.2"}
    assert all("occupied_cell_count" in value for value in output.values())


def test_changed_input_changes_variant_and_result_fingerprints(context):
    db, _, dataset, experiment, variants = _fixture_variants(context)
    initial = variants["FULL_SOURCE"]
    initial_result = experiment.analyze_variant(initial, [0.1])[0]
    _occurrence(db, dataset, "added", 18.6, -77.6)
    db.commit()
    changed = experiment.create_variants()["FULL_SOURCE"]
    changed_result = experiment.analyze_variant(changed, [0.1])[0]
    assert changed.input_fingerprint != initial.input_fingerprint
    assert changed_result.result_fingerprint != initial_result.result_fingerprint


def test_artifacts_are_reproducible_and_experimental(tmp_path, context):
    _, _, _, experiment, variants = _fixture_variants(context)
    result = experiment.analyze_variant(variants["FULL_SOURCE"], [0.1])[0]
    first = experiment.write_artifact(result, tmp_path)
    content = first.read_text(encoding="utf-8")
    second = experiment.write_artifact(result, tmp_path)
    assert second.read_text(encoding="utf-8") == content
    payload = json.loads(content)
    assert json.loads(payload["provenance_json"])["experimental_only"] is True
    assert "overall_status" not in payload and "overall_classification" not in payload


def test_incompatible_jurisdiction_dataset_is_excluded(context):
    db, _, jamaica, bahamas, _ = context
    _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "jamaica", 18, -77)
    db.commit()
    experiment = GeographicBaselineExperiment(db, "Pterois volitans", bahamas.id, [dataset.id])
    _boundary(db, bahamas, -79, -73)
    variants = experiment.create_variants()
    assert variants["FULL_SOURCE"].source_dataset_ids == ()
    assert variants["FULL_SOURCE"].points == ()


def test_generic_execution_path_and_deferred_concave_hull(context):
    import geographic_baseline_experiment

    source = pyinspect.getsource(geographic_baseline_experiment).lower()
    for forbidden in (
        "jamaica", "bahamas", "pterois", "lionfish", "geographic_range_anomaly",
        "overall_classification", "<= 10", "<= 50",
    ):
        assert forbidden not in source
    assert "concave/alpha hull is deferred" in source
