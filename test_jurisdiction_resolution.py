from datetime import datetime, timezone
import base64
import json
import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    def analyze(self, **kwargs):
        return {
            "observation": {},
            "identification": {"status": "accepted", "species": "Pterois volitans", "nearest_candidate": None, "score": 0.95, "margin": 0.2, "candidates": []},
            "regional_evidence": None,
            "ecological_status": "INVASIVE",
            "decision": "KNOWN_INVASIVE_RECORD",
            "priority": "HIGH",
            "reason": "Test fixture.",
        }


service_module = types.ModuleType("marine_observation_service")
service_module.MarineObservationService = _StubMarineObservationService
sys.modules.setdefault("marine_observation_service", service_module)

import api  # noqa: E402
from database import Base, get_db  # noqa: E402
from jurisdiction_resolution_service import JurisdictionResolutionService  # noqa: E402
from models import Jurisdiction, JurisdictionBoundary, Observation, Region  # noqa: E402


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    region = Region(name="Test Region", slug="test-region", status="ACTIVE")
    db.add(region); db.flush()
    first = Jurisdiction(region_id=region.id, name="Fixture A", slug="fixture-a", country_code="FA", status="ACTIVE", center_latitude=1, center_longitude=1, default_zoom=8)
    second = Jurisdiction(region_id=region.id, name="Fixture B", slug="fixture-b", country_code="FB", status="ACTIVE", center_latitude=2, center_longitude=2, default_zoom=8)
    db.add_all([first, second]); db.commit()

    def override_db():
        session = Session()
        try: yield session
        finally: session.close()

    api.app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(api, "UPLOAD_DIRECTORY", tmp_path)
    # Other API test modules install deliberately minimal service doubles at
    # import time. Own this dependency explicitly so full-suite ordering cannot
    # leak an unrelated stub into these submission integration tests.
    monkeypatch.setattr(api, "service", _StubMarineObservationService())
    try: yield db, TestClient(api.app), first, second
    finally:
        api.app.dependency_overrides.clear(); db.close(); engine.dispose()


def add_boundary(db, jurisdiction, coordinates, source="CONTROLLED_TEST_FIXTURE", *, geometry_type="Polygon", status="ACTIVE", boundary_type="MARINE_MONITORING"):
    geometry_coordinates = [coordinates] if geometry_type == "Polygon" else [[coordinates]]
    boundary = JurisdictionBoundary(
        jurisdiction_id=jurisdiction.id,
        boundary_type=boundary_type,
        geometry_json=json.dumps({"type": geometry_type, "coordinates": geometry_coordinates}),
        source=source,
        source_version="test-v1",
        source_reference="fixture://jurisdiction-boundary",
        status=status,
    )
    db.add(boundary); db.commit()
    return boundary


def test_boundary_persistence_provenance_and_multipolygon(environment):
    db, _, first, _ = environment
    boundary = add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]], geometry_type="MultiPolygon")
    db.expire_all()
    persisted = db.query(JurisdictionBoundary).filter_by(id=boundary.id).one()
    assert json.loads(persisted.geometry_json)["type"] == "MultiPolygon"
    assert persisted.source == "CONTROLLED_TEST_FIXTURE"
    assert persisted.source_version == "test-v1"
    assert persisted.source_reference == "fixture://jurisdiction-boundary"
    assert JurisdictionResolutionService().resolve(db, 1, 1)["status"] == "RESOLVED"


def test_inactive_and_non_monitoring_boundaries_are_ignored(environment):
    db, _, first, _ = environment
    coordinates = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    add_boundary(db, first, coordinates, status="INACTIVE")
    add_boundary(db, first, coordinates, boundary_type="LAND_ADMINISTRATIVE")
    assert JurisdictionResolutionService().resolve(db, 1, 1)["status"] == "NO_CONFIGURED_JURISDICTION"


