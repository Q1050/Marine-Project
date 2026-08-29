import shutil
import sqlite3

import pytest
from fastapi import HTTPException

from auth_service import require_scientific_jurisdiction, scientific_reviewer_jurisdiction_ids
from early_warning_operations import EarlyWarningOperations
from early_warning_service import EarlyWarningService
from milestone13d_migrate_early_warning_operations import run_migration
from models import (
    AnomalyAssessment,
    AnomalyConfiguration,
    EcologicalStatusAssertion,
    GovernedOccurrenceEvidence,
    ScientificDomainEvent,
    ScientificReviewerGrant,
    User,
)
from test_milestone13c_early_warning import observation, seed


def config_values(jurisdiction_id, taxon_id, version="test-v1", spatial=None):
    return {
        "jurisdiction_id": jurisdiction_id,
        "taxon_id": taxon_id,
        "configuration_version": version,
        "enabled_signal_types_json": '["GEOGRAPHIC_CONTEXT"]' if spatial else "[]",
        "spatial_rule_json": None if spatial is None else f'{{"rule_id":"synthetic-spatial","rule_version":"test-v1","review_distance_km":{spatial}}}',
        "temporal_rule_json": None,
        "mode": "RULE_BASED" if spatial else "DESCRIPTIVE_ONLY",
        "environmental_context_json": "{}",
        "minimum_evidence_json": "{}",
        "algorithm_version": "marine-early-warning-v1",
        "provenance_json": '{"fixture":true}',
        "limitations_json": '["Synthetic test configuration only"]',
    }


def test_migration_twice_is_noop_and_preserves_production_counts(tmp_path):
    target = tmp_path / "copy.db"
    shutil.copy2("marine_observations.db", target)
    with sqlite3.connect(target) as connection:
        before = {table: connection.execute(f"select count(*) from {table}").fetchone()[0] for table in ("observations", "historical_occurrences", "governed_occurrence_evidence", "ecological_status_assertions")}
        first = run_migration(connection)
        second = run_migration(connection)
        after = {table: connection.execute(f"select count(*) from {table}").fetchone()[0] for table in before}
        assert set(first) == {"tables_created", "configuration_columns_added"}
        assert second == {"tables_created": [], "configuration_columns_added": []}
        assert before == after
    empty = tmp_path / "empty.db"
    with sqlite3.connect(empty) as connection:
        created = run_migration(connection)
        assert set(created["tables_created"]) >= {"scientific_reviewer_grants", "anomaly_review_assignments", "scientific_domain_events"}


def test_scientific_grant_is_jurisdiction_scoped_and_revocable():
    session, jurisdiction, _ = seed()
    reviewer = User(email="scientist@example.test", display_name="Scientist", password_hash="fixture")
    session.add(reviewer); session.flush()
    operations = EarlyWarningOperations(session)
    grant = operations.grant(reviewer.id, jurisdiction.id, reviewer.id, "fixture approval")
    assert scientific_reviewer_jurisdiction_ids(session, reviewer) == {jurisdiction.id}
    require_scientific_jurisdiction(session, reviewer, jurisdiction.id)
    with pytest.raises(HTTPException): require_scientific_jurisdiction(session, reviewer, jurisdiction.id + 100)
    operations.revoke(grant, reviewer.id)
    assert scientific_reviewer_jurisdiction_ids(session, reviewer) == set()


