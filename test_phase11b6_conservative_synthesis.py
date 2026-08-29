"""Focused Phase 11B-6 conservative synthesis-gate tests."""

import inspect as pyinspect
import json
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from anomaly_assessment_service import AnomalyAssessmentService
from anomaly_domain import AssessmentStatus, ReviewType
from anomaly_signal_service import AnomalySignalService
from anomaly_synthesis_service import (
    AUTHORIZED_STATUSES,
    AnomalySynthesisService,
)
from models import (
    AnomalyAssessment,
    AnomalySignal,
    HistoricalOccurrence,
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
)
from test_phase11b2_evidence_readiness import add_observation, context
from test_phase11b4_descriptive_signals import _add_grid_cell


def _prepare(db, observation):
    assessment = AnomalyAssessmentService(db).assess_observation(observation.id)
    signals = AnomalySignalService(db).generate_for_observation(observation.id)
    return assessment, signals


def _synthesize(db, observation):
    _prepare(db, observation)
    return AnomalySynthesisService(db).synthesize_observation(observation.id)


def test_unresolved_identity_routes_to_identification_review(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, identification_status="unresolved", species=None)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.REQUIRES_IDENTIFICATION_REVIEW.value
    assert result.requires_review is True
    assert result.review_type == ReviewType.IDENTIFICATION_REVIEW.value
    assert result.overall_classification is None


def test_duplicate_is_not_evaluated(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, is_possible_duplicate=True, duplicate_of_observation_id=7)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.NOT_EVALUATED.value
    assert result.review_type == ReviewType.NO_REVIEW.value
    assert result.overall_classification is None


def test_configured_descriptive_only_is_insufficient(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.INSUFFICIENT_EVIDENCE.value
    assert result.review_type == ReviewType.NO_REVIEW.value
    assert result.overall_classification is None


def test_unconfigured_jurisdiction_is_not_configured_without_leakage(context):
    db, _, _, bahamas, _ = context
    observation = add_observation(db, bahamas)
    result = _synthesize(db, observation)
    provenance = json.loads(result.provenance_json)
    assert result.overall_status == AssessmentStatus.NOT_CONFIGURED.value
    assert result.overall_classification is None
    assert provenance["scientific_dataset_ids"] == []
    assert provenance["suitability_deployment_ids"] == []
    assert "jamaica" not in result.provenance_json.lower()


def test_changed_dependency_refuses_stale_synthesis(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    observation.verification_status = "CONFIRMED"
    observation.verified_species = "Pterois volitans"
    db.flush()
    with pytest.raises(ValueError, match="stale"):
        AnomalySynthesisService(db).synthesize_observation(observation.id)
    assert db.query(AnomalyAssessment).one().current_state == "CURRENT"


@pytest.mark.parametrize("score,band", [(0.1, "VERY_LOW"), (0.9, "VERY_HIGH")])
def test_suitability_extremes_cannot_change_conservative_outcome(context, score, band):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _add_grid_cell(db, observation, score, band)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.INSUFFICIENT_EVIDENCE.value
    assert result.overall_classification is None


@pytest.mark.parametrize("historical_count", [0, 12])
def test_historical_count_cannot_trigger_novelty_or_expected(context, historical_count):
    db, _, jamaica, _, _ = context
    dataset = db.query(ScientificDataset).filter_by(slug="jamaica-occ").one()
    for index in range(historical_count):
        db.add(HistoricalOccurrence(
            scientific_name="Pterois volitans", taxon_id=1,
            latitude=18.0, longitude=-77.0, event_date=datetime(2010, 1, 1),
            source="OBIS", deduplication_key=f"history-{index}", dataset_id=dataset.id,
        ))
    db.commit()
    observation = add_observation(db, jamaica)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.INSUFFICIENT_EVIDENCE.value
    assert result.overall_classification is None


@pytest.mark.parametrize("score", [0.01, 0.99])
def test_ai_score_cannot_trigger_ecological_classification(context, score):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, score=score)
    result = _synthesize(db, observation)
    assert result.overall_status == AssessmentStatus.INSUFFICIENT_EVIDENCE.value
    assert result.overall_classification is None


def test_all_authorized_paths_have_null_classification_and_forbidden_unreachable(context):
    db, _, jamaica, bahamas, _ = context
    observations = [
        add_observation(db, jamaica),
        add_observation(db, jamaica, identification_status="unresolved", species=None),
        add_observation(db, jamaica, is_possible_duplicate=True),
        add_observation(db, bahamas),
    ]
    results = [_synthesize(db, observation) for observation in observations]
    assert all(result.overall_status in AUTHORIZED_STATUSES for result in results)
    assert all(result.overall_classification is None for result in results)
    assert not ({result.overall_status for result in results} & {
        AssessmentStatus.ANOMALY_SIGNAL.value,
        AssessmentStatus.NO_ANOMALY_DETECTED.value,
    })


def test_provenance_and_result_are_deterministic_idempotent_and_immutable(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    service = AnomalySynthesisService(db)
    first = service.synthesize_observation(observation.id)
    second = service.synthesize_observation(observation.id)
    assert first == second
    assert first.synthesis_fingerprint == second.synthesis_fingerprint
    provenance = json.loads(first.provenance_json)
    assert provenance["assessment_id"] == first.assessment_id
    assert len(provenance["consumed_signals"]) == 4
    assert provenance["classification_available"] is False
    with pytest.raises(FrozenInstanceError):
        first.overall_status = AssessmentStatus.ANOMALY_SIGNAL.value


def test_historical_assessment_and_signals_remain_immutable(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    assessment, signals = _prepare(db, observation)
    before = (
        assessment.overall_status, assessment.overall_classification,
        [(row.id, row.signal_type, row.evidence_summary_json) for row in signals],
    )
    AnomalySynthesisService(db).synthesize_observation(observation.id)
    after = (
        assessment.overall_status, assessment.overall_classification,
        [(row.id, row.signal_type, row.evidence_summary_json) for row in signals],
    )
    assert after == before


def test_no_protected_scientific_state_mutation(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    before_observation = (observation.species, observation.verification_status, observation.score)
    before_datasets = [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)]
    before_deployments = [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)]
    before_runs = [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)]
    AnomalySynthesisService(db).synthesize_observation(observation.id)
    assert (observation.species, observation.verification_status, observation.score) == before_observation
    assert [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)] == before_datasets
    assert [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == before_deployments
    assert [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)] == before_runs


def test_generic_execution_path_has_no_species_or_jurisdiction_constants_or_probability():
    import anomaly_synthesis_service

    source = pyinspect.getsource(anomaly_synthesis_service).lower()
    for forbidden in ("jamaica", "bahamas", "pterois", "lionfish", "anomaly_probability"):
        assert forbidden not in source
