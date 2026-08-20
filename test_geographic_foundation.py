from datetime import datetime, timezone
import sys
import types

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    pass


service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _StubMarineObservationService
sys.modules.setdefault("marine_observation_service", service_module)

from api import (  # noqa: E402
    get_jurisdiction,
    get_region,
    get_region_jurisdictions,
    get_regions,
    get_review_queue,
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
    jamaica = Jurisdiction(
        region_id=region.id,
        name="Jamaica",
        slug="jamaica",
        country_code="JM",
        status="ACTIVE",
        center_latitude=18.1096,
        center_longitude=-77.2975,
        default_zoom=8,
    )
    session.add(jamaica)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _review_observation(jurisdiction_id):
    return Observation(
        jurisdiction_id=jurisdiction_id,
        image_filename="review.jpg",
        latitude=18.43,
        longitude=-77.1,
        identification_status="accepted",
        species="Pterois volitans",
        ecological_status="INVASIVE",
        decision="KNOWN_INVASIVE_RECORD",
        priority="HIGH",
        verification_status="PENDING",
        created_at=datetime.now(timezone.utc),
    )


def test_caribbean_and_jamaica_configuration(db):
    regions = get_regions(db=db)
    assert regions["count"] == 1
    assert regions["regions"][0]["slug"] == "caribbean"
    region = get_region("caribbean", db=db)
    assert region["name"] == "Caribbean"
    jurisdictions = get_region_jurisdictions("caribbean", db=db)
    assert jurisdictions["count"] == 1
    jamaica = get_jurisdiction("caribbean", "jamaica", db=db)
    assert jamaica["country_code"] == "JM"
    assert jamaica["region"]["slug"] == "caribbean"


def test_region_slug_is_unique(db):
    db.add(Region(name="Duplicate", slug="caribbean", status="ACTIVE"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_jamaica_review_queue_scope_preserves_eligibility(db):
    jamaica = db.query(Jurisdiction).filter_by(slug="jamaica").one()
    db.add(_review_observation(jamaica.id))
    admin = User(email="admin@example.test", display_name="Admin", password_hash="unused", status="ACTIVE", is_platform_admin=True)
    db.add(admin)
    db.commit()
    result = get_review_queue(
        region_slug="caribbean",
        jurisdiction_slug="jamaica",
        current_user=admin,
        db=db,
    )
    assert result["count"] == 1
    assert result["queue"][0]["jurisdiction"] == "jamaica"


@pytest.mark.parametrize(
    ("call", "detail"),
    [
        (lambda db: get_region("unknown", db=db), "Region not found."),
        (
            lambda db: get_jurisdiction("caribbean", "unknown", db=db),
            "Jurisdiction not found.",
        ),
    ],
)
def test_unknown_geography_returns_404(db, call, detail):
    with pytest.raises(HTTPException) as error:
        call(db)
    assert error.value.status_code == 404
    assert error.value.detail == detail
