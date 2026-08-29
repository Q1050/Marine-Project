from datetime import datetime, timezone
from pathlib import Path
import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    pass


# Importing the API normally initializes BioCLIP. These endpoint tests do not
# exercise inference, so keep model loading outside their scope.
service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _StubMarineObservationService
sys.modules["marine_observation_service"] = service_module

from api import (  # noqa: E402
    VerificationRequest,
    app,
    get_observation,
    get_review_queue,
    verify_observation,
)
from database import Base  # noqa: E402
from models import Jurisdiction, Observation, Region, User  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    session.add(region)
    session.flush()
    session.add(Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_observation(db, **overrides):
    values = {
        "jurisdiction_id": db.query(Jurisdiction).filter_by(slug="jamaica").one().id,
        "image_filename": "test-review.jpg",
        "latitude": 18.43,
        "longitude": -77.1,
        "identification_status": "accepted",
        "species": "Sparisoma viride",
        "nearest_candidate": None,
        "score": 0.91,
        "margin": 0.08,
        "candidates_json": "[]",
        "regional_evidence_json": None,
        "ecological_status": "NATIVE",
        "decision": "NORMAL_REGIONAL_RECORD",
        "priority": "LOW",
        "reason": "Test observation.",
        "verification_status": "PENDING",
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    observation = Observation(**values)
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


def platform_admin(db):
    user = User(email="admin@example.test", display_name="Admin", password_hash="not-used", status="ACTIVE", is_platform_admin=True)
    db.add(user)
    db.commit()
    return user


def test_observation_detail_is_self_contained(db):
    observation = add_observation(
        db,
        is_possible_duplicate=True,
        duplicate_of_observation_id=42,
    )

    result = get_observation(observation.id, db)

    # Private reporter media is intentionally omitted from ordinary detail
    # payloads and is available only through the authorized reviewer endpoint.
    assert result["observation"]["image_url"] is None
    assert result["is_possible_duplicate"] is True
    assert result["duplicate_of_observation_id"] == 42
    assert result["verification"]["verified_at"] is None


def test_review_queue_includes_required_cases_once(db):
    invasive = add_observation(
        db,
        species="Pterois volitans",
        ecological_status="INVASIVE",
        decision="KNOWN_INVASIVE_RECORD",
        priority="MONITOR",
    )
    unresolved = add_observation(
        db,
        identification_status="unresolved",
        species=None,
        nearest_candidate="Pterois volitans",
        ecological_status="UNKNOWN",
        decision="UNRESOLVED_IDENTIFICATION",
        priority="REVIEW",
    )
    high_priority = add_observation(
        db,
        decision="HIGH_PRIORITY_REVIEW",
        priority="HIGH",
    )
    add_observation(db)

    result = get_review_queue(db, current_user=platform_admin(db))
    ids = [item["id"] for item in result["queue"]]

    assert ids == [invasive.id, unresolved.id, high_priority.id]
    assert len(ids) == len(set(ids))


def test_verification_transitions_and_timestamp(db):
    reviewer = platform_admin(db)
    observation = add_observation(
        db,
        species="Pterois volitans",
        ecological_status="INVASIVE",
        decision="KNOWN_INVASIVE_RECORD",
        priority="MONITOR",
    )

    confirmed = verify_observation(
        observation.id,
        VerificationRequest(
            status="CONFIRMED",
            verified_species="Pterois volitans",
            notes="Image reviewed.",
        ),
        db,
        reviewer,
    )
    assert confirmed["verification"]["status"] == "CONFIRMED"
    assert confirmed["verification"]["verified_at"] is not None

    corrected = verify_observation(
        observation.id,
        VerificationRequest(
            status="CORRECTED",
            verified_species="Pterois miles",
        ),
        db,
        reviewer,
    )
    db.refresh(observation)
    assert corrected["verification"]["status"] == "CORRECTED"
    assert observation.verified_species == "Pterois miles"
    assert observation.verified_at is not None

    for status in ("NEEDS_MORE_REVIEW", "REJECTED"):
        result = verify_observation(
            observation.id,
            VerificationRequest(status=status),
            db,
            reviewer,
        )
        assert result["verification"]["status"] == status
        assert result["verification"]["verified_at"] is not None


def test_static_observation_image_route_does_not_expose_private_upload():
    uploads = Path("uploads/observations")
    image = next(uploads.iterdir(), None)
    if image is None:
        pytest.skip("No existing uploaded image is available for route check.")

    response = TestClient(app).get(
        f"/uploads/observations/{image.name}"
    )

    assert response.status_code == 404
