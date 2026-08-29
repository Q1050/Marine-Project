"""Focused Phase 11C-2 descriptive geographic-evidence tests."""

import inspect as pyinspect
import json
from datetime import datetime

import pytest

from anomaly_geographic_evidence import GeographicEvidenceService
from geographic_utils import haversine_km
from models import (
    AnomalyAssessment,
    AnomalySignal,
    HistoricalOccurrence,
    JurisdictionBoundary,
    Region,
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
)
from scientific_applicability_domain import ApplicabilityStatus, EvidenceRole
from scientific_dataset_applicability import create_applicability
from test_phase11b2_evidence_readiness import add_observation, context


def _boundary(db, jurisdiction, minimum_longitude=-80, maximum_longitude=-75):
    row = JurisdictionBoundary(
        jurisdiction_id=jurisdiction.id,
        boundary_type="MARINE_MONITORING",
        geometry_json=json.dumps({
            "type": "Polygon",
            "coordinates": [[
                [minimum_longitude, 16], [maximum_longitude, 16],
                [maximum_longitude, 20], [minimum_longitude, 20],
                [minimum_longitude, 16],
            ]],
        }),
        source="Boundary provider", source_version="v1",
        source_reference="boundary-reference", geometry_hash="boundary-hash",
        status="ACTIVE",
    )
    db.add(row)
    db.commit()
    return row


def _occurrence(db, dataset, key, latitude, longitude, event_date=None):
    row = HistoricalOccurrence(
        scientific_name="Pterois volitans", taxon_id=1,
        latitude=latitude, longitude=longitude, event_date=event_date,
        occurrence_id=key, raw_source_id=key, source="OBIS",
        deduplication_key=key, dataset_id=dataset.id,
    )
    db.add(row)
    db.flush()
    return row


def _jamaica_dataset(db):
    return db.query(ScientificDataset).filter_by(slug="jamaica-occ").one()


def test_nearest_haversine_distance_and_deterministic_tie(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    first = _occurrence(db, dataset, "first", 18.5, -77.0)
    _occurrence(db, dataset, "second", 18.5, -77.0)
    db.commit()
    observation = add_observation(db, jamaica, latitude=18.0, longitude=-77.0)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert result.nearest_occurrence_distance_km == pytest.approx(
        haversine_km(18.0, -77.0, 18.5, -77.0), abs=1e-6
    )
    assert result.nearest_occurrence_id == first.id
    assert "great-circle" in result.distance_metric_description


def test_occupied_cells_are_deterministic_and_resolution_explicit(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "one", 18.01, -77.01)
    _occurrence(db, dataset, "two", 18.04, -77.04)
    _occurrence(db, dataset, "three", 18.11, -77.11)
    db.commit()
    observation = add_observation(db, jamaica, latitude=18.0, longitude=-77.0)
    service = GeographicEvidenceService(db, grid_resolution_degrees=0.1)
    first = service.evaluate_observation(observation.id)
    second = service.evaluate_observation(observation.id)
    assert first.grid_resolution_degrees == 0.1
    assert first.occupied_cell_count == 2
    assert first.nearest_occupied_cell_distance_km == second.nearest_occupied_cell_distance_km
    assert first.nearest_occupied_cell_latitude == second.nearest_occupied_cell_latitude


def test_documented_envelope_and_temporal_summary(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "old", 18.0, -78.0, datetime(2010, 1, 1))
    _occurrence(db, dataset, "new", 19.0, -76.0, datetime(2020, 1, 1))
    _occurrence(db, dataset, "undated", 18.5, -77.0)
    db.commit()
    inside = add_observation(db, jamaica, latitude=18.4, longitude=-77.0)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(inside.id)
    assert result.inside_documented_occurrence_envelope is True
    assert (result.historical_min_latitude, result.historical_max_latitude) == (18.0, 19.0)
    assert result.records_with_dates == 2 and result.records_without_dates == 1
    assert result.earliest_historical_record.startswith("2010-01-01")
    assert result.latest_historical_record.startswith("2020-01-01")
    assert not hasattr(result, "species_range_membership")


def test_jamaica_dataset_does_not_leak_to_bahamas(context):
    db, _, jamaica, bahamas, _ = context
    _boundary(db, jamaica)
    _boundary(db, bahamas, -79, -73)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "jamaica-only", 18.0, -77.0)
    db.commit()
    observation = add_observation(db, bahamas, latitude=18.0, longitude=-77.0)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert result.occurrence_dataset_ids == ()
    assert result.historical_record_count == 0
    assert result.nearest_occurrence_distance_km is None


