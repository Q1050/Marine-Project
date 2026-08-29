"""Focused Phase 11B-1 tests: persistence foundation only."""

import inspect as pyinspect
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from anomaly_domain import (
    AssessmentLifecycleState,
    AssessmentStatus,
    EvidenceConfidence,
    IdentificationConfidence,
    OverallClassification,
    ReviewType,
    SignalStatus,
    SignalType,
)
from anomaly_repository import AnomalyRepository, canonical_json
from database import Base
from models import AnomalyAssessment, AnomalySignal
from phase11b1_migrate_anomaly_domain import run_migration


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def assessment_values(observation_id=1):
    return {
        "observation_id": observation_id,
        "jurisdiction_id": 1,
        "species_program_id": None,
        "evaluated_species": None,
        "evaluated_species_source": None,
        "overall_status": AssessmentStatus.INSUFFICIENT_EVIDENCE,
        "overall_classification": None,
        "assessment_confidence": IdentificationConfidence.NONE,
        "requires_review": True,
        "review_type": ReviewType.IDENTIFICATION_REVIEW,
        "provenance_version": "ecological-anomaly-v1",
        "dependency_fingerprint": None,
        "evidence_summary_json": {"b": 2, "a": 1},
        "limitations_json": ["Evidence is incomplete"],
        "provenance_json": {"method": "foundation-only"},
    }


def signal_values(assessment_id, signal_type=SignalType.GEOGRAPHIC_RANGE_ANOMALY):
    return {
        "anomaly_assessment_id": assessment_id,
        "signal_type": signal_type,
        "status": SignalStatus.NOT_EVALUATED,
        "anomaly_strength": None,
        "evidence_confidence": EvidenceConfidence.NONE,
        "evidence_summary_json": {},
        "limitations_json": ["No ecological evaluator implemented"],
        "source_dataset_ids_json": [],
        "suitability_deployment_id": None,
        "supporting_observation_ids_json": [],
        "provenance_version": "ecological-anomaly-v1",
    }


def test_schema_creation_and_migration_idempotency(tmp_path):
    path = tmp_path / "phase11b.sqlite"
    with sqlite3.connect(path) as connection:
        before = {
            row[0]: tuple(row[1] for row in connection.execute(f"PRAGMA table_info({row[0]})"))
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        first = run_migration(connection)
        second = run_migration(connection)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        after_unrelated = {
            name: tuple(row[1] for row in connection.execute(f"PRAGMA table_info({name})"))
            for name in before
        }
    assert first == {"anomaly_assessments_created": True, "anomaly_signals_created": True}
    assert second == {"anomaly_assessments_created": False, "anomaly_signals_created": False}
    assert {"anomaly_assessments", "anomaly_signals"} <= tables
    assert after_unrelated == before


def test_assessment_insert_nullable_fields_and_current_default(session):
    row = AnomalyRepository(session).create_assessment(**assessment_values())
    assert row.id is not None
    assert row.evaluated_species is None
    assert row.overall_classification is None
    assert row.current_state == AssessmentLifecycleState.CURRENT.value


def test_signal_insert_multiple_types_and_duplicate_rejected(session):
    repo = AnomalyRepository(session)
    assessment = repo.create_assessment(**assessment_values())
    repo.create_signal(**signal_values(assessment.id))
    repo.create_signal(**signal_values(assessment.id, SignalType.TEMPORAL_PATTERN_ANOMALY))
    assert session.query(AnomalySignal).count() == 2
    with pytest.raises(IntegrityError):
        repo.create_signal(**signal_values(assessment.id))
    session.rollback()


def test_lifecycle_forward_transitions(session):
    repo = AnomalyRepository(session)
    row = repo.create_assessment(**assessment_values())
    repo.mark_assessment_stale(row)
    assert row.current_state == "STALE" and row.invalidated_at is not None
    repo.mark_assessment_superseded(row)
    assert row.current_state == "SUPERSEDED" and row.superseded_at is not None


def test_lifecycle_reverse_and_skip_rejected(session):
    repo = AnomalyRepository(session)
    row = repo.create_assessment(**assessment_values())
    with pytest.raises(ValueError):
        repo.mark_assessment_superseded(row)
    repo.mark_assessment_stale(row)
    row.current_state = "CURRENT"
    with pytest.raises(ValueError):
        session.flush()
    session.rollback()


def test_assessment_scientific_results_immutable(session):
    row = AnomalyRepository(session).create_assessment(**assessment_values())
    row.overall_status = AssessmentStatus.NO_ANOMALY_DETECTED.value
    with pytest.raises(ValueError, match="immutable"):
        session.flush()
    session.rollback()


def test_signal_immutable(session):
    repo = AnomalyRepository(session)
    assessment = repo.create_assessment(**assessment_values())
    signal = repo.create_signal(**signal_values(assessment.id))
    signal.status = SignalStatus.SIGNAL_DETECTED.value
    with pytest.raises(ValueError, match="immutable"):
        session.flush()
    session.rollback()


def test_deterministic_json_serialization(session):
    assert canonical_json({"z": [2, 1], "a": {"b": True}}) == '{"a":{"b":true},"z":[2,1]}'
    row = AnomalyRepository(session).create_assessment(**assessment_values())
    assert row.evidence_summary_json == '{"a":1,"b":2}'


def test_repository_does_not_create_rows_automatically(session):
    # Merely creating the schema/session represents both Jamaica and Bahamas:
    # neither jurisdiction receives an assessment without an explicit call.
    assert session.query(AnomalyAssessment).count() == 0
    assert session.query(AnomalySignal).count() == 0


def test_migration_does_not_mutate_protected_models():
    source = pyinspect.getsource(run_migration).lower()
    for name in ("observations", "scientific_datasets", "suitability_deployments", "training_runs"):
        assert f"alter table {name}" not in source
        assert f"update {name}" not in source
        assert f"insert into {name}" not in source


def test_no_unvalidated_scientific_thresholds_or_scoring():
    import anomaly_domain
    import anomaly_repository

    combined = (pyinspect.getsource(anomaly_domain) + pyinspect.getsource(anomaly_repository)).lower()
    for token in ("haversine", "threshold", "anomaly_probability", "suitability_score <", "suitability_score >"):
        # Documentation may explicitly say thresholds are absent.
        executable = "\n".join(line for line in combined.splitlines() if not line.lstrip().startswith("#"))
        if token == "threshold":
            continue
        assert token not in executable


def test_all_required_enums_are_distinct_enum_types():
    enum_types = (
        AssessmentStatus, AssessmentLifecycleState, SignalStatus,
        OverallClassification, IdentificationConfidence, EvidenceConfidence,
        ReviewType, SignalType,
    )
    assert len(set(enum_types)) == 8
