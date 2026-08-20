"""Phase 9B: Regional Species Intelligence.

Verifies:

1. Pterois volitans appears once as canonical regional species.
2. Jamaica evidence is attributed correctly.
3. Bahamas zero evidence is represented as zero platform evidence, not absence.
4. Jamaica SpeciesProgram is linked to canonical Pterois identity.
5. Bahamas does not inherit Jamaica SpeciesProgram.
6. Bahamas does not inherit Jamaica suitability.
7. Bahamas does not inherit Jamaica Monitoring Priority.
8. No regional prediction score exists.
9. Regional totals equal jurisdiction evidence totals.
10. Unresolved species evidence is not falsely canonicalized.
11. Confirmed/corrected evidence uses verified identity correctly.
12. Pending AI evidence remains distinguishable.
13. Existing Jamaica scientific endpoints remain unchanged.
14. Existing Bahamas scientific 404 behavior remains unchanged.
15. Jurisdiction-scoped endpoint returns canonical species even when no
    jurisdiction-specific evidence exists.
16. Jurisdiction-scoped endpoint returns jurisdiction-specific per_jurisdiction
    data only.
17. Regional species-evidence endpoint still works (compatibility).
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
from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402
    HabitatSuitabilityModel, Jurisdiction, JurisdictionBoundary, NextAreaSnapshotGeneration,
    Observation, Region, Species, SpeciesProgram, SuitabilityDeployment,
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

    canonical_pterois = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(canonical_pterois); db.flush()
    canonical_octopus = Species(scientific_name="Octopus briareus", common_name="Caribbean reef octopus", status="ACTIVE")
    db.add(canonical_octopus); db.flush()
    canonical_scallop = Species(scientific_name="Sparisoma viride", common_name="Stoplight parrotfish", status="ACTIVE")
    db.add(canonical_scallop); db.flush()

    model = HabitatSuitabilityModel(model_version="pterois-volitans-suitability-v3", scientific_name="Pterois volitans", algorithm="fixture", feature_list_json="[]", training_generation_version="fixture", training_sample_count=1, eligible_presence_count=1, eligible_background_count=0, spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}", artifact_path="fixture", trained_at=datetime.now(timezone.utc))
    db.add(model); db.flush()
    jamaica_program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=canonical_pterois.id, scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
    db.add(jamaica_program); db.flush()
    deployment = SuitabilityDeployment(species_program_id=jamaica_program.id, habitat_suitability_model_id=model.id, model_version=model.model_version, status="ACTIVE")
    db.add(deployment); db.flush()
    db.add(NextAreaSnapshotGeneration(
        species_program_id=jamaica_program.id,
        suitability_deployment_id=deployment.id,
        scientific_name="Pterois volitans",
        prediction_version="pterois-volitans-next-area-v1",
        suitability_model_version=model.model_version,
        status="ACTIVE",
        is_active=True,
        diagnostics_json="{}",
        evidence_state_json="[]",
        started_at=datetime.now(timezone.utc),
        generated_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    ))

    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j1.jpg", latitude=18.0, longitude=-77.0, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="CONFIRMED", verified_species="Pterois volitans", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j2.jpg", latitude=18.1, longitude=-77.1, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j3.jpg", latitude=18.2, longitude=-77.2, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j4.jpg", latitude=18.3, longitude=-77.3, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j5.jpg", latitude=18.4, longitude=-77.4, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j6.jpg", latitude=18.5, longitude=-77.5, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j7.jpg", latitude=18.6, longitude=-77.6, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j8.jpg", latitude=18.7, longitude=-77.7, identification_status="unresolved", species=None, ecological_status="UNKNOWN", decision="UNRESOLVED_IDENTIFICATION", priority="REVIEW", verification_status="CORRECTED", verified_species="Octopus briareus", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j9.jpg", latitude=18.8, longitude=-77.8, identification_status="unresolved", species=None, ecological_status="UNKNOWN", decision="UNRESOLVED_IDENTIFICATION", priority="REVIEW", verification_status="CORRECTED", verified_species="Octopus briareus", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j10.jpg", latitude=18.9, longitude=-77.9, identification_status="accepted", species="Sparisoma viride", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))
    db.add(Observation(jurisdiction_id=jamaica.id, image_filename="j11.jpg", latitude=19.0, longitude=-78.0, identification_status="accepted", species="Mystery unregistered species", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime.now(timezone.utc)))

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
        yield db, client, region, jamaica, bahamas, canonical_pterois, jamaica_program
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def _pterois_in_canonical(payload):
    for item in payload["species"]:
        if item["scientific_name"] == "Pterois volitans":
            return item
    return None


def test_pterois_volitans_appears_once_as_canonical_regional_species(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    pterois_entries = [item for item in data["species"] if item["scientific_name"] == "Pterois volitans"]
    assert len(pterois_entries) == 1


def test_jamaica_evidence_is_attributed_correctly(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    assert item is not None
    assert item["evidence"]["total"] == 7
    assert item["evidence"]["verified_or_corrected"] == 1
    assert item["evidence"]["ai_supported"] == 6
    jamaica_pj = next(pj for pj in item["per_jurisdiction"] if pj["jurisdiction"]["slug"] == "jamaica")
    assert jamaica_pj["evidence"]["total"] == 7
    assert jamaica_pj["evidence"]["verified_or_corrected"] == 1
    assert jamaica_pj["evidence"]["ai_supported"] == 6


def test_bahamas_zero_evidence_is_represented_not_absent(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    assert item is not None
    assert item["jurisdictions_with_evidence"] == 1
    bahamas_pj = next(pj for pj in item["per_jurisdiction"] if pj["jurisdiction"]["slug"] == "bahamas")
    assert bahamas_pj["evidence"]["total"] == 0
    assert bahamas_pj["evidence"]["verified_or_corrected"] == 0
    assert bahamas_pj["scientific_program"] is False
    assert bahamas_pj["suitability"] == "Not configured"
    assert bahamas_pj["monitoring_priority"] == "Not configured"
    assert "absent" not in str(item).lower()
    assert "not found" not in str(item).lower()
    assert "not present" not in str(item).lower()


def test_jamaica_species_program_is_linked_to_canonical_pterois_identity(environment):
    db, client, region, jamaica, bahamas, canonical_pterois, jamaica_program = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    assert item["id"] == canonical_pterois.id
    assert len(item["scientific_programs"]) == 1
    assert item["scientific_programs"][0]["jurisdiction"]["slug"] == "jamaica"


def test_bahamas_does_not_inherit_jamaica_species_program(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    for program in item["scientific_programs"]:
        assert program["jurisdiction"]["slug"] != "bahamas"
    bahamas_pj = next(pj for pj in item["per_jurisdiction"] if pj["jurisdiction"]["slug"] == "bahamas")
    assert bahamas_pj["scientific_program"] is False


def test_bahamas_does_not_inherit_jamaica_suitability(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    for dep in item["suitability_deployments"]:
        assert dep["jurisdiction_id"] != bahamas_pj_id(environment)
    bahamas_pj = next(pj for pj in item["per_jurisdiction"] if pj["jurisdiction"]["slug"] == "bahamas")
    assert bahamas_pj["suitability"] == "Not configured"


def test_bahamas_does_not_inherit_jamaica_monitoring_priority(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    for gen in item["monitoring_priority_generations"]:
        assert gen["jurisdiction_id"] != bahamas_pj_id(environment)
    bahamas_pj = next(pj for pj in item["per_jurisdiction"] if pj["jurisdiction"]["slug"] == "bahamas")
    assert bahamas_pj["monitoring_priority"] == "Not configured"


def bahamas_pj_id(environment):
    db, *_ = environment
    return db.query(Jurisdiction).filter_by(slug="bahamas").one().id


def test_no_regional_prediction_score_exists(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
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
        "aggregated_priority",
    )
    for key in forbidden:
        assert key not in serialized, f"Found forbidden key: {key}"


def test_regional_totals_equal_jurisdiction_evidence_totals(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    per_jurisdiction_total = sum(pj["evidence"]["total"] for pj in item["per_jurisdiction"])
    assert item["evidence"]["total"] == per_jurisdiction_total


def test_unresolved_species_evidence_is_not_falsely_canonicalized(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    canonical_names = {item["scientific_name"] for item in data["species"]}
    assert "Mystery unregistered species" not in canonical_names
    unresolved_names = {item["scientific_name"] for item in data["unresolved_evidence"]}
    assert "Mystery unregistered species" in unresolved_names
    canonical_ids = {item["id"] for item in data["species"]}
    for item in data["unresolved_evidence"]:
        assert "canonical_species_id" not in item or item.get("canonical_species_id") is None
        for jurisdiction_entry in item["jurisdictions"]:
            assert isinstance(jurisdiction_entry["total"], int)
        assert item["scientific_name"] not in canonical_ids


def test_confirmed_and_corrected_evidence_use_verified_identity(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    octopus = next(item for item in data["species"] if item["scientific_name"] == "Octopus briareus")
    assert octopus["evidence"]["total"] == 2
    assert octopus["evidence"]["verified_or_corrected"] == 2


def test_pending_ai_evidence_remains_distinguishable(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    item = _pterois_in_canonical(data)
    assert item["evidence"]["ai_supported"] >= 5
    assert item["evidence"]["ai_supported"] < item["evidence"]["total"]


def test_existing_jamaica_scientific_endpoints_remain_unchanged(environment):
    db, client, *_ = environment
    base = "/predictions/species/Pterois%20volitans"
    response = client.get(f"{base}/suitability/grid?region_slug=caribbean&jurisdiction_slug=jamaica")
    assert response.status_code in (200, 404)


def test_existing_bahamas_scientific_404_behavior_remains_unchanged(environment):
    db, client, *_ = environment
    base = "/predictions/species/Pterois%20volitans"
    scope = "region_slug=caribbean&jurisdiction_slug=bahamas"
    assert client.get(f"{base}/suitability/grid?{scope}").status_code == 404
    assert client.get(f"{base}/next-areas?{scope}").status_code == 404


def test_jurisdiction_endpoint_returns_canonical_species_even_without_evidence(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/jurisdictions/bahamas/species").json()
    canonical_names = {item["scientific_name"] for item in data["species"]}
    assert "Pterois volitans" in canonical_names
    pterois = next(item for item in data["species"] if item["scientific_name"] == "Pterois volitans")
    assert len(pterois["per_jurisdiction"]) == 1
    assert pterois["per_jurisdiction"][0]["jurisdiction"]["slug"] == "bahamas"
    assert pterois["per_jurisdiction"][0]["evidence"]["total"] == 0
    assert pterois["per_jurisdiction"][0]["scientific_program"] is False


def test_jurisdiction_endpoint_returns_jurisdiction_specific_per_jurisdiction_only(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/jurisdictions/jamaica/species").json()
    pterois = next(item for item in data["species"] if item["scientific_name"] == "Pterois volitans")
    assert len(pterois["per_jurisdiction"]) == 1
    assert pterois["per_jurisdiction"][0]["jurisdiction"]["slug"] == "jamaica"
    bahamas_data = client.get("/regions/caribbean/jurisdictions/bahamas/species").json()
    pterois_bahamas = next(item for item in bahamas_data["species"] if item["scientific_name"] == "Pterois volitans")
    assert len(pterois_bahamas["per_jurisdiction"]) == 1
    assert pterois_bahamas["per_jurisdiction"][0]["jurisdiction"]["slug"] == "bahamas"


def test_regional_species_evidence_endpoint_still_works(environment):
    db, client, *_ = environment
    response = client.get("/regions/caribbean/species-evidence")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1
    assert any(item["scientific_name"] == "Pterois volitans" for item in data["species_evidence"])


def test_canonical_species_with_observation_only_appears_in_canonical_list(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    canonical_names = {item["scientific_name"] for item in data["species"]}
    assert "Pterois volitans" in canonical_names
    assert "Octopus briareus" in canonical_names
    assert "Sparisoma viride" in canonical_names


def test_response_includes_region_and_jurisdiction_metadata(environment):
    db, client, *_ = environment
    data = client.get("/regions/caribbean/species").json()
    assert data["region"]["slug"] == "caribbean"
    assert data["region"]["status"] == "ACTIVE"
    data_b = client.get("/regions/caribbean/jurisdictions/bahamas/species").json()
    assert data_b["jurisdiction"]["slug"] == "bahamas"