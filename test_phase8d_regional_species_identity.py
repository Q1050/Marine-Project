"""Phase 8D: Regional species identity + final scientific scope cleanup.

Verifies:

1. Jamaica scientific requests explicitly resolve Jamaica (no silent fall-through).
2. Bahamas scientific requests cannot fall back to Jamaica.
3. Omitting required scientific jurisdiction scope fails safely with 400.
4. Jamaica regeneration resolution remains valid without actually running production
   regeneration.
5. Bahamas regeneration returns "not configured" rather than hitting Jamaica.
6. Monitoring-priority investigation creation is capability-driven rather than
   Jamaica-slug-driven.
7. Bahamas cannot create a Monitoring Priority investigation without a deployment.
8. Jamaica existing scientific values remain unchanged.
9. Jamaica generation 2 remains ACTIVE.
10. Bahamas has no scientific deployment.
11. One Pterois volitans Species identity exists.
12. Jamaica program references the canonical Species identity.
13. A future Bahamas program could reference the same Species identity.
"""

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
    HabitatSuitabilityModel, HabitatSuitabilityV3GridCell, Jurisdiction, JurisdictionBoundary, NextAreaSnapshotCell,
    NextAreaSnapshotGeneration, Observation, Organization, OrganizationJurisdiction,
    OrganizationMembership, Region, Species, SpeciesProgram, SuitabilityDeployment, User,
)


