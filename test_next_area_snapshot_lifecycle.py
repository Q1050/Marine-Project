from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    HabitatSuitabilityV3GridCell,
    NextAreaSnapshotCell,
    NextAreaSnapshotGeneration,
    Observation,
)
import next_area_prediction_service as service_module
from next_area_prediction_service import (
    PREDICTION_VERSION,
    RegenerationInProgressError,
    SCORING_FORMULA,
    NextAreaPredictionService,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_grid(db):
    for identifier, latitude in (("170:-770", 17.05), ("171:-770", 17.15)):
        db.add(HabitatSuitabilityV3GridCell(
            scientific_name="Pterois volitans",
            model_version="pterois-volitans-suitability-v3",
            grid_cell_id=identifier,
            latitude=latitude,
            longitude=-76.95,
            grid_size=0.1,
            suitability_score=0.8,
            suitability_band="VERY_HIGH",
            prediction_status="SCORED",
            feature_values_json="{}",
            missing_features_json="[]",
        ))
    db.commit()


def add_observation(db, created_at, **overrides):
    values = {
        "image_filename": "evidence.jpg",
        "latitude": 18.43,
        "longitude": -77.1,
        "identification_status": "accepted",
        "species": "Pterois volitans",
        "ecological_status": "INVASIVE",
        "decision": "KNOWN_INVASIVE_RECORD",
        "priority": "MONITOR",
        "verification_status": "PENDING",
        "is_possible_duplicate": False,
        "created_at": created_at,
    }
    values.update(overrides)
    observation = Observation(**values)
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


def generate_baseline(db, now):
    add_grid(db)
    service = NextAreaPredictionService()
    result = service.regenerate(db, now=now)
    assert result["prediction_version"] == PREDICTION_VERSION
    return service, result


def test_no_relevant_changes_is_fresh(db):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    add_observation(db, now - timedelta(days=1))
    service, _ = generate_baseline(db, now)

    result = service.freshness(db, now=now + timedelta(hours=1))

    assert result["status"] == "FRESH"
    assert result["relevant_changes_since_generation"] == 0


def test_new_eligible_pterois_is_stale_but_unrelated_is_not(db):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    service, _ = generate_baseline(db, now)
    add_observation(
        db,
        now + timedelta(hours=1),
        species="Sparisoma viride",
        ecological_status="NATIVE",
    )
    assert service.freshness(db, now=now + timedelta(hours=2))["status"] == "FRESH"

    add_observation(db, now + timedelta(hours=2))
    result = service.freshness(db, now=now + timedelta(hours=3))
    assert result["status"] == "STALE"
    assert "NEW_ELIGIBLE_EVIDENCE" in result["reasons"]


def test_verification_and_duplicate_changes_are_stale(db):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    observation = add_observation(db, now - timedelta(days=1))
    service, _ = generate_baseline(db, now)
    observation.verification_status = "CONFIRMED"
    observation.verified_species = "Pterois volitans"
    observation.verified_at = now + timedelta(hours=1)
    db.commit()
    result = service.freshness(db, now=now + timedelta(hours=2))
    assert result["status"] == "STALE"
    assert "VERIFICATION_CHANGED" in result["reasons"]

    service.regenerate(db, now=now + timedelta(hours=3))
    observation.is_possible_duplicate = True
    db.commit()
    result = service.freshness(db, now=now + timedelta(hours=4))
    assert result["status"] == "STALE"
    assert "EVIDENCE_STATE_CHANGED" in result["reasons"]


def test_recency_boundary_marks_snapshot_stale(db):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    add_observation(db, now - timedelta(days=1))
    service, _ = generate_baseline(db, now)

    result = service.freshness(db, now=now + timedelta(days=7, hours=1))

    assert result["status"] == "STALE"
    assert "RECENCY_BUCKET_CHANGED" in result["reasons"]


def test_legacy_null_verified_at_is_unknown(db):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    add_observation(
        db,
        now - timedelta(days=1),
        verification_status="CONFIRMED",
        verified_species="Pterois volitans",
        verified_at=None,
    )
    db.add(NextAreaSnapshotGeneration(
        scientific_name="Pterois volitans",
        prediction_version=PREDICTION_VERSION,
        suitability_model_version="pterois-volitans-suitability-v3",
        status="ACTIVE",
        is_active=True,
        diagnostics_json="{}",
        evidence_state_json=None,
        started_at=now,
        generated_at=now,
        completed_at=now,
    ))
    db.commit()

    result = NextAreaPredictionService().freshness(db, now=now + timedelta(hours=1))

    assert result["status"] == "UNKNOWN"
    assert "LEGACY_VERIFICATION_TIMESTAMP_UNKNOWN" in result["reasons"]


def test_regeneration_replaces_atomically_and_preserves_method(db):
    first_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
    service, first = generate_baseline(db, first_time)
    second = service.regenerate(db, now=first_time + timedelta(hours=1))

    generations = db.query(NextAreaSnapshotGeneration).order_by(
        NextAreaSnapshotGeneration.id
    ).all()
    assert first["generation_id"] != second["generation_id"]
    assert sum(item.is_active for item in generations) == 1
    assert generations[0].status == "SUPERSEDED"
    assert generations[1].status == "ACTIVE"
    assert second["prediction_version"] == PREDICTION_VERSION
    assert second["scoring_formula"] == SCORING_FORMULA
    assert second["diagnostics"]["recommendation_cells"] == 2
    assert db.query(NextAreaSnapshotCell).filter(
        NextAreaSnapshotCell.generation_id == second["generation_id"]
    ).count() == 2


def test_failed_regeneration_preserves_active_snapshot(db, monkeypatch):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    service, original = generate_baseline(db, now)

    def fail_build(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(service, "_build_snapshot", fail_build)
    with pytest.raises(RuntimeError, match="test failure"):
        service.regenerate(db, now=now + timedelta(hours=1))

    active = service.summary(db)
    assert active["generation_id"] == original["generation_id"]
    assert db.query(NextAreaSnapshotGeneration).filter(
        NextAreaSnapshotGeneration.status == "FAILED"
    ).count() == 1


def test_repeated_request_protection(db):
    assert service_module._regeneration_lock.acquire(blocking=False)
    try:
        with pytest.raises(RegenerationInProgressError):
            NextAreaPredictionService().regenerate(db)
    finally:
        service_module._regeneration_lock.release()
