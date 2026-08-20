from datetime import datetime, timezone
import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    pass


service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _StubMarineObservationService
sys.modules.setdefault("marine_observation_service", service_module)

import api  # noqa: E402
from auth_service import hash_password  # noqa: E402
from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402
    HabitatSuitabilityV3GridCell, Investigation, Jurisdiction, JurisdictionBoundary,
    NextAreaSnapshotCell, NextAreaSnapshotGeneration, Observation,
    Organization, OrganizationJurisdiction, OrganizationMembership, Region, Species, SpeciesProgram, User,
)


@pytest.fixture
def environment(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    db.add(region); db.flush()
    jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1, center_longitude=-77.3, default_zoom=8)
    other = Jurisdiction(region_id=region.id, name="Other", slug="other", country_code="OT", status="ACTIVE", center_latitude=12, center_longitude=-60, default_zoom=7)
    db.add_all([jamaica, other]); db.flush()
    db.add_all([
        JurisdictionBoundary(jurisdiction_id=jamaica.id, boundary_type="MARINE_MONITORING", geometry_json='{"type":"Polygon","coordinates":[[[-80,16],[-75,16],[-75,20],[-80,20],[-80,16]]]}', source="test", status="ACTIVE"),
        JurisdictionBoundary(jurisdiction_id=other.id, boundary_type="MARINE_MONITORING", geometry_json='{"type":"Polygon","coordinates":[[[-62,10],[-58,10],[-58,14],[-62,14],[-62,10]]]}', source="test", status="ACTIVE"),
    ])
    participating = Organization(name="Jamaica Test Agency", slug="jamaica-test-agency", organization_type="OTHER", status="ACTIVE")
    unrelated = Organization(name="Other Test Agency", slug="other-test-agency", organization_type="OTHER", status="ACTIVE")
    db.add_all([participating, unrelated]); db.flush()
    db.add_all([
        OrganizationJurisdiction(organization_id=participating.id, jurisdiction_id=jamaica.id, status="ACTIVE"),
        OrganizationJurisdiction(organization_id=unrelated.id, jurisdiction_id=other.id, status="ACTIVE"),
    ])
    observation = Observation(jurisdiction_id=jamaica.id, image_filename="test.jpg", latitude=18, longitude=-78, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc))
    other_observation = Observation(jurisdiction_id=other.id, image_filename="other.jpg", latitude=12, longitude=-60, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc))
    species_identity = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(species_identity); db.flush()
    jamaica_program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=species_identity.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(jamaica_program); db.flush()
    generation = NextAreaSnapshotGeneration(species_program_id=jamaica_program.id, scientific_name="Pterois volitans", prediction_version="pterois-volitans-next-area-v1", suitability_model_version="pterois-volitans-suitability-v3", status="ACTIVE", is_active=True, diagnostics_json="{}", evidence_state_json="[]", started_at=datetime.now(timezone.utc), generated_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc))
    db.add_all([observation, other_observation, generation]); db.flush()
    cell = NextAreaSnapshotCell(generation_id=generation.id, scientific_name="Pterois volitans", prediction_version=generation.prediction_version, grid_cell_id="180:-781", latitude=18.05, longitude=-78.05, suitability_score=.8, distance_from_nearest_current_evidence_km=5, observation_evidence_score=1, recent_activity_score=1, current_evidence_score=1, monitoring_priority_score=.89, priority_band="VERY_HIGH", source_observation_ids_json="[]", evidence_json="{}", reason_codes_json="[]", generated_at=generation.generated_at)
    db.add(cell); db.commit()

    def add_user(email, role=None, org=None, admin=False):
        user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password("test-password"), status="ACTIVE", is_platform_admin=admin)
        db.add(user); db.flush()
        if role: db.add(OrganizationMembership(user_id=user.id, organization_id=org.id, role=role, status="ACTIVE"))
        db.commit(); return user
    users = {
        "viewer": add_user("viewer@test.invalid", "VIEWER", participating),
        "reviewer": add_user("reviewer@test.invalid", "REVIEWER", participating),
        "manager": add_user("manager@test.invalid", "MANAGER", participating),
        "outsider": add_user("outsider@test.invalid", "MANAGER", unrelated),
        "admin": add_user("admin@test.invalid", admin=True),
    }

    def override_db():
        session = Session()
        try: yield session
        finally: session.close()
    api.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(api, "service", _StubMarineObservationService())
    client = TestClient(api.app)
    def headers(name):
        response = client.post("/auth/login", json={"email": users[name].email, "password": "test-password"})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    try:
        yield db, client, headers, jamaica, other, participating, unrelated, observation, other_observation, generation, cell
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def create_payload(org_id, source_type="MANUAL", **values):
    payload = {"title": "Reef follow-up", "objective": "Inspect the reported monitoring area.", "priority": "HIGH", "assigned_organization_id": org_id, "latitude": 18.1, "longitude": -78.1, "source_type": source_type}
    payload.update(values); return payload