@pytest.fixture
def environment():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    db.add(region); db.flush()
    jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8)
    bahamas = Jurisdiction(region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS", status="ACTIVE", center_latitude=24.25, center_longitude=-76.0, default_zoom=6)
    db.add_all([jamaica, bahamas]); db.flush()
    db.add_all([
        JurisdictionBoundary(jurisdiction_id=jamaica.id, boundary_type="MARINE_MONITORING", geometry_json='{"type":"Polygon","coordinates":[[[-80,16],[-75,16],[-75,20],[-80,20],[-80,16]]]}', source="fixture", status="ACTIVE"),
        JurisdictionBoundary(jurisdiction_id=bahamas.id, boundary_type="MARINE_MONITORING", geometry_json='{"type":"Polygon","coordinates":[[[-82,20],[-70,20],[-70,31],[-82,31],[-82,20]]]}', source="fixture", status="ACTIVE"),
    ])

    species_identity = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(species_identity); db.flush()

    model = HabitatSuitabilityModel(model_version="pterois-volitans-suitability-v3", scientific_name="Pterois volitans", algorithm="fixture", feature_list_json="[]", training_generation_version="fixture", training_sample_count=1, eligible_presence_count=1, eligible_background_count=0, spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}", artifact_path="fixture", trained_at=datetime.now(timezone.utc))
    db.add(model); db.flush()
    jamaica_program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=species_identity.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(jamaica_program); db.flush()
    deployment = SuitabilityDeployment(species_program_id=jamaica_program.id, habitat_suitability_model_id=model.id, model_version=model.model_version, status="ACTIVE")
    db.add(deployment); db.flush()
    db.add(HabitatSuitabilityV3GridCell(scientific_name="Pterois volitans", model_version=model.model_version, suitability_deployment_id=deployment.id, grid_cell_id="180:-770", latitude=18.05, longitude=-76.95, grid_size=0.1, suitability_score=0.7, suitability_band="HIGH", prediction_status="SCORED", feature_values_json="{}", missing_features_json="[]", generated_at=datetime.now(timezone.utc)))
    generation = NextAreaSnapshotGeneration(species_program_id=jamaica_program.id, suitability_deployment_id=deployment.id, scientific_name="Pterois volitans", prediction_version="pterois-volitans-next-area-v1", suitability_model_version=model.model_version, status="ACTIVE", is_active=True, diagnostics_json="{}", evidence_state_json="[]", started_at=datetime.now(timezone.utc), generated_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc))
    db.add(generation); db.flush()
    cell = NextAreaSnapshotCell(generation_id=generation.id, scientific_name="Pterois volitans", prediction_version=generation.prediction_version, grid_cell_id="180:-770", latitude=18.05, longitude=-76.95, suitability_score=0.7, distance_from_nearest_current_evidence_km=10, observation_evidence_score=0.6, recent_activity_score=0.7, current_evidence_score=0.7, monitoring_priority_score=0.7, priority_band="HIGH", source_observation_ids_json="[]", evidence_json="{}", reason_codes_json="[]", generated_at=generation.generated_at)
    db.add(cell)
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="jam.jpg", latitude=18.0, longitude=-77.0, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    jamaica_org = Organization(name="Jamaica Agency", slug="jamaica-agency", organization_type="OTHER", status="ACTIVE")
    bahamas_org = Organization(name="Bahamas Agency", slug="bahamas-agency", organization_type="OTHER", status="ACTIVE")
    db.add_all([jamaica_org, bahamas_org]); db.flush()
    db.add_all([
        OrganizationJurisdiction(organization_id=jamaica_org.id, jurisdiction_id=jamaica.id, status="ACTIVE"),
        OrganizationJurisdiction(organization_id=bahamas_org.id, jurisdiction_id=bahamas.id, status="ACTIVE"),
    ])
    db.commit()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()
    api.app.dependency_overrides[get_db] = override_db
    api.service = _StubMarineObservationService()
    client = TestClient(api.app)

    def add_user(email, role=None, jurisdiction=None, admin=False):
        user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password("test-password"), status="ACTIVE", is_platform_admin=admin)
        db.add(user); db.flush()
        if role and jurisdiction:
            org = next(item for item in [jamaica_org, bahamas_org] if item.jurisdiction_links[0].jurisdiction_id == jurisdiction.id)
            db.add(OrganizationMembership(user_id=user.id, organization_id=org.id, role=role, status="ACTIVE"))
        db.commit(); return user
    users = {
        "jamaica_manager": add_user("jamaica-manager@example.test", "MANAGER", jamaica),
        "jamaica_viewer": add_user("jamaica-viewer@example.test", "VIEWER", jamaica),
        "bahamas_manager": add_user("bahamas-manager@example.test", "MANAGER", bahamas),
        "admin": add_user("admin@example.test", admin=True),
    }
    def headers(name):
        response = client.post("/auth/login", json={"email": users[name].email, "password": "test-password"})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    try:
        yield db, client, headers, jamaica, bahamas, jamaica_org, bahamas_org, species_identity, jamaica_program, deployment, generation, cell
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def scientific_path(scientific_name="Pterois%20volitans"):
    return f"/predictions/species/{scientific_name}"


def test_one_pterois_volitans_species_identity_exists(environment):
    db, *_ = environment
    species_rows = db.query(Species).filter(Species.scientific_name == "Pterois volitans").all()
    assert len(species_rows) == 1, "Canonical Species identity must be unique by scientific_name."


def test_jamaica_program_references_canonical_species_identity(environment):
    db, *_ = environment
    jamaica_program = db.query(SpeciesProgram).filter_by(jurisdiction_id=environment[3].id).one()
    assert jamaica_program.species_id is not None
    species = db.query(Species).filter_by(id=jamaica_program.species_id).one()
    assert species.scientific_name == "Pterois volitans"


