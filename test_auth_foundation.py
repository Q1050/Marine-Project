from datetime import datetime, timezone
import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    pass


service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _StubMarineObservationService
sys.modules.setdefault("marine_observation_service", service_module)

import api  # noqa: E402
from auth_service import hash_password, jurisdiction_roles  # noqa: E402
from database import Base, get_db  # noqa: E402
from models import HabitatSuitabilityModel, Jurisdiction, NextAreaSnapshotGeneration, Observation, Organization, OrganizationJurisdiction, OrganizationMembership, Region, SpeciesProgram, SuitabilityDeployment, User  # noqa: E402


@pytest.fixture
def environment():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    db.add(region); db.flush()
    jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8)
    other = Jurisdiction(region_id=region.id, name="Test Island", slug="test-island", country_code="TI", status="ACTIVE", center_latitude=16, center_longitude=-60, default_zoom=8)
    db.add_all([jamaica, other]); db.commit()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_db] = override_db
    client = TestClient(api.app)
    try:
        yield db, client, jamaica, other
    finally:
        api.app.dependency_overrides.clear()
        db.close(); engine.dispose()


def add_user(db, email, role=None, jurisdiction=None, user_status="ACTIVE", organization_status="ACTIVE", membership_status="ACTIVE", link_status="ACTIVE", platform_admin=False):
    user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password("correct-password"), status=user_status, is_platform_admin=platform_admin)
    db.add(user); db.flush()
    if role:
        organization = Organization(name=f"Org {email}", slug=f"org-{user.id}", organization_type="OTHER", status=organization_status)
        db.add(organization); db.flush()
        db.add(OrganizationMembership(user_id=user.id, organization_id=organization.id, role=role, status=membership_status))
        if jurisdiction:
            db.add(OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=jurisdiction.id, status=link_status))
    db.commit()
    return user


def token(client, email, password="correct-password"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response


def auth_header(client, email):
    return {"Authorization": f"Bearer {token(client, email).json()['access_token']}"}


def add_observation(db, jurisdiction):
    observation = Observation(jurisdiction_id=jurisdiction.id, image_filename="test.jpg", latitude=18.4, longitude=-77.1, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc))
    db.add(observation); db.commit()
    return observation


def test_authentication_and_me_do_not_expose_hash(environment):
    db, client, jamaica, _ = environment
    add_user(db, "reviewer@example.test", "REVIEWER", jamaica)
    success = token(client, "reviewer@example.test")
    assert success.status_code == 200
    assert "password_hash" not in str(success.json())
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {success.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["authorized_jurisdictions"][0]["slug"] == "jamaica"
    assert token(client, "reviewer@example.test", "wrong-password").status_code == 401
    add_user(db, "inactive@example.test", user_status="INACTIVE")
    assert token(client, "inactive@example.test").status_code == 401


def test_membership_uniqueness_and_multi_organization(environment):
    db, _, jamaica, _ = environment
    user = add_user(db, "member@example.test", "VIEWER", jamaica)
    second = Organization(name="Second", slug="second", organization_type="OTHER", status="ACTIVE")
    db.add(second); db.flush()
    db.add(OrganizationMembership(user_id=user.id, organization_id=second.id, role="REVIEWER", status="ACTIVE")); db.commit()
    assert len(user.memberships) == 2
    db.add(OrganizationMembership(user_id=user.id, organization_id=second.id, role="VIEWER", status="ACTIVE"))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


@pytest.mark.parametrize("kwargs", [{"membership_status": "INACTIVE"}, {"organization_status": "INACTIVE"}, {"link_status": "INACTIVE"}])
def test_inactive_access_chain_grants_no_access(environment, kwargs):
    db, _, jamaica, _ = environment
    user = add_user(db, f"inactive-chain-{list(kwargs)[0]}@example.test", "REVIEWER", jamaica, **kwargs)
    assert jurisdiction_roles(db, user, jamaica.id) == set()


def test_verification_authorization_and_provenance(environment):
    db, client, jamaica, other = environment
    observation = add_observation(db, jamaica)
    viewer = add_user(db, "viewer@example.test", "VIEWER", jamaica)
    reviewer = add_user(db, "reviewer@example.test", "REVIEWER", jamaica)
    outsider = add_user(db, "outsider@example.test", "REVIEWER", other)
    payload = {"status": "CONFIRMED", "verified_species": "Pterois volitans"}
    url = f"/observations/{observation.id}/verify"
    assert client.patch(url, json=payload).status_code == 401
    assert client.patch(url, json=payload, headers=auth_header(client, viewer.email)).status_code == 403
    assert client.patch(url, json=payload, headers=auth_header(client, outsider.email)).status_code == 403
    response = client.patch(url, json=payload, headers=auth_header(client, reviewer.email))
    assert response.status_code == 200
    db.refresh(observation)
    assert observation.verification_status == "CONFIRMED"
    assert observation.verified_by_user_id == reviewer.id


def test_review_queue_requires_reviewer_or_admin(environment):
    db, client, jamaica, _ = environment
    add_observation(db, jamaica)
    viewer = add_user(db, "viewer@example.test", "VIEWER", jamaica)
    reviewer = add_user(db, "reviewer@example.test", "REVIEWER", jamaica)
    admin = add_user(db, "admin@example.test", platform_admin=True)
    url = "/observations/review-queue?region_slug=caribbean&jurisdiction_slug=jamaica"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth_header(client, viewer.email)).status_code == 403
    assert client.get(url, headers=auth_header(client, reviewer.email)).status_code == 200
    assert client.get(url, headers=auth_header(client, admin.email)).status_code == 200