def test_region_evidence_requires_explicit_geographic_applicability(context):
    db, caribbean, jamaica, _, species = context
    _boundary(db, jamaica)
    other_region = Region(name="Other", slug="other")
    db.add(other_region)
    db.flush()
    matching = ScientificDataset(
        slug="matching-region", name="Matching", dataset_type="OCCURRENCE",
        species_id=species.id, geographic_scope_type="REGION", region_id=caribbean.id,
        source_name="Provider", source_version="v1", record_count=1,
    )
    incompatible = ScientificDataset(
        slug="other-region", name="Other", dataset_type="OCCURRENCE",
        species_id=species.id, geographic_scope_type="REGION", region_id=other_region.id,
        source_name="Provider", source_version="v1", record_count=1,
    )
    db.add_all([matching, incompatible]); db.flush()
    _occurrence(db, matching, "matching", 18.1, -77.1)
    _occurrence(db, incompatible, "incompatible", 18.2, -77.2)
    create_applicability(
        db, scientific_dataset_id=matching.id, jurisdiction_id=jamaica.id,
        evidence_role=EvidenceRole.GEOGRAPHIC_EVIDENCE,
        applicability_status=ApplicabilityStatus.AUTHORIZED,
        reconciliation_method="TEST", reconciliation_version="v1",
        provenance_reference="test", provenance={"assertion": "geographic"},
    )
    db.commit()
    observation = add_observation(db, jamaica)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert matching.id in result.occurrence_dataset_ids
    assert incompatible.id not in result.occurrence_dataset_ids


def test_unowned_dataset_is_excluded(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    unowned = ScientificDataset(
        slug="unowned", name="Unowned", dataset_type="OCCURRENCE",
        geographic_scope_type="JURISDICTION", jurisdiction_id=jamaica.id,
        source_name="Provider", source_version="v1", record_count=1,
    )
    db.add(unowned); db.flush()
    _occurrence(db, unowned, "unowned-record", 18.0, -77.0)
    db.commit()
    observation = add_observation(db, jamaica)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert unowned.id not in result.occurrence_dataset_ids


def test_duplicate_remains_non_independent(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    observation = add_observation(db, jamaica, is_possible_duplicate=True)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert result.duplicate_state == "POSSIBLE_DUPLICATE"
    assert result.contributes_independent_evidence is False


def test_unresolved_identity_is_safe(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    observation = add_observation(db, jamaica, identification_status="unresolved", species=None)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert result.evaluated_species is None
    assert result.evidence_availability == "UNRESOLVED_IDENTITY"
    assert result.occurrence_dataset_ids == ()
    assert result.nearest_occurrence_distance_km is None


def test_actual_boundary_membership_and_outside_records_are_reported(context):
    db, _, jamaica, _, _ = context
    boundary = _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "inside", 18.0, -77.0)
    _occurrence(db, dataset, "outside", 18.0, -74.0)
    db.commit()
    observation = add_observation(db, jamaica, latitude=18.0, longitude=-77.0)
    result = GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert result.jurisdiction_boundary_membership == "INSIDE_OR_ON_BOUNDARY"
    assert result.boundary_id == boundary.id
    assert result.records_inside_jurisdiction_boundary == 1
    assert result.records_outside_jurisdiction_boundary == 1
    assert result.historical_record_count == 2
    assert result.boundary_reconciliation_status == "RECORDS_OUTSIDE_BOUNDARY_PRESENT"


def test_fingerprint_deterministic_and_changes_with_evidence(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    dataset = _jamaica_dataset(db)
    _occurrence(db, dataset, "one", 18.0, -77.0)
    db.commit()
    observation = add_observation(db, jamaica)
    service = GeographicEvidenceService(db, 0.1)
    first = service.evaluate_observation(observation.id)
    assert service.evaluate_observation(observation.id).dependency_fingerprint == first.dependency_fingerprint
    _occurrence(db, dataset, "two", 18.2, -77.2)
    db.commit()
    assert service.evaluate_observation(observation.id).dependency_fingerprint != first.dependency_fingerprint


def test_no_anomaly_threshold_or_concentration_logic():
    import anomaly_geographic_evidence

    source = pyinspect.getsource(anomaly_geographic_evidence)
    for forbidden in (
        "GEOGRAPHIC_RANGE_ANOMALY", "overall_classification",
        "classify_historical_location_context", "occurrence_concentration",
        "<= 10", "<= 50", "ANOMALY_SIGNAL",
    ):
        assert forbidden not in source


def test_no_production_scientific_models_are_mutated(context):
    db, _, jamaica, _, _ = context
    _boundary(db, jamaica)
    observation = add_observation(db, jamaica)
    before = {
        "observation": (observation.species, observation.verification_status),
        "datasets": [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)],
        "deployments": [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)],
        "runs": [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)],
        "assessments": db.query(AnomalyAssessment).count(),
        "signals": db.query(AnomalySignal).count(),
    }
    GeographicEvidenceService(db, 0.1).evaluate_observation(observation.id)
    assert (observation.species, observation.verification_status) == before["observation"]
    assert [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)] == before["datasets"]
    assert [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == before["deployments"]
    assert [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)] == before["runs"]
    assert db.query(AnomalyAssessment).count() == before["assessments"]
    assert db.query(AnomalySignal).count() == before["signals"]
