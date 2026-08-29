"""Focused Phase 11B-3 readiness snapshot orchestration tests."""

import inspect as pyinspect
import json

import pytest

from anomaly_assessment_service import AnomalyAssessmentService
from anomaly_domain import AssessmentStatus, ReviewType
from anomaly_evidence_readiness import EvidenceReadinessResolver
from models import (
    AnomalyAssessment,
    AnomalySignal,
    Observation,
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
)
from test_phase11b2_evidence_readiness import add_observation, context


def test_unresolved_creates_identification_review_snapshot(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, identification_status="unresolved", species=None)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    assert row.overall_status == AssessmentStatus.REQUIRES_IDENTIFICATION_REVIEW.value
    assert row.requires_review is True
    assert row.review_type == ReviewType.IDENTIFICATION_REVIEW.value
    assert row.overall_classification is None


def test_duplicate_creates_not_evaluated_without_signals(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica, is_possible_duplicate=True)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    assert row.overall_status == AssessmentStatus.NOT_EVALUATED.value
    assert row.requires_review is False
    assert db.query(AnomalySignal).count() == 0


def test_jamaica_persists_complete_readiness_without_ecological_conclusion(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    readiness = EvidenceReadinessResolver(db).resolve(observation)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    assert row.overall_status == AssessmentStatus.NOT_EVALUATED.value
    assert row.overall_classification is None
    assert row.species_program_id is not None
    assert row.dependency_fingerprint == readiness.dependency_fingerprint
    assert db.query(AnomalySignal).count() == 0


def test_bahamas_not_configured_and_contains_no_jamaica_provenance(context):
    db, _, _, bahamas, _ = context
    observation = add_observation(db, bahamas)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    provenance = json.loads(row.provenance_json)
    assert row.overall_status == AssessmentStatus.NOT_CONFIGURED.value
    assert row.species_program_id is None
    assert provenance["jurisdiction_id"] == bahamas.id
    assert provenance["scientific_datasets"] == []
    assert provenance["suitability_deployment"] is None
    assert "jamaica" not in row.provenance_json.lower()


def test_region_evidence_alone_does_not_configure_bahamas(context):
    db, region, _, bahamas, species = context
    db.add(ScientificDataset(
        slug="regional-occurrence", name="Regional occurrence",
        dataset_type="OCCURRENCE", species_id=species.id,
        geographic_scope_type="REGION", region_id=region.id,
        source_name="OBIS", source_version="regional-v1", record_count=10,
    ))
    db.commit()
    observation = add_observation(db, bahamas)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    assert row.overall_status == AssessmentStatus.NOT_CONFIGURED.value
    assert row.species_program_id is None


def test_identical_fingerprint_reuses_only_current_snapshot(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    service = AnomalyAssessmentService(db)
    first = service.assess_observation(observation.id)
    second = service.assess_observation(observation.id)
    assert second.id == first.id
    assert db.query(AnomalyAssessment).count() == 1
    assert db.query(AnomalyAssessment).filter_by(current_state="CURRENT").count() == 1


def test_changed_verification_replaces_and_supersedes_old_snapshot(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    service = AnomalyAssessmentService(db)
    old = service.assess_observation(observation.id)
    old_fingerprint = old.dependency_fingerprint
    observation.verification_status = "CONFIRMED"
    observation.verified_species = "Pterois volitans"
    db.flush()
    new = service.assess_observation(observation.id)
    assert new.id != old.id
    assert new.dependency_fingerprint != old_fingerprint
    assert old.current_state == "SUPERSEDED"
    assert old.invalidated_at is not None
    assert old.superseded_at is not None
    assert new.current_state == "CURRENT"
    assert db.query(AnomalyAssessment).filter_by(current_state="CURRENT").count() == 1


def test_failed_replacement_leaves_old_stale(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    service = AnomalyAssessmentService(db)
    old = service.assess_observation(observation.id)
    observation.verification_status = "CONFIRMED"
    observation.verified_species = "Pterois volitans"
    db.flush()

    class FailingService(AnomalyAssessmentService):
        def _persist_snapshot(self, observation, readiness):
            assert old.current_state == "STALE"
            raise RuntimeError("controlled replacement failure")

    with pytest.raises(RuntimeError, match="controlled"):
        FailingService(db).assess_observation(observation.id)
    assert old.current_state == "STALE"
    assert old.invalidated_at is not None
    assert old.superseded_at is None
    assert db.query(AnomalyAssessment).count() == 1


def test_historical_scientific_fields_remain_immutable(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    row.overall_status = AssessmentStatus.ANOMALY_SIGNAL.value
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_no_authorized_ecological_outcomes_or_signals(context):
    db, _, jamaica, bahamas, _ = context
    observations = [
        add_observation(db, jamaica),
        add_observation(db, jamaica, identification_status="unresolved", species=None),
        add_observation(db, jamaica, is_possible_duplicate=True),
        add_observation(db, bahamas),
    ]
    service = AnomalyAssessmentService(db)
    rows = [service.assess_observation(item.id) for item in observations]
    forbidden = {
        AssessmentStatus.ANOMALY_SIGNAL.value,
        AssessmentStatus.NO_ANOMALY_DETECTED.value,
    }
    assert not ({row.overall_status for row in rows} & forbidden)
    assert all(row.overall_classification is None for row in rows)
    assert db.query(AnomalySignal).count() == 0


def test_service_mutates_no_input_or_protected_scientific_state(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    before_observation = (
        observation.species, observation.verification_status,
        observation.is_possible_duplicate, observation.duplicate_of_observation_id,
    )
    before_datasets = [(x.id, x.slug, x.record_count, x.artifact_sha256) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)]
    before_deployments = [(x.id, x.model_version, x.artifact_hash, x.status) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)]
    before_training = [(x.id, x.status, x.artifact_sha256) for x in db.query(TrainingRun).order_by(TrainingRun.id)]
    AnomalyAssessmentService(db).assess_observation(observation.id)
    assert (
        observation.species, observation.verification_status,
        observation.is_possible_duplicate, observation.duplicate_of_observation_id,
    ) == before_observation
    assert [(x.id, x.slug, x.record_count, x.artifact_sha256) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)] == before_datasets
    assert [(x.id, x.model_version, x.artifact_hash, x.status) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == before_deployments
    assert [(x.id, x.status, x.artifact_sha256) for x in db.query(TrainingRun).order_by(TrainingRun.id)] == before_training


def test_provenance_is_structured_and_deterministic(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    row = AnomalyAssessmentService(db).assess_observation(observation.id)
    provenance = json.loads(row.provenance_json)
    assert provenance["dependency_fingerprint"] == row.dependency_fingerprint
    assert provenance["identity_source"] == "ACCEPTED_AI"
    assert provenance["scientific_datasets"][0]["jurisdiction_id"] == jamaica.id
    assert "reasoning" not in provenance
    assert "credential" not in row.provenance_json.lower()


def test_service_contains_no_scoring_thresholds_or_probabilities():
    import anomaly_assessment_service

    source = pyinspect.getsource(anomaly_assessment_service)
    assert "anomaly_probability" not in source
    assert "suitability_score" not in source
    assert "distance_km" not in source
    assert "create_signal" not in source
