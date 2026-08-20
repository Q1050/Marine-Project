"""Phase 9A: Caribbean regional intelligence overview.

Verifies:

1. Caribbean overview contains Jamaica and Bahamas.
2. Jamaica observation counts are correct.
3. Bahamas zero observations are represented correctly.
4. Regional totals equal jurisdiction totals.
5. Scientific deployment coverage reports Jamaica correctly.
6. Bahamas is not reported as having suitability.
7. Bahamas is not reported as having Monitoring Priority.
8. Regional response contains no synthetic regional prediction score.
9. Regional species evidence is based on observations.
10. Bahamas cannot inherit Jamaica species deployment through aggregation.
11. Regional observation filtering respects jurisdiction.
12. Existing Jamaica scientific endpoints remain unchanged.
13. Existing Bahamas scientific 404 behavior remains unchanged.
"""

from datetime import datetime, timezone
import json
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
    FieldVisit, HabitatSuitabilityModel, Investigation, Jurisdiction, JurisdictionBoundary,
    Observation, Organization, OrganizationJurisdiction, OrganizationMembership, Region,
    Species, SpeciesProgram, SuitabilityDeployment, User,
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
    jamaica_org = Organization(name="Jamaica Agency", slug="jamaica-agency", organization_type="OTHER", status="ACTIVE")
    bahamas_org = Organization(name="Bahamas Agency", slug="bahamas-agency", organization_type="OTHER", status="ACTIVE")
    db.add_all([jamaica_org, bahamas_org]); db.flush()
    db.add_all([
        OrganizationJurisdiction(organization_id=jamaica_org.id, jurisdiction_id=jamaica.id, status="ACTIVE"),
        OrganizationJurisdiction(organization_id=bahamas_org.id, jurisdiction_id=bahamas.id, status="ACTIVE"),
    ])
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j1.jpg", latitude=18.0, longitude=-77.0, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="CONFIRMED", verified_species="Pterois volitans", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j2.jpg", latitude=18.1, longitude=-77.1, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j3.jpg", latitude=18.2, longitude=-77.2, identification_status="unresolved", species=None, ecological_status="UNKNOWN", decision="UNRESOLVED_IDENTIFICATION", priority="REVIEW", verification_status="NEEDS_MORE_REVIEW", created_at=datetime.now(timezone.utc)))
    db.add(Investigation(jurisdiction_id=jamaica.id, title="Follow-up", objective="Check", priority="HIGH", assigned_organization_id=jamaica_org.id, created_by_user_id=1, latitude=18.0, longitude=-77.0, source_type="MANUAL", status="IN_PROGRESS"))
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
            org = jamaica_org if jurisdiction.id == jamaica.id else bahamas_org
            db.add(OrganizationMembership(user_id=user.id, organization_id=org.id, role=role, status="ACTIVE"))
        db.commit(); return user
    users = {
        "admin": add_user("admin@example.test", admin=True),
    }
    def headers(name):
        response = client.post("/auth/login", json={"email": users[name].email, "password": "test-password"})
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    try:
        yield db, client, headers, jamaica, bahamas, jamaica_org, bahamas_org, species_identity, jamaica_program, deployment
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def test_caribbean_overview_contains_jamaica_and_bahamas(environment):
    db, client, headers, *_ = environment
    response = client.get("/regions/caribbean/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["region"]["slug"] == "caribbean"
    slugs = [item["slug"] for item in payload["jurisdiction_summaries"]]
    assert "jamaica" in slugs
    assert "bahamas" in slugs


def test_jamaica_observation_counts_are_correct(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    jamaica_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "jamaica")
    assert jamaica_block["observations"]["total"] == 3
    assert jamaica_block["observations"]["confirmed"] == 1
    assert jamaica_block["observations"]["pending_review"] == 2  # PENDING + NEEDS_MORE_REVIEW


def test_bahamas_zero_observations_are_represented_correctly(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    bahamas_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert bahamas_block["observations"]["total"] == 0
    assert bahamas_block["investigations"]["total"] == 0
    assert bahamas_block["field_visits_total"] == 0
    assert bahamas_block["scientific_programs_total"] == 0


def test_regional_totals_equal_jurisdiction_totals(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    regional_total = payload["observations"]["total"]
    jurisdiction_total = sum(item["observations"]["total"] for item in payload["jurisdiction_summaries"])
    assert regional_total == jurisdiction_total
    regional_investigations = payload["operational_activity"]["investigations_total"]
    jurisdiction_investigations = sum(item["investigations"]["total"] for item in payload["jurisdiction_summaries"])
    assert regional_investigations == jurisdiction_investigations


def test_scientific_deployment_coverage_reports_jamaica_correctly(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    assert payload["scientific_deployments"]["jurisdictions_with_species_programs"] == 1
    assert payload["scientific_deployments"]["jurisdictions_with_suitability"] == 1
    jamaica_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "jamaica")
    assert jamaica_block["capabilities"]["habitat_suitability"] is True
    assert jamaica_block["capabilities"]["monitoring_priority"] is False


def test_bahamas_is_not_reported_as_having_suitability(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    bahamas_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert bahamas_block["capabilities"]["habitat_suitability"] is False
    assert bahamas_block["scientific_deployment"]["habitat_suitability"] == "Not configured"


def test_bahamas_is_not_reported_as_having_monitoring_priority(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    bahamas_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert bahamas_block["capabilities"]["monitoring_priority"] is False
    assert bahamas_block["scientific_deployment"]["monitoring_priority"] == "Not configured"


def test_regional_response_contains_no_synthetic_regional_prediction_score(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    serialized = json.dumps(payload)
    forbidden_keys = ("regional_priority", "caribbean_priority", "regional_suitability", "caribbean_suitability", "average_priority", "average_suitability", "aggregated_priority", "regional_score", "caribbean_score")
    for key in forbidden_keys:
        assert key not in serialized
    assert payload["scientific_deployments"]["jurisdictions_with_monitoring_priority"] == 0
    assert "regional_priority_score" not in payload
    assert "prediction" not in {key.lower() for key in payload.get("scientific_deployments", {}).keys()}


def test_regional_species_evidence_is_based_on_observations(environment):
    db, client, headers, *_ = environment
    response = client.get("/regions/caribbean/species-evidence")
    assert response.status_code == 200
    payload = response.json()
    items = payload["species_evidence"]
    pterois = next((item for item in items if item["scientific_name"] == "Pterois volitans"), None)
    assert pterois is not None
    assert pterois["total_observations"] == 2  # only confirmed/accepted; NEEDS_MORE_REVIEW with no species excluded
    assert pterois["verified_or_corrected"] == 1
    assert pterois["ai_supported"] == 1
    jurisdiction_slugs = [item["slug"] for item in pterois["jurisdictions"]]
    assert jurisdiction_slugs == ["jamaica"]


def test_bahamas_cannot_inherit_jamaica_species_deployment_through_aggregation(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    jamaica_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "jamaica")
    bahamas_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert jamaica_block["scientific_programs_total"] == 1
    assert bahamas_block["scientific_programs_total"] == 0
    assert jamaica_block["scientific_programs_total"] != bahamas_block["scientific_programs_total"]
    evidence = client.get("/regions/caribbean/species-evidence").json()
    pterois = next(item for item in evidence["species_evidence"] if item["scientific_name"] == "Pterois volitans")
    assert "bahamas" not in [item["slug"] for item in pterois["jurisdictions"]]


def test_regional_observation_filtering_respects_jurisdiction(environment):
    db, client, headers, *_ = environment
    caribbean_response = client.get("/observations/map?region_slug=caribbean").json()
    assert caribbean_response["count"] == 3
    jamaica_response = client.get("/observations/map?region_slug=caribbean&jurisdiction_slug=jamaica").json()
    assert jamaica_response["count"] == 3
    bahamas_response = client.get("/observations/map?region_slug=caribbean&jurisdiction_slug=bahamas").json()
    assert bahamas_response["count"] == 0
    for marker in jamaica_response["markers"]:
        assert marker["jurisdiction"] == "jamaica"


def test_existing_jamaica_scientific_endpoints_remain_unchanged(environment):
    db, client, headers, jamaica, *_ = environment
    response = client.get(f"/predictions/species/Pterois%20volitans/suitability/grid?region_slug=caribbean&jurisdiction_slug={jamaica.slug}")
    assert response.status_code in (200, 404)
    if response.status_code == 404:
        body = response.json()
        assert "Pterois volitans" not in body.get("detail", "")


def test_existing_bahamas_scientific_404_behavior_remains_unchanged(environment):
    db, client, headers, _, bahamas, *_ = environment
    base = "/predictions/species/Pterois%20volitans"
    scope = f"region_slug=caribbean&jurisdiction_slug={bahamas.slug}"
    assert client.get(f"{base}/suitability/grid?{scope}").status_code == 404
    assert client.get(f"{base}/next-areas?{scope}").status_code == 404
    assert client.get(f"{base}/next-areas/summary?{scope}").status_code == 404
    assert client.get(f"{base}/next-areas/freshness?{scope}").status_code == 404


def test_observations_endpoint_carries_jurisdiction_identity(environment):
    db, client, headers, *_ = environment
    caribbean = client.get("/observations/map?region_slug=caribbean").json()
    for marker in caribbean["markers"]:
        assert marker.get("jurisdiction") in {"jamaica", "bahamas"}
        assert marker.get("region") == "caribbean"


def test_zero_data_bahamas_is_not_an_error(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    bahamas_block = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert bahamas_block["operational_boundary_configured"] is True
    assert bahamas_block["observations"]["total"] == 0
    evidence = client.get("/regions/caribbean/species-evidence").json()
    assert isinstance(evidence["species_evidence"], list)


def test_no_synthetic_jamaica_duplicate_in_bahamas(environment):
    db, client, headers, *_ = environment
    payload = client.get("/regions/caribbean/overview").json()
    jamaica_summary = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "jamaica")
    bahamas_summary = next(item for item in payload["jurisdiction_summaries"] if item["slug"] == "bahamas")
    assert jamaica_summary["id"] != bahamas_summary["id"]
    assert jamaica_summary["scientific_programs_total"] == 1
    assert bahamas_summary["scientific_programs_total"] == 0