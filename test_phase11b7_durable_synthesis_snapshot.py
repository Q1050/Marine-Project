"""Focused Phase 11B-7 durable synthesis snapshot tests."""

import hashlib
import inspect as pyinspect
import json
import sqlite3
from dataclasses import replace

import pytest

from anomaly_assessment_service import AnomalyAssessmentService
from anomaly_domain import AssessmentStatus
from anomaly_repository import canonical_json
from anomaly_signal_service import AnomalySignalService
from anomaly_synthesis_repository import AnomalySynthesisRepository
from anomaly_synthesis_service import AnomalySynthesisService
from models import (
    AnomalyAssessment,
    AnomalySignal,
    AnomalySynthesisSnapshot,
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
)
from phase11b7_migrate_synthesis_snapshot import run_migration
from test_phase11b2_evidence_readiness import add_observation, context


def _prepare(db, observation):
    AnomalyAssessmentService(db).assess_observation(observation.id)
    AnomalySignalService(db).generate_for_observation(observation.id)


def test_migration_schema_creation_and_idempotency(tmp_path):
    path = tmp_path / "phase11b7.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE protected_state (id INTEGER, value TEXT)")
        connection.execute("INSERT INTO protected_state VALUES (1, 'unchanged')")
        first = run_migration(connection)
        second = run_migration(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(anomaly_synthesis_snapshots)")}
        protected = connection.execute("SELECT * FROM protected_state").fetchall()
    assert first == {"anomaly_synthesis_snapshots_created": True}
    assert second == {"anomaly_synthesis_snapshots_created": False}
    assert {
        "anomaly_assessment_id", "observation_id", "jurisdiction_id",
        "synthesis_rules_version", "dependency_fingerprint",
        "synthesis_fingerprint", "overall_status", "overall_classification",
        "review_type", "assessment_confidence", "provenance_json",
        "limitations_json", "created_at",
    } <= columns
    assert protected == [(1, "unchanged")]


def test_snapshot_insert_idempotency_and_exact_fingerprint(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    service = AnomalySynthesisService(db)
    computed = service.synthesize_observation(observation.id)
    first = service.synthesize_and_persist(observation.id)
    second = service.synthesize_and_persist(observation.id)
    assert first.id == second.id
    assert db.query(AnomalySynthesisSnapshot).count() == 1
    assert first.synthesis_fingerprint == computed.synthesis_fingerprint
    assert hashlib.sha256(first.provenance_json.encode("utf-8")).hexdigest() == first.synthesis_fingerprint
    assert canonical_json(json.loads(first.provenance_json)) == first.provenance_json


def test_snapshot_is_immutable(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    snapshot = AnomalySynthesisService(db).synthesize_and_persist(observation.id)
    snapshot.overall_status = AssessmentStatus.ANOMALY_SIGNAL.value
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_prohibited_outcome_or_classification_rejected_by_repository(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    result = AnomalySynthesisService(db).synthesize_observation(observation.id)
    repository = AnomalySynthesisRepository(db)
    with pytest.raises(ValueError, match="Unauthorized"):
        repository.create_or_get_snapshot(replace(result, overall_status=AssessmentStatus.ANOMALY_SIGNAL.value))
    with pytest.raises(ValueError, match="NULL"):
        repository.create_or_get_snapshot(replace(result, overall_classification="EXPECTED"))
    assert db.query(AnomalySynthesisSnapshot).count() == 0


def test_jamaica_insufficient_evidence_persists_without_classification(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    snapshot = AnomalySynthesisService(db).synthesize_and_persist(observation.id)
    assert snapshot.overall_status == AssessmentStatus.INSUFFICIENT_EVIDENCE.value
    assert snapshot.overall_classification is None
    assert snapshot.jurisdiction_id == jamaica.id


def test_bahamas_not_configured_has_no_jamaica_provenance(context):
    db, _, _, bahamas, _ = context
    observation = add_observation(db, bahamas)
    _prepare(db, observation)
    snapshot = AnomalySynthesisService(db).synthesize_and_persist(observation.id)
    provenance = json.loads(snapshot.provenance_json)
    assert snapshot.overall_status == AssessmentStatus.NOT_CONFIGURED.value
    assert snapshot.overall_classification is None
    assert snapshot.jurisdiction_id == bahamas.id
    assert provenance["scientific_dataset_ids"] == []
    assert provenance["suitability_deployment_ids"] == []
    assert "jamaica" not in snapshot.provenance_json.lower()


def test_changed_assessment_creates_new_snapshot_and_preserves_history(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    service = AnomalySynthesisService(db)
    old_snapshot = service.synthesize_and_persist(observation.id)
    old_values = (
        old_snapshot.overall_status, old_snapshot.synthesis_fingerprint,
        old_snapshot.provenance_json, old_snapshot.limitations_json,
    )
    observation.verification_status = "CONFIRMED"
    observation.verified_species = "Pterois volitans"
    db.flush()
    AnomalyAssessmentService(db).assess_observation(observation.id)
    AnomalySignalService(db).generate_for_observation(observation.id)
    new_snapshot = service.synthesize_and_persist(observation.id)
    assert new_snapshot.id != old_snapshot.id
    assert new_snapshot.anomaly_assessment_id != old_snapshot.anomaly_assessment_id
    assert new_snapshot.synthesis_fingerprint != old_snapshot.synthesis_fingerprint
    assert (
        old_snapshot.overall_status, old_snapshot.synthesis_fingerprint,
        old_snapshot.provenance_json, old_snapshot.limitations_json,
    ) == old_values
    assert len(AnomalySynthesisRepository(db).list_snapshots_for_assessment(old_snapshot.anomaly_assessment_id)) == 1
    assert AnomalySynthesisRepository(db).get_latest_snapshot_for_observation(observation.id).id == new_snapshot.id


def test_refused_synthesis_attempt_is_not_persisted(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    AnomalyAssessmentService(db).assess_observation(observation.id)
    with pytest.raises(ValueError, match="signals are missing"):
        AnomalySynthesisService(db).synthesize_and_persist(observation.id)
    assert db.query(AnomalySynthesisSnapshot).count() == 0


def test_persistence_mutates_no_source_or_scientific_rows(context):
    db, _, jamaica, _, _ = context
    observation = add_observation(db, jamaica)
    _prepare(db, observation)
    assessment_before = [(x.id, x.overall_status, x.overall_classification, x.current_state) for x in db.query(AnomalyAssessment).order_by(AnomalyAssessment.id)]
    signals_before = [(x.id, x.signal_type, x.evidence_summary_json) for x in db.query(AnomalySignal).order_by(AnomalySignal.id)]
    observation_before = (observation.species, observation.verification_status, observation.score)
    datasets_before = [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)]
    deployments_before = [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)]
    runs_before = [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)]
    AnomalySynthesisService(db).synthesize_and_persist(observation.id)
    assert [(x.id, x.overall_status, x.overall_classification, x.current_state) for x in db.query(AnomalyAssessment).order_by(AnomalyAssessment.id)] == assessment_before
    assert [(x.id, x.signal_type, x.evidence_summary_json) for x in db.query(AnomalySignal).order_by(AnomalySignal.id)] == signals_before
    assert (observation.species, observation.verification_status, observation.score) == observation_before
    assert [(x.id, x.slug, x.record_count) for x in db.query(ScientificDataset).order_by(ScientificDataset.id)] == datasets_before
    assert [(x.id, x.model_version, x.artifact_hash) for x in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == deployments_before
    assert [(x.id, x.status) for x in db.query(TrainingRun).order_by(TrainingRun.id)] == runs_before


def test_generic_persistence_has_no_threshold_probability_or_place_species_constants():
    import anomaly_synthesis_repository
    import phase11b7_migrate_synthesis_snapshot

    source = (
        pyinspect.getsource(anomaly_synthesis_repository)
        + pyinspect.getsource(phase11b7_migrate_synthesis_snapshot)
    ).lower()
    for forbidden in (
        "jamaica", "bahamas", "pterois", "lionfish", "anomaly_probability",
        "distance_km", "suitability_score",
    ):
        assert forbidden not in source
