"""Phase 9C: Caribbean Regional Operational Analytics.

Verifies:

1. Caribbean totals equal jurisdiction totals.
2. Jamaica observations appear correctly.
3. Bahamas zero observations remain legitimate zero.
4. Verification-state totals are correct.
5. Review workload totals are correct.
6. Activity buckets use real observation timestamps.
7. Species analytics reuse canonical identity.
8. Unresolved species evidence remains separate.
9. Investigation states aggregate correctly.
10. Field detection states aggregate correctly.
11. NOT_DETECTED is never represented as absence.
12. Operational coverage reflects real configuration.
13. Jamaica suitability availability may be reported as configuration metadata.
14. Jamaica suitability numeric values are absent from regional analytics.
15. Monitoring Priority numeric values are absent.
16. Bahamas receives no Jamaica predictive data.
17. API response contains no synthetic regional prediction score.
18. Endpoint returns 404 for unknown region.
19. Endpoint returns 404 for inactive region.
"""

from datetime import datetime, timezone, timedelta
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

    canonical = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(canonical); db.flush()
    canonical_octopus = Species(scientific_name="Octopus briareus", common_name="Caribbean reef octopus", status="ACTIVE")
    db.add(canonical_octopus); db.flush()

    model = HabitatSuitabilityModel(model_version="pterois-volitans-suitability-v3", scientific_name="Pterois volitans", algorithm="fixture", feature_list_json="[]", training_generation_version="fixture", training_sample_count=1, eligible_presence_count=1, eligible_background_count=0, spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}", artifact_path="fixture", trained_at=datetime.now(timezone.utc))
    db.add(model); db.flush()
    jamaica_program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=canonical.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(jamaica_program); db.flush()
    deployment = SuitabilityDeployment(species_program_id=jamaica_program.id, habitat_suitability_model_id=model.id, model_version=model.model_version, status="ACTIVE")
    db.add(deployment); db.flush()

    jam_org = Organization(name="Jamaica Agency", slug="jamaica-agency", organization_type="OTHER", status="ACTIVE")
    db.add(jam_org); db.flush()
    db.add(OrganizationJurisdiction(organization_id=jam_org.id, jurisdiction_id=jamaica.id, status="ACTIVE"))

    manager_user = User(email="manager@example.test", display_name="Manager", password_hash="x", status="ACTIVE", is_platform_admin=False)
    db.add(manager_user); db.flush()
    db.add(OrganizationMembership(user_id=manager_user.id, organization_id=jam_org.id, role="MANAGER", status="ACTIVE"))

    base = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    observations = [
        Observation(jurisdiction_id=jamaica.id, image_filename="j1.jpg", latitude=18.0, longitude=-77.0, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="CONFIRMED", verified_species="Pterois volitans", created_at=base),
        Observation(jurisdiction_id=jamaica.id, image_filename="j2.jpg", latitude=18.1, longitude=-77.1, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="CORRECTED", verified_species="Pterois volitans", created_at=base + timedelta(days=1)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j3.jpg", latitude=18.2, longitude=-77.2, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=2)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j4.jpg", latitude=18.3, longitude=-77.3, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=2)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j5.jpg", latitude=18.4, longitude=-77.4, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=2)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j6.jpg", latitude=18.5, longitude=-77.5, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=3)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j7.jpg", latitude=18.6, longitude=-77.6, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=3)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j8.jpg", latitude=18.7, longitude=-77.7, identification_status="unresolved", species=None, ecological_status="UNKNOWN", decision="UNRESOLVED_IDENTIFICATION", priority="REVIEW", verification_status="NEEDS_MORE_REVIEW", created_at=base + timedelta(days=3)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j9.jpg", latitude=18.8, longitude=-77.8, identification_status="unresolved", species=None, ecological_status="UNKNOWN", decision="UNRESOLVED_IDENTIFICATION", priority="REVIEW", verification_status="CORRECTED", verified_species="Octopus briareus", created_at=base + timedelta(days=4)),
        Observation(jurisdiction_id=jamaica.id, image_filename="j10.jpg", latitude=18.9, longitude=-77.9, identification_status="accepted", species="Mystery unregistered", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=base + timedelta(days=4)),
    ]
    db.add_all(observations)

    investigation = Investigation(
        jurisdiction_id=jamaica.id,
        title="Follow-up",
        objective="Inspect area",
        status="IN_PROGRESS",
        priority="HIGH",
        assigned_organization_id=jam_org.id,
        created_by_user_id=manager_user.id,
        latitude=18.0, longitude=-77.0,
        source_type="MANUAL",
        created_at=base,
        started_at=base + timedelta(days=1),
    )
    completed_investigation = Investigation(
        jurisdiction_id=jamaica.id,
        title="Completed",
        objective="Done",
        status="COMPLETED",
        priority="LOW",
        assigned_organization_id=jam_org.id,
        created_by_user_id=manager_user.id,
        latitude=18.1, longitude=-77.1,
        source_type="MANUAL",
        created_at=base,
        started_at=base + timedelta(days=1),
        completed_at=base + timedelta(days=2),
    )
    cancelled_investigation = Investigation(
        jurisdiction_id=jamaica.id,
        title="Cancelled",
        objective="Cancelled",
        status="CANCELLED",
        priority="MODERATE",
        assigned_organization_id=jam_org.id,
        created_by_user_id=manager_user.id,
        latitude=18.2, longitude=-77.2,
        source_type="MANUAL",
        created_at=base,
        cancelled_at=base + timedelta(days=1),
    )
    planned_investigation = Investigation(
        jurisdiction_id=bahamas.id,
        title="Planned",
        objective="Plan",
        status="PLANNED",
        priority="LOW",
        assigned_organization_id=jam_org.id,
        created_by_user_id=manager_user.id,
        latitude=24.0, longitude=-76.0,
        source_type="MANUAL",
        created_at=base,
    )
    db.add_all([investigation, completed_investigation, cancelled_investigation, planned_investigation])
    db.flush()

    visit_detected = FieldVisit(
        investigation_id=investigation.id,
        jurisdiction_id=jamaica.id,
        organization_id=jam_org.id,
        recorded_by_user_id=manager_user.id,
        status="SUBMITTED",
        visited_at=base + timedelta(days=2),
        latitude=18.0, longitude=-77.0,
        survey_method="DIVE_SURVEY",
        effort_duration_minutes=45,
        target_detection_status="DETECTED",
        submitted_at=base + timedelta(days=2),
    )
    visit_not_detected = FieldVisit(
        investigation_id=investigation.id,
        jurisdiction_id=jamaica.id,
        organization_id=jam_org.id,
        recorded_by_user_id=manager_user.id,
        status="SUBMITTED",
        visited_at=base + timedelta(days=3),
        latitude=18.1, longitude=-77.1,
        survey_method="DIVE_SURVEY",
        effort_duration_minutes=45,
        target_detection_status="NOT_DETECTED",
        submitted_at=base + timedelta(days=3),
    )
    visit_inconclusive = FieldVisit(
        investigation_id=investigation.id,
        jurisdiction_id=jamaica.id,
        organization_id=jam_org.id,
        recorded_by_user_id=manager_user.id,
        status="DRAFT",
        visited_at=base + timedelta(days=4),
        latitude=18.2, longitude=-77.2,
        survey_method="DIVE_SURVEY",
        effort_duration_minutes=30,
        target_detection_status="INCONCLUSIVE",
    )
    db.add_all([visit_detected, visit_not_detected, visit_inconclusive])
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
    try:
        yield db, client, region, jamaica, bahamas, canonical
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def test_caribbean_totals_equal_jurisdiction_totals(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    by_jurisdiction = sum(item["observations"]["total"] for item in data["jurisdictions"])
    assert data["observations"]["total"] == by_jurisdiction


def test_jamaica_observations_appear_correctly(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    jamaica = next(item for item in data["jurisdictions"] if item["jurisdiction"]["slug"] == "jamaica")
    assert jamaica["observations"]["total"] == 10
    assert jamaica["observations"]["confirmed"] == 1
    assert jamaica["observations"]["corrected"] == 2
    assert jamaica["observations"]["pending"] == 6
    assert jamaica["observations"]["needs_more_review"] == 1


def test_bahamas_zero_observations_remain_legitimate_zero(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    bahamas = next(item for item in data["jurisdictions"] if item["jurisdiction"]["slug"] == "bahamas")
    assert bahamas["observations"]["total"] == 0
    assert bahamas["observations"]["confirmed"] == 0
    assert bahamas["observations"]["corrected"] == 0
    assert bahamas["observations"]["pending"] == 0
    assert bahamas["observations"]["needs_more_review"] == 0
    assert bahamas["species_evidence"]["count"] == 0
    serialized = str(bahamas).lower()
    assert "absent" not in serialized
    assert "not found" not in serialized
    assert "no invasive species" not in serialized


def test_verification_state_totals_are_correct(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    assert data["observations"]["total"] == 10
    assert data["observations"]["confirmed"] == 1
    assert data["observations"]["corrected"] == 2
    assert data["observations"]["pending"] == 6
    assert data["observations"]["needs_more_review"] == 1


def test_review_workload_totals_are_correct(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    assert data["review_workload"]["pending"] == 6
    assert data["review_workload"]["needs_more_review"] == 1
    assert data["review_workload"]["total"] == 7


def test_activity_buckets_use_real_observation_timestamps(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    buckets = data["activity"]["observation_buckets"]["buckets"]
    assert len(buckets) >= 4
    total_from_buckets = sum(bucket["total"] for bucket in buckets)
    assert total_from_buckets == 10
    for bucket in buckets:
        assert "T" in bucket["start"]
        assert isinstance(bucket["total"], int)
        assert isinstance(bucket["verified_or_corrected"], int)


def test_species_analytics_reuse_canonical_identity(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    species_list = data["species_evidence"]["species"]
    pterois = next(item for item in species_list if item["scientific_name"] == "Pterois volitans")
    assert pterois["total_observations"] == 7
    assert pterois["verified_or_corrected"] == 2
    assert pterois["common_name"] == "Lionfish"
    assert pterois["ai_supported"] == 5
    mystery_unresolved = next(
        (item for item in data["species_evidence"]["unresolved_evidence"] if item["scientific_name"] == "Mystery unregistered"),
        None,
    )
    assert mystery_unresolved is not None
    assert mystery_unresolved["evidence"]["total"] == 1


def test_unresolved_species_evidence_remains_separate(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    canonical_names = {item["scientific_name"] for item in data["species_evidence"]["species"]}
    assert "Mystery unregistered" not in canonical_names
    octopus = next(item for item in data["species_evidence"]["species"] if item["scientific_name"] == "Octopus briareus")
    assert octopus["verified_or_corrected"] == 1


def test_investigation_states_aggregate_correctly(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    assert data["investigations"]["total"] == 4
    assert data["investigations"]["in_progress"] == 1
    assert data["investigations"]["completed"] == 1
    assert data["investigations"]["cancelled"] == 1
    assert data["investigations"]["planned"] == 1
    assert data["investigations"]["active"] == 2


def test_field_detection_states_aggregate_correctly(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    assert data["field_activity"]["total"] == 3
    assert data["field_activity"]["draft"] == 1
    assert data["field_activity"]["submitted"] == 2
    assert data["field_activity"]["detection_outcomes"]["total"] == 3
    assert data["field_activity"]["detection_outcomes"]["detected"] == 1
    assert data["field_activity"]["detection_outcomes"]["not_detected"] == 1
    assert data["field_activity"]["detection_outcomes"]["inconclusive"] == 1


def test_not_detected_is_never_represented_as_absence(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    serialized = str(data).lower()
    assert "absence confidence" not in serialized
    assert "detection probability" not in serialized
    assert "absent from region" not in serialized
    assert "no platform evidence recorded" not in serialized
    interpretation = data["field_activity"]["non_detection_interpretation"].lower()
    assert "absence" in interpretation
    assert "not" in interpretation
    assert "interpret" in interpretation


def test_operational_coverage_reflects_real_configuration(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    coverage = data["operational_coverage"]
    assert coverage["configured_jurisdictions"] == 2
    assert coverage["jurisdictions_with_boundaries"] == 2
    assert coverage["jurisdictions_with_organizations"] == 1
    assert coverage["jurisdictions_with_managers"] == 1
    assert coverage["jurisdictions_with_species_programs"] == 1
    assert coverage["jurisdictions_with_suitability"] == 1
    assert coverage["jurisdictions_with_monitoring_priority"] == 0


def test_jamaica_suitability_availability_is_configuration_metadata_only(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    jamaica = next(item for item in data["jurisdictions"] if item["jurisdiction"]["slug"] == "jamaica")
    assert jamaica["habitat_suitability"] == "Available"
    assert jamaica["monitoring_priority"] == "Not configured"


def test_jamaica_suitability_numeric_values_are_absent(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    serialized = str(data).lower()
    forbidden = ("suitability_score", "suit_score", "habitat_score", "priority_score", "average_priority")
    for key in forbidden:
        assert key not in serialized, f"Found forbidden numeric key: {key}"
    assert "habitat_suitability_v3_grid" not in serialized


def test_monitoring_priority_numeric_values_are_absent(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    serialized = str(data).lower()
    forbidden = ("monitoring_priority_score", "next_area_priority", "priority_band_distribution")
    for key in forbidden:
        assert key not in serialized


def test_bahamas_receives_no_jamaica_predictive_data(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    bahamas = next(item for item in data["jurisdictions"] if item["jurisdiction"]["slug"] == "bahamas")
    assert bahamas["habitat_suitability"] == "Not configured"
    assert bahamas["monitoring_priority"] == "Not configured"
    assert bahamas["scientific_programs_configured"] is False
    jamaica = next(item for item in data["jurisdictions"] if item["jurisdiction"]["slug"] == "jamaica")
    assert jamaica["habitat_suitability"] == "Available"


def test_response_contains_no_synthetic_regional_prediction_score(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/analytics").json()
    serialized = str(data).lower()
    forbidden = (
        "regional_priority_score",
        "regional_suitability_score",
        "caribbean_priority",
        "caribbean_suitability",
        "average_priority",
        "average_suitability",
        "regional_score",
        "caribbean_score",
    )
    for key in forbidden:
        assert key not in serialized, f"Found forbidden key: {key}"


def test_unknown_region_returns_404(environment):
    db, client, *_ = environment
    response = client.get("/regions/missing-region/analytics")
    assert response.status_code == 404


def test_inactive_region_returns_404(environment):
    db, client, region, *_ = environment
    region.status = "INACTIVE"
    db.commit()
    response = client.get("/regions/caribbean/analytics")
    assert response.status_code == 404