def test_configuration_lifecycle_descriptive_default_and_supersession():
    session, jurisdiction, taxon = seed(); operations = EarlyWarningOperations(session)
    first = operations.config_draft(config_values(jurisdiction.id, taxon.id))
    assert first.review_status == "DRAFT" and first.mode == "DESCRIPTIVE_ONLY" and not first.automatic_evaluation_enabled
    fingerprint = first.dependency_fingerprint
    operations.transition_config(first, "READY_FOR_REVIEW"); operations.transition_config(first, "APPROVED", 1, "fixture"); operations.transition_config(first, "ACTIVE")
    with pytest.raises(ValueError): operations.update_draft(first, {"limitations_json": "[]"})
    second = operations.config_draft(config_values(jurisdiction.id, taxon.id, "test-v2"))
    assert second.dependency_fingerprint != fingerprint
    operations.transition_config(second, "READY_FOR_REVIEW"); operations.transition_config(second, "APPROVED", 1, "fixture"); operations.transition_config(second, "ACTIVE")
    assert first.review_status == "SUPERSEDED" and second.supersedes_configuration_id == first.id


def test_test_only_spatial_rule_changes_review_recommendation():
    session, jurisdiction, taxon = seed()
    session.add(GovernedOccurrenceEvidence(preparation_id=1, candidate_record_id=1, scientific_dataset_id=1, jurisdiction_id=jurisdiction.id, taxon_id=taxon.id, latitude=1, longitude=1, boundary_id=1, evidence_fingerprint="e1", provenance_json="{}"))
    observed = observation(session, jurisdiction, taxon); observed.latitude = 3; observed.longitude = 3; session.flush()
    operations = EarlyWarningOperations(session); configuration = operations.config_draft(config_values(jurisdiction.id, taxon.id, spatial=10))
    operations.transition_config(configuration, "READY_FOR_REVIEW"); operations.transition_config(configuration, "APPROVED", 1, "synthetic-reviewed-rule"); operations.transition_config(configuration, "ACTIVE")
    assessment = EarlyWarningService(session).evaluate(observed.id)
    assert assessment.overall_status == "REVIEW_SUGGESTED"
    assert "explicitly reviewed" in EarlyWarningService(session).payload(assessment)["explanation"]


def test_event_idempotency_disabled_switch_and_enabled_fixture():
    session, jurisdiction, taxon = seed(); observed = observation(session, jurisdiction, taxon); operations = EarlyWarningOperations(session)
    first = operations.emit("OBSERVATION_EXPERT_VERIFIED", jurisdiction.id, taxon.id, observed.id, "verification-v1")
    assert operations.emit("OBSERVATION_EXPERT_VERIFIED", jurisdiction.id, taxon.id, observed.id, "verification-v1").id == first.id
    operations.process(first)
    assert first.processing_state == "SKIPPED" and session.query(AnomalyAssessment).count() == 0
    configuration = operations.config_draft(config_values(jurisdiction.id, taxon.id)); configuration.automatic_evaluation_enabled = True
    operations.transition_config(configuration, "READY_FOR_REVIEW"); operations.transition_config(configuration, "APPROVED", 1, "fixture"); operations.transition_config(configuration, "ACTIVE")
    enabled = operations.emit("OBSERVATION_EXPERT_VERIFIED", jurisdiction.id, taxon.id, observed.id, "verification-v2")
    operations.process(enabled)
    assert enabled.processing_state == "PROCESSED" and session.query(AnomalyAssessment).count() == 1
    assert session.query(GovernedOccurrenceEvidence).count() == 0 and session.query(EcologicalStatusAssertion).count() == 0


def test_scoped_invalidation_and_claim_history():
    session, jurisdiction, taxon = seed(); observed = observation(session, jurisdiction, taxon); assessment = EarlyWarningService(session).evaluate(observed.id)
    reviewer = User(email="claim@example.test", display_name="Claim Reviewer", password_hash="fixture"); session.add(reviewer); session.flush()
    operations = EarlyWarningOperations(session); assignment = operations.claim(assessment, reviewer.id, reviewer.id, "claim")
    assert operations.claim(assessment, reviewer.id, reviewer.id, "same claim").id == assignment.id
    assert operations.invalidate(jurisdiction.id, taxon.id, "baseline changed") == 1
    assert assessment.current_state == "STALE"
    assert session.query(ScientificDomainEvent).count() == 0