def test_point_resolution_outside_overlap_and_provenance(environment):
    db, _, first, second = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    service = JurisdictionResolutionService()
    resolved = service.resolve(db, 1, 1)
    assert resolved["status"] == "RESOLVED"
    assert resolved["jurisdiction"]["slug"] == "fixture-a"
    assert resolved["boundary"]["source"] == "CONTROLLED_TEST_FIXTURE"
    assert service.resolve(db, 10, 10)["status"] == "NO_CONFIGURED_JURISDICTION"
    add_boundary(db, second, [[0.5, 0.5], [3, 0.5], [3, 3], [0.5, 3], [0.5, 0.5]])
    assert service.resolve(db, 1, 1)["status"] == "AMBIGUOUS"


@pytest.mark.parametrize(("latitude", "longitude"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_invalid_coordinates_fail(environment, latitude, longitude):
    db, _, _, _ = environment
    with pytest.raises(ValueError): JurisdictionResolutionService().resolve(db, latitude, longitude)


def test_public_preview_is_unauthenticated(environment):
    db, client, first, _ = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    response = client.get("/geography/resolve?latitude=1&longitude=1")
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"


def test_submission_resolves_server_side_and_persists_device_metadata(environment):
    db, client, first, second = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    response = client.post(
        "/observations/analyze",
        data={"latitude": "1", "longitude": "1", "jurisdiction_id": str(second.id), "location_accuracy_m": "12.5", "location_captured_at": "2026-08-17T12:00:00Z", "location_source": "DEVICE_GEOLOCATION"},
        files={"image": ("test.png", VALID_PNG, "image/png")},
    )
    assert response.status_code == 200, response.text
    observation = db.query(Observation).one()
    assert observation.jurisdiction_id == first.id
    assert observation.location_accuracy_m == 12.5
    assert observation.location_source == "DEVICE_GEOLOCATION"
    assert observation.location_captured_at is not None


def test_manual_location_is_distinguished_and_accuracy_not_invented(environment):
    db, client, first, _ = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    response = client.post("/observations/analyze", data={"latitude": "1", "longitude": "1", "location_accuracy_m": "99", "location_source": "MANUAL"}, files={"image": ("test.png", VALID_PNG, "image/png")})
    assert response.status_code == 200
    observation = db.query(Observation).one()
    assert observation.location_source == "MANUAL"
    assert observation.location_accuracy_m is None


def test_map_selected_location_clears_device_metadata(environment):
    db, client, first, _ = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    response = client.post(
        "/observations/analyze",
        data={
            "latitude": "1", "longitude": "1",
            "location_accuracy_m": "25",
            "location_captured_at": "2026-08-17T12:00:00Z",
            "location_source": "MAP_SELECTED",
        },
        files={"image": ("test.png", VALID_PNG, "image/png")},
    )
    assert response.status_code == 200
    observation = db.query(Observation).one()
    assert observation.location_source == "MAP_SELECTED"
    assert observation.location_accuracy_m is None
    assert observation.location_captured_at is None


def test_unresolved_submission_does_not_default_or_run_inference(environment, monkeypatch):
    db, client, _, _ = environment
    calls = []
    monkeypatch.setattr(api.service, "analyze", lambda **kwargs: calls.append(1))
    response = client.post("/observations/analyze", data={"latitude": "1", "longitude": "1", "location_source": "MANUAL"}, files={"image": ("test.png", VALID_PNG, "image/png")})
    assert response.status_code == 422
    assert response.json()["error"]["message"]["status"] == "NO_CONFIGURED_JURISDICTION"
    assert db.query(Observation).count() == 0
    assert calls == []


def test_ambiguous_submission_is_not_persisted(environment):
    db, client, first, second = environment
    add_boundary(db, first, [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])
    add_boundary(db, second, [[0.5, 0.5], [3, 0.5], [3, 3], [0.5, 3], [0.5, 0.5]])
    response = client.post(
        "/observations/analyze",
        data={"latitude": "1", "longitude": "1", "location_source": "MANUAL"},
        files={"image": ("test.png", VALID_PNG, "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["message"]["status"] == "AMBIGUOUS"
    assert len(response.json()["error"]["message"]["resolution"]["candidates"]) == 2
    assert db.query(Observation).count() == 0