def test_future_bahamas_program_can_reference_existing_species_identity(environment):
    db, _, _, _, bahamas, *_ = environment
    species_identity = db.query(Species).filter_by(scientific_name="Pterois volitans").one()
    future_program = SpeciesProgram(jurisdiction_id=bahamas.id, species_id=species_identity.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(future_program); db.commit()
    assert db.query(Species).filter_by(scientific_name="Pterois volitans").count() == 1
    assert db.query(SpeciesProgram).filter_by(species_id=species_identity.id, jurisdiction_id=bahamas.id).count() == 1


def test_bahamas_has_no_scientific_deployment(environment):
    db, *_ = environment
    bahamas = environment[4]
    assert db.query(SpeciesProgram).filter_by(jurisdiction_id=bahamas.id).count() == 0


def test_jamaica_scientific_requests_resolve_jamaica(environment):
    db, client, headers, jamaica, *_ = environment
    jamaica_scope = f"region_slug=caribbean&jurisdiction_slug={jamaica.slug}"
    response = client.get(f"{scientific_path()}/suitability/grid?{jamaica_scope}")
    assert response.status_code == 200
    cells = response.json().get("cells") or []
    assert cells, "Jamaica suitability grid should be reachable with explicit Jamaica scope."


def test_bahamas_scientific_requests_cannot_fall_back_to_jamaica(environment):
    db, client, headers, jamaica, bahamas, *_ = environment
    bahamas_scope = f"region_slug=caribbean&jurisdiction_slug={bahamas.slug}"
    assert client.get(f"{scientific_path()}/suitability/grid?{bahamas_scope}").status_code == 404
    assert client.get(f"{scientific_path()}/next-areas?{bahamas_scope}").status_code == 404
    assert client.get(f"{scientific_path()}/next-areas/summary?{bahamas_scope}").status_code == 404
    assert client.get(f"{scientific_path()}/next-areas/freshness?{bahamas_scope}").status_code == 404


def test_omitting_required_scientific_scope_fails_safely(environment):
    db, client, headers, jamaica, *_ = environment
    assert client.get(f"{scientific_path()}/suitability/grid").status_code == 400
    assert client.get(f"{scientific_path()}/next-areas").status_code == 400
    assert client.get(f"{scientific_path()}/next-areas/summary").status_code == 400
    assert client.get(f"{scientific_path()}/next-areas/freshness").status_code == 400
    assert client.get(f"{scientific_path()}/suitability/grid?region_slug=caribbean").status_code == 400
    assert client.get(f"{scientific_path()}/suitability/grid?jurisdiction_slug=jamaica").status_code == 400
    assert client.post(
        f"{scientific_path()}/next-areas/regenerate",
        headers=headers("jamaica_manager"),
    ).status_code == 400


def test_jamaica_regeneration_resolution_remains_valid_without_production_run(environment, monkeypatch):
    db, client, headers, jamaica, *_ = environment
    called = {"count": 0}
    def fake_regenerate(self, *args, **kwargs):
        called["count"] += 1
        return {"id": 999, "scientific_name": "Pterois volitans"}
    monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", fake_regenerate)
    response = client.post(
        f"{scientific_path()}/next-areas/regenerate?region_slug=caribbean&jurisdiction_slug={jamaica.slug}",
        headers=headers("jamaica_manager"),
    )
    assert response.status_code == 200
    assert called["count"] == 1
    details = db.query(NextAreaSnapshotGeneration).filter_by(id=environment[10].id).one()
    assert details.status == "ACTIVE" and details.is_active is True


def test_bahamas_regeneration_returns_not_configured(environment, monkeypatch):
    db, client, headers, jamaica, bahamas, *_ = environment
    def must_not_run(self, *args, **kwargs):
        raise AssertionError("Bahamas must never reach the regeneration service")
    monkeypatch.setattr(api.NextAreaPredictionService, "regenerate", must_not_run)
    response = client.post(
        f"{scientific_path()}/next-areas/regenerate?region_slug=caribbean&jurisdiction_slug={bahamas.slug}",
        headers=headers("admin"),
    )
    assert response.status_code == 404


def test_monitoring_priority_investigation_is_capability_driven(environment):
    db, client, headers, jamaica, bahamas, jamaica_org, bahamas_org, *_ = environment
    generation = environment[10]
    cell = environment[11]
    jamaica_url = "/regions/caribbean/jurisdictions/jamaica/investigations"
    bahamas_url = "/regions/caribbean/jurisdictions/bahamas/investigations"
    payload_base = {"title": "MP", "objective": "Check MP source.", "priority": "HIGH", "latitude": 18.0, "longitude": -77.0, "source_type": "MONITORING_PRIORITY"}
    payload_jamaica = {**payload_base, "assigned_organization_id": jamaica_org.id, "source_prediction_generation_id": generation.id, "source_prediction_cell_id": cell.grid_cell_id}
    payload_bahamas_missing_id = {**payload_base, "assigned_organization_id": bahamas_org.id, "source_prediction_generation_id": None, "source_prediction_cell_id": cell.grid_cell_id}
    payload_bahamas_with_jamaica_id = {**payload_base, "assigned_organization_id": bahamas_org.id, "source_prediction_generation_id": generation.id, "source_prediction_cell_id": cell.grid_cell_id}
    payload_bahamas_fake_id = {**payload_base, "assigned_organization_id": bahamas_org.id, "source_prediction_generation_id": 99999, "source_prediction_cell_id": "missing"}
    assert client.post(jamaica_url, json=payload_jamaica, headers=headers("jamaica_manager")).status_code == 200
    assert client.post(bahamas_url, json=payload_bahamas_missing_id, headers=headers("bahamas_manager")).status_code == 400
    assert client.post(bahamas_url, json=payload_bahamas_with_jamaica_id, headers=headers("bahamas_manager")).status_code == 400
    assert client.post(bahamas_url, json=payload_bahamas_fake_id, headers=headers("bahamas_manager")).status_code == 400


def test_bahamas_cannot_create_monitoring_priority_investigation_without_deployment(environment):
    db, client, headers, _, bahamas, _, bahamas_org, *_ = environment
    assert db.query(SpeciesProgram).filter_by(jurisdiction_id=bahamas.id).count() == 0
    url = "/regions/caribbean/jurisdictions/bahamas/investigations"
    payload = {"title": "Bahamas MP", "objective": "Attempt MP in Bahamas.", "priority": "HIGH", "assigned_organization_id": bahamas_org.id, "latitude": 25.0, "longitude": -76.0, "source_type": "MONITORING_PRIORITY", "source_prediction_generation_id": 1, "source_prediction_cell_id": "anything"}
    response = client.post(url, json=payload, headers=headers("bahamas_manager"))
    assert response.status_code == 400
    assert db.query(NextAreaSnapshotGeneration).count() == 1
    assert db.query(NextAreaSnapshotCell).count() == 1


def test_jamaica_existing_scientific_values_remain_unchanged(environment):
    db, *_ = environment
    jamaica_program = db.query(SpeciesProgram).filter_by(jurisdiction_id=environment[3].id).one()
    assert jamaica_program.scientific_name == "Pterois volitans"
    assert jamaica_program.common_name == "Lionfish"
    deployment = environment[9]
    assert deployment.model_version == "pterois-volitans-suitability-v3"
    assert deployment.status == "ACTIVE"


def test_jamaica_generation_2_remains_active(environment):
    db, *_ = environment
    jamaica = environment[3]
    jamaica_program = db.query(SpeciesProgram).filter_by(jurisdiction_id=jamaica.id).one()
    generations = db.query(NextAreaSnapshotGeneration).filter_by(species_program_id=jamaica_program.id).order_by(NextAreaSnapshotGeneration.id).all()
    assert len(generations) == 1
    assert generations[0].status == "ACTIVE" and generations[0].is_active is True


def test_admin_registry_labels_scientific_deployment(environment):
    db, client, headers, *_ = environment
    response = client.get("/admin/species-programs", headers=headers("admin"))
    assert response.status_code == 200
    payload = response.json()
    programs = payload["species_programs"]
    assert len(programs) == 1
    program = programs[0]
    assert program["scientific_name"] == "Pterois volitans"
    assert program["jurisdiction"]["slug"] == "jamaica"
    assert program["species"]["scientific_name"] == "Pterois volitans"
    assert program["program_label"] == "Jamaica · Pterois volitans monitoring program"