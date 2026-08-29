"""Focused Phase 11B-4 descriptive signal tests."""

import inspect as pyinspect
import json
from datetime import datetime, timezone

import pytest

from anomaly_assessment_service import AnomalyAssessmentService
from anomaly_domain import AssessmentStatus, SignalType
from anomaly_signal_service import AnomalySignalService
from models import (
    AnomalySignal,
    HabitatSuitabilityV3GridCell,
    HistoricalOccurrence,
    Observation,
    ScientificDataset,
    ScientificDatasetDeployment,
    SuitabilityDeployment,
    TrainingRun,
)
from test_phase11b2_evidence_readiness import add_observation, context


def _signals(db, observation):
    assessment = AnomalyAssessmentService(db).assess_observation(observation.id)
    rows = AnomalySignalService(db).generate_for_observation(observation.id)
    return assessment, {row.signal_type: row for row in rows}


def _add_grid_cell(db, observation, score, band):
    deployment = db.query(SuitabilityDeployment).one()
    identifier = AnomalySignalService._grid_cell_id(observation.latitude, observation.longitude)
    db.add(HabitatSuitabilityV3GridCell(
        suitability_deployment_id=deployment.id,
        scientific_name="Pterois volitans", model_version=deployment.model_version,
        grid_cell_id=identifier, latitude=observation.latitude,
        longitude=observation.longitude, grid_size=0.1,
        suitability_score=score, suitability_band=band,
        prediction_status="SCORED", feature_values_json="{}",
        missing_features_json="[]",
    ))
    dataset = db.query(ScientificDataset).filter_by(slug="jamaica-occ").one()
    db.add(ScientificDatasetDeployment(
        scientific_dataset_id=dataset.id,
        suitability_deployment_id=deployment.id,
        role="TRAINING_OCCURRENCES",
    ))
    db.commit()


def _evidence(signal):
    return json.loads(signal.evidence_summary_json)["evidence"]


@pytest.mark.parametrize("score,band", [(0.1, "VERY_LOW"), (0.9, "VERY_HIGH")])
def test_habitat_uses_persisted_score_band_without_interpretation(context, score, band):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _add_grid_cell(db, observation, score, band)
    assessment, signals = _signals(db, observation)
    signal = signals[SignalType.HABITAT_SUITABILITY_CONTEXT.value]
    evidence = _evidence(signal)
    assert evidence["suitability_score"] == score
    assert evidence["suitability_band"] == band
    assert signal.anomaly_strength is None
    assert assessment.overall_classification is None
    assert assessment.overall_status == AssessmentStatus.NOT_EVALUATED.value


def test_historical_context_uses_only_compatible_records_and_count_is_descriptive(context):
    db, _, jamaica, _, _ = context
    dataset = db.query(ScientificDataset).filter_by(slug="jamaica-occ").one()
    db.add_all([
        HistoricalOccurrence(scientific_name="Pterois volitans", taxon_id=1, latitude=18.1, longitude=-77.1, event_date=datetime(2010, 1, 1), source="OBIS", deduplication_key="one", dataset_id=dataset.id),
        HistoricalOccurrence(scientific_name="Pterois volitans", taxon_id=1, latitude=18.2, longitude=-77.2, event_date=datetime(2020, 1, 1), source="OBIS", deduplication_key="two", dataset_id=dataset.id),
    ])
    db.commit()
    observation = add_observation(db, jamaica)
    assessment, signals = _signals(db, observation)
    signal = signals[SignalType.HISTORICAL_OCCURRENCE_CONTEXT.value]
    evidence = _evidence(signal)
    assert evidence["record_count"] == 2
    assert evidence["earliest_record"].startswith("2010-01-01")
    assert evidence["latest_record"].startswith("2020-01-01")
    assert evidence["current_observation_representation"] == "UNKNOWN"
    assert signal.anomaly_strength is None
    assert assessment.overall_classification is None