def test_regeneration_authorization_stops_before_service(environment, monkeypatch):
    db, client, jamaica, _ = environment
    viewer = add_user(db, "viewer@example.test", "VIEWER", jamaica)
    reviewer = add_user(db, "reviewer@example.test", "REVIEWER", jamaica)
    manager = add_user(db, "manager@example.test", "MANAGER", jamaica)
    admin = add_user(db, "admin@example.test", platform_admin=True)
    model = HabitatSuitabilityModel(model_version="pterois-volitans-suitability-v3", scientific_name="Pterois volitans", algorithm="fixture", feature_list_json="[]", training_generation_version="fixture", training_sample_count=1, eligible_presence_count=1, eligible_background_count=0, spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}", artifact_path="fixture", trained_at=datetime.now(timezone.utc))
    from models import Species
    species_identity = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(species_identity); db.flush()
    program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=species_identity.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add_all([model, program]); db.flush()
    deployment = SuitabilityDeployment(species_program_id=program.id, habitat_suitability_model_id=model.id, model_version=model.model_version, status="ACTIVE")
    db.add(deployment); db.flush()
    db.add(NextAreaSnapshotGeneration(species_program_id=program.id, suitability_deployment_id=deployment.id, scientific_name="Pterois volitans", prediction_version="pterois-volitans-next-area-v1", suitability_model_version=model.model_version, status="ACTIVE", is_active=True, diagnostics_json="{}", started_at=datetime.now(timezone.utc), generated_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc)))
    db.commit()
    calls = []
    monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", lambda self, *args, **kwargs: calls.append(1) or {"id": 99})
    base_url = "/predictions/species/Pterois%20volitans/next-areas/regenerate"
    jamaica_scope = f"?region_slug=caribbean&jurisdiction_slug={jamaica.slug}"
    other_scope = "?region_slug=caribbean&jurisdiction_slug=test-island"
    assert client.post(base_url).status_code == 401
    assert client.post(f"{base_url}{jamaica_scope}", headers=auth_header(client, viewer.email)).status_code == 403
    assert client.post(f"{base_url}{jamaica_scope}", headers=auth_header(client, reviewer.email)).status_code == 403
    assert calls == []
    assert client.post(f"{base_url}{jamaica_scope}", headers=auth_header(client, manager.email)).status_code == 200
    assert client.post(f"{base_url}{jamaica_scope}", headers=auth_header(client, admin.email)).status_code == 200
    assert len(calls) == 2
    assert client.post(f"{base_url}{other_scope}", headers=auth_header(client, manager.email)).status_code == 404
    assert client.post(base_url, headers=auth_header(client, manager.email)).status_code == 400


def test_non_jamaica_scientific_deployments_are_deliberately_unavailable(environment, monkeypatch):
    db, client, _, other = environment
    admin = add_user(db, "science-admin@example.test", platform_admin=True)
    monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", lambda *args, **kwargs: pytest.fail("unsupported jurisdiction must not reach regeneration"))
    scope = f"region_slug=caribbean&jurisdiction_slug={other.slug}"
    species = "/predictions/species/Pterois%20volitans"
    assert client.get(f"{species}/suitability/grid?{scope}").status_code == 404
    assert client.get(f"{species}/next-areas?{scope}").status_code == 404
    assert client.get(f"{species}/next-areas/summary?{scope}").status_code == 404
    assert client.get(f"{species}/next-areas/freshness?{scope}").status_code == 404
    assert client.post(f"{species}/next-areas/regenerate?{scope}", headers=auth_header(client, admin.email)).status_code == 404