def test_authorization_and_manual_creation(environment):
    db, client, headers, _, _, org, _, *_ = environment
    url = "/regions/caribbean/jurisdictions/jamaica/investigations"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers("viewer")).status_code == 200
    assert client.get(url, headers=headers("reviewer")).status_code == 200
    assert client.post(url, json=create_payload(org.id), headers=headers("viewer")).status_code == 403
    assert client.post(url, json=create_payload(org.id), headers=headers("reviewer")).status_code == 403
    assert client.post(url, json=create_payload(org.id), headers=headers("outsider")).status_code == 403
    created = client.post(url, json=create_payload(org.id), headers=headers("manager"))
    assert created.status_code == 200 and created.json()["source"]["type"] == "MANUAL"
    assert created.json()["jurisdiction"]["slug"] == "jamaica"
    assert client.get(f"/investigations/{created.json()['id']}", headers=headers("admin")).status_code == 200
    assert db.query(Investigation).count() == 1


def test_organization_and_observation_source_integrity(environment):
    db, client, headers, _, _, org, unrelated, observation, other_observation, *_ = environment
    url = "/regions/caribbean/jurisdictions/jamaica/investigations"
    assert client.post(url, json=create_payload(unrelated.id), headers=headers("manager")).status_code == 400
    before = (observation.latitude, observation.longitude, observation.verification_status)
    created = client.post(url, json=create_payload(org.id, "OBSERVATION", source_observation_id=observation.id), headers=headers("manager"))
    assert created.status_code == 200
    assert created.json()["source"]["observation_id"] == observation.id
    assert created.json()["source"]["observation_at_creation"]["verification_status"] == "PENDING"
    assert (created.json()["latitude"], created.json()["longitude"]) == (observation.latitude, observation.longitude)
    db.refresh(observation)
    assert (observation.latitude, observation.longitude, observation.verification_status) == before
    observation.verification_status = "CONFIRMED"
    db.commit()
    detail = client.get(f"/investigations/{created.json()['id']}", headers=headers("manager")).json()
    assert detail["source"]["observation_at_creation"]["verification_status"] == "PENDING"
    assert detail["source"]["observation"]["verification_status"] == "CONFIRMED"
    assert client.post(url, json=create_payload(org.id, "OBSERVATION", source_observation_id=other_observation.id), headers=headers("manager")).status_code == 400


def test_monitoring_source_is_snapshot_provenance(environment):
    db, client, headers, _, _, org, _, _, _, generation, cell = environment
    url = "/regions/caribbean/jurisdictions/jamaica/investigations"
    generation_count = db.query(NextAreaSnapshotGeneration).count()
    cell_count = db.query(NextAreaSnapshotCell).count()
    created = client.post(url, json=create_payload(org.id, "MONITORING_PRIORITY", source_prediction_generation_id=generation.id, source_prediction_cell_id=cell.grid_cell_id), headers=headers("manager"))
    assert created.status_code == 200, created.text
    source = created.json()["source"]
    assert source["generation_id"] == generation.id and source["cell_id"] == cell.grid_cell_id
    assert source["priority_score"] == .89 and source["priority_band"] == "VERY_HIGH"
    cell.monitoring_priority_score = .1; cell.priority_band = "VERY_LOW"; db.commit()
    detail = client.get(f"/investigations/{created.json()['id']}", headers=headers("viewer")).json()
    assert detail["source"]["priority_score"] == .89 and detail["source"]["priority_band"] == "VERY_HIGH"
    assert db.query(NextAreaSnapshotGeneration).count() == generation_count
    assert db.query(NextAreaSnapshotCell).count() == cell_count
    assert client.post(url, json=create_payload(org.id, "MONITORING_PRIORITY", source_prediction_generation_id=999, source_prediction_cell_id="missing"), headers=headers("manager")).status_code == 400


def test_status_lifecycle_and_invalid_transitions(environment):
    _, client, headers, _, _, org, *_ = environment
    url = "/regions/caribbean/jurisdictions/jamaica/investigations"
    item = client.post(url, json=create_payload(org.id), headers=headers("manager")).json()
    start = client.post(f"/investigations/{item['id']}/status", json={"status": "IN_PROGRESS"}, headers=headers("manager"))
    assert start.status_code == 200 and start.json()["started_at"]
    complete = client.post(f"/investigations/{item['id']}/status", json={"status": "COMPLETED", "outcome_summary": "Survey completed."}, headers=headers("manager"))
    assert complete.status_code == 200 and complete.json()["completed_at"] and complete.json()["outcome_summary"]
    assert client.post(f"/investigations/{item['id']}/status", json={"status": "IN_PROGRESS"}, headers=headers("manager")).status_code == 400
    cancelled_item = client.post(url, json=create_payload(org.id, title="Cancelled follow-up"), headers=headers("manager")).json()
    cancelled = client.post(f"/investigations/{cancelled_item['id']}/status", json={"status": "CANCELLED"}, headers=headers("manager"))
    assert cancelled.status_code == 200 and cancelled.json()["cancelled_at"]
