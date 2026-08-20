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

from api import get_jurisdiction_organizations, get_organization, get_organizations  # noqa: E402
from database import Base  # noqa: E402
from models import Jurisdiction, Organization, OrganizationJurisdiction, Region  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    session.add(region)
    session.flush()
    session.add_all([
        Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8),
        Jurisdiction(region_id=region.id, name="Test Island", slug="test-island", country_code="TI", status="ACTIVE", center_latitude=16, center_longitude=-60, default_zoom=8),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_organization(db, name="Example Research Group", slug="example-research", organization_type="RESEARCH_INSTITUTION"):
    organization = Organization(name=name, slug=slug, organization_type=organization_type, status="ACTIVE")
    db.add(organization)
    db.commit()
    return organization


def test_empty_registry_does_not_fabricate_organizations(db):
    assert get_organizations(db=db) == {"count": 0, "organizations": []}


def test_organization_type_status_and_slug_uniqueness(db):
    organization = add_organization(db)
    assert organization.organization_type == "RESEARCH_INSTITUTION"
    assert organization.status == "ACTIVE"
    db.add(Organization(name="Duplicate", slug=organization.slug, organization_type="OTHER", status="INACTIVE"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_multiple_organizations_can_participate_in_jamaica(db):
    jamaica = db.query(Jurisdiction).filter_by(slug="jamaica").one()
    first = add_organization(db)
    second = add_organization(db, "Example Fisheries", "example-fisheries", "FISHERIES_AUTHORITY")
    db.add_all([OrganizationJurisdiction(organization_id=first.id, jurisdiction_id=jamaica.id), OrganizationJurisdiction(organization_id=second.id, jurisdiction_id=jamaica.id)])
    db.commit()
    response = get_jurisdiction_organizations("caribbean", "jamaica", db=db)
    assert response["count"] == 2
    assert {item["slug"] for item in response["organizations"]} == {"example-research", "example-fisheries"}


def test_organization_can_participate_in_multiple_jurisdictions(db):
    organization = add_organization(db)
    jurisdictions = db.query(Jurisdiction).all()
    db.add_all([OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=item.id) for item in jurisdictions])
    db.commit()
    response = get_organization(organization.slug, db=db)
    assert {item["slug"] for item in response["jurisdictions"]} == {"jamaica", "test-island"}


def test_duplicate_organization_jurisdiction_is_prevented(db):
    organization = add_organization(db)
    jamaica = db.query(Jurisdiction).filter_by(slug="jamaica").one()
    db.add(OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=jamaica.id))
    db.commit()
    db.add(OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=jamaica.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_jamaica_endpoint_excludes_unlinked_organization(db):
    add_organization(db)
    response = get_jurisdiction_organizations("caribbean", "jamaica", db=db)
    assert response["count"] == 0


def test_unknown_organization_returns_404(db):
    with pytest.raises(HTTPException) as error:
        get_organization("unknown", db=db)
    assert error.value.status_code == 404
