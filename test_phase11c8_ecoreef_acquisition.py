"""Focused Phase 11C-8 ECOREEF acquisition tests."""

import hashlib
import inspect
from dataclasses import replace

import pytest
from shapely.geometry import box

from ecoreef_validation_acquisition import (
    ECOREEF_DATASET_KEY, EcoreefControlledArtifact, EcoreefRecord, LinkageResult,
    decide_independence, independent_validation, link_calibration, link_nas,
    normalize_record, normalize_species, write_artifact,
)
from geographic_validation_inputs import DatasetRole, IndependenceStatus, RequirementStatus, readiness_report
from test_phase11b2_evidence_readiness import context
from test_phase11c3_geographic_baseline_experiment import _fixture_variants


class Calibration:
    id = 7
    scientific_name = "Pterois volitans"
    latitude = 18.1
    longitude = -77.1
    occurrence_id = "cal-7"
    raw_source_id = "obis-7"
    event_date = None


def raw(key=1, event="event-1", occurrence="uwi-1", lat=18.2, lon=-77.2):
    return {
        "key": key, "occurrenceID": occurrence, "eventID": event,
        "scientificName": "Pterois volitans (Linnaeus, 1758)",
        "species": "Pterois volitans", "taxonKey": 2334438,
        "decimalLatitude": lat, "decimalLongitude": lon, "eventDate": "2017-01-01",
        "basisOfRecord": "HUMAN_OBSERVATION", "occurrenceStatus": "PRESENT",
        "samplingProtocol": "AGRRA", "institutionCode": "UWI",
        "datasetKey": ECOREEF_DATASET_KEY,
    }


def record(**changes):
    payload = raw(**changes)
    return normalize_record(payload, "Pterois volitans", box(-78, 17, -76, 19))


def artifact(records, independence="INDEPENDENT"):
    links = tuple(LinkageResult(row.event_id, "DISTINCT", "NO_EXACT", ()) for row in records)
    return EcoreefControlledArtifact(
        "UWI Discovery Bay Marine Laboratory", "ECOREEF", ECOREEF_DATASET_KEY,
        "10.15468/vqhret", "Pterois volitans", "jamaica",
        DatasetRole.INDEPENDENT_VALIDATION_INPUT.value, independence, "v1", "{}", "{}", "{}",
        tuple(records), links, links, len(records), len({r.event_id for r in records}),
        len({(r.latitude, r.longitude) for r in records}), "2026-01-01", "CC BY 4.0",
        ("experimental",), True, "fingerprint",
    )


def test_exact_taxonomy_only_and_event_ids_preserved():
    row = record()
    assert normalize_species(row.canonical_name) == "pterois volitans"
    assert row.event_id == "event-1" and row.occurrence_id == "uwi-1"
    with pytest.raises(ValueError, match="Non-exact"):
        normalize_record({**raw(), "species": "Pterois volitans/miles"},
                         "Pterois volitans", box(-78, 17, -76, 19))


def test_repeated_events_one_coordinate_are_one_spatial_location():
    rows = (record(key=1, event="e1", occurrence="o1"),
            record(key=2, event="e2", occurrence="o2"))
    value = artifact(rows)
    assert value.source_record_count == 2 and value.survey_event_count == 2
    assert value.unique_spatial_location_count == 1


def test_boundary_reconciliation_preserves_outside_and_unresolved():
    inside = record()
    outside = normalize_record(raw(key=2, event="e2", occurrence="o2", lat=20),
                               "Pterois volitans", box(-78, 17, -76, 19))
    unresolved = normalize_record({**raw(key=3, event="e3", occurrence="o3"),
                                   "decimalLatitude": None},
                                  "Pterois volitans", box(-78, 17, -76, 19))
    assert [inside.boundary_status, outside.boundary_status, unresolved.boundary_status] == [
        "INSIDE_OR_ON_BOUNDARY", "OUTSIDE_BOUNDARY", "UNRESOLVED_GEOGRAPHY"]


def test_exact_obis_overlap_and_provider_difference_not_enough():
    row = record(occurrence="cal-7")
    assert link_calibration(row, [Calibration()]).classification == "VERIFIED_OVERLAP"
    distinct = record(occurrence="other")
    assert link_calibration(distinct, [Calibration()]).classification == "DISTINCT"


def test_nas_exact_context_link_and_ambiguous_taxon_not_promoted():
    row = record()
    nas = ({"candidate": {"provider_record_id": "nas-1", "latitude": row.latitude,
                           "longitude": row.longitude, "event_date": row.event_date,
                           "scientific_name": "Pterois volitans/miles",
                           "source_reference_titles": []}},)
    result = link_nas(row, nas)
    assert result.classification == "POSSIBLE_OVERLAP"


def test_independent_role_only_after_all_checks():
    rows = (record(),)
    links = (LinkageResult("event-1", "DISTINCT", "none", ()),)
    metadata = {"description": "University of the West Indies Discovery Bay survey"}
    jurisdiction = type("J", (), {"slug": "example"})()
    boundary = object()
    assert decide_independence(rows, links, metadata, jurisdiction, boundary) == IndependenceStatus.INDEPENDENT
    overlap = (LinkageResult("event-1", "VERIFIED_OVERLAP", "id", ("1",)),)
    assert decide_independence(rows, overlap, metadata, jurisdiction, boundary) == IndependenceStatus.OVERLAPPING


def test_artifact_sha_reproducible(tmp_path):
    value = artifact((record(),))
    first, sha1 = write_artifact(value, tmp_path / "a.json")
    second, sha2 = write_artifact(value, tmp_path / "b.json")
    assert sha1 == sha2 == hashlib.sha256(first.read_bytes()).hexdigest()


def test_independent_validation_keeps_calibration_separate_and_reports_levels(context):
    _, _, _, _, variants = _fixture_variants(context)
    variant = variants["JURISDICTION_RECONCILED_EVENT_GROUPED"]
    value = artifact((record(key=1, event="e1", occurrence="o1"),
                      record(key=2, event="e2", occurrence="o2")))
    result = independent_validation(value, variant)
    assert result["calibration_input_fingerprint"] == variant.input_fingerprint
    assert result["validation_event_count"] == 2 and result["unique_location_count"] == 1
    assert result["validation_dimensions"]["GEOGRAPHIC_EXTENT_VALIDATION"] is False
    assert result["production_threshold"] is False


def test_readiness_still_blocks_activation_and_no_production_contracts():
    report = readiness_report("Example species", 1, "ANOMALY_ACTIVATION", {
        "INDEPENDENT_OCCURRENCE_SOURCE": (RequirementStatus.SATISFIED, "ECOREEF"),
        "EXPERT_ORDINARY_CASES": (RequirementStatus.NOT_SATISFIED, "Absent"),
        "EXPERT_QUESTIONABLE_CASES": (RequirementStatus.NOT_SATISFIED, "Absent"),
    }, "fp")
    assert report.ready is False
    import ecoreef_validation_acquisition
    source = inspect.getsource(ecoreef_validation_acquisition).casefold()
    assert "geographicoccurrencebaseline" not in source
    assert "geographic_range_anomaly" not in source