def test_zero_occurrence_rows_is_not_anomaly_conclusion(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    assessment, signals = _signals(db, observation)
    evidence = _evidence(signals[SignalType.HISTORICAL_OCCURRENCE_CONTEXT.value])
    assert evidence["record_count"] == 0
    assert assessment.overall_status not in {
        AssessmentStatus.ANOMALY_SIGNAL.value,
        AssessmentStatus.NO_ANOMALY_DETECTED.value,
    }
    assert assessment.overall_classification is None


def test_identification_context_preserves_expert_precedence(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(
        db, jamaica, species="AI species", score=0.99,
        verification_status="CORRECTED", verified_species="Pterois volitans",
    )
    _, signals = _signals(db, observation)
    signal = signals[SignalType.IDENTIFICATION_CONTEXT.value]
    evidence = _evidence(signal)
    assert evidence["evaluated_species"] == "Pterois volitans"
    assert evidence["identity_source"] == "EXPERT_VERIFIED"
    assert evidence["accepted_ai_identity"] is None
    assert evidence["ai_score"] == 0.99
    assert signal.anomaly_strength is None


def test_duplicate_context_is_not_independent_evidence(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, is_possible_duplicate=True, duplicate_of_observation_id=42)
    _, signals = _signals(db, observation)
    signal = signals[SignalType.DUPLICATE_CONTEXT.value]
    evidence = _evidence(signal)
    assert evidence["duplicate_of_observation_id"] == 42
    assert evidence["contributes_independent_evidence"] is False
    assert json.loads(signal.supporting_observation_ids_json) == [42]
    assert signal.anomaly_strength is None


def test_bahamas_cannot_inherit_jamaica_occurrence_or_suitability(context):
    db, _, _, bahamas, _ = context
    observation = add_observation(db, bahamas)
    assessment, signals = _signals(db, observation)
    historical = _evidence(signals[SignalType.HISTORICAL_OCCURRENCE_CONTEXT.value])
    habitat = _evidence(signals[SignalType.HABITAT_SUITABILITY_CONTEXT.value])
    assert assessment.overall_status == AssessmentStatus.NOT_CONFIGURED.value
    assert historical["scientific_dataset_ids"] == []
    assert historical["record_count"] == 0
    assert habitat["deployment_id"] is None
    assert habitat["suitability_score"] is None


def test_explicit_region_owned_occurrence_is_compatible(context):
    db, region, _, bahamas, species = context
    dataset = ScientificDataset(
        slug="caribbean-occ", name="Caribbean occurrence", dataset_type="OCCURRENCE",
        species_id=species.id, geographic_scope_type="REGION", region_id=region.id,
        source_name="OBIS", source_version="v1", record_count=1,
    )
    db.add(dataset)
    db.flush()
    # Region ownership alone is no longer jurisdiction authorization. Preserve
    # the original signal assertion with an explicit role-scoped applicability.
    from scientific_dataset_applicability import create_applicability
    create_applicability(
        db, scientific_dataset_id=dataset.id, jurisdiction_id=bahamas.id,
        evidence_role="OCCURRENCE_HISTORY", applicability_status="AUTHORIZED",
        reconciliation_method="TEST_FIXTURE_REVIEW", reconciliation_version="13B",
        provenance_reference="test://phase11b4/region-occurrence",
        provenance={"fixture": "explicit Bahamas occurrence authorization"},
        approved_by="test", approved_at=datetime.now(timezone.utc),
    )
    db.add(HistoricalOccurrence(
        scientific_name="Pterois volitans", taxon_id=1, latitude=20, longitude=-76,
        event_date=datetime(2015, 1, 1), source="OBIS", deduplication_key="regional",
        dataset_id=dataset.id,
    ))
    db.commit()
    observation = add_observation(db, bahamas)
    _, signals = _signals(db, observation)
    evidence = _evidence(signals[SignalType.HISTORICAL_OCCURRENCE_CONTEXT.value])
    assert evidence["scientific_dataset_ids"] == [dataset.id]
    assert evidence["record_count"] == 1


def test_generation_is_idempotent_and_provenance_deterministic(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    AnomalyAssessmentService(db).assess_observation(observation.id)
    service = AnomalySignalService(db)
    first = service.generate_for_observation(observation.id)
    snapshots = [(row.id, row.signal_type, row.evidence_summary_json) for row in first]
    second = service.generate_for_observation(observation.id)
    assert [(row.id, row.signal_type, row.evidence_summary_json) for row in second] == snapshots
    assert db.query(AnomalySignal).count() == 4


def test_signal_rows_remain_immutable(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _, signals = _signals(db, observation)
    signal = signals[SignalType.IDENTIFICATION_CONTEXT.value]
    signal.anomaly_strength = "HIGH"
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_generation_mutates_no_protected_source_state(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    before_observation = (observation.species, observation.verification_status, observation.score)
    before_datasets = [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)]
    before_deployments = [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)]
    before_runs = [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)]
    _signals(db, observation)
    assert (observation.species, observation.verification_status, observation.score) == before_observation
    assert [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)] == before_datasets
    assert [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == before_deployments
    assert [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)] == before_runs


def test_no_distance_threshold_probability_or_final_conclusion_logic():
    import anomaly_signal_service

    source = pyinspect.getsource(anomaly_signal_service)
    assert "distance_km" not in source
    assert "anomaly_probability" not in source
    assert "OverallClassification" not in source
    assert "ANOMALY_SIGNAL" not in source
    assert "NO_ANOMALY_DETECTED" not in source
