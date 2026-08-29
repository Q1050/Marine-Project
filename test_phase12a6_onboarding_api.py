import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from jurisdiction_onboarding_service import JurisdictionOnboardingService
from models import (
    HistoricalOccurrence, Jurisdiction, JurisdictionBoundary,
    JurisdictionOnboardingPreparation, JurisdictionOnboardingRecord,
    PredictionModelSample, Region, ScientificDatasetApplicability,
    SpeciesJurisdictionStatus, SpeciesProgram, SuitabilityDeployment,
    TrainingRun, User,
)
from phase12a6_migrate_onboarding_workflow import run_migration


ROOT = Path(__file__).parent
MANIFESTS = (
    ROOT / "artifacts/onboarding/antigua-and-barbuda-onboarding-manifest-v1.json",
    ROOT / "artifacts/onboarding/saint-lucia-onboarding-manifest-v1.json",
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Region(name="Caribbean", slug="caribbean", status="ACTIVE"))
    db.add(User(email="admin@test.invalid", display_name="Admin", password_hash="x", is_platform_admin=True))
    db.commit()
    try:
        yield db
    finally:
        db.close()


def test_migration_is_idempotent(tmp_path):
    connection = sqlite3.connect(tmp_path / "phase12a6.db")
    connection.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY); CREATE TABLE users(id INTEGER PRIMARY KEY); CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY); CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY);")
    assert run_migration(connection)["table_created"] is True
    assert run_migration(connection)["table_created"] is False


def test_generic_prepare_approval_apply_and_idempotency(session):
    service = JurisdictionOnboardingService(session)
    row = service.prepare_from_manifest(MANIFESTS[0])
    session.commit()
    assert row.workflow_state == "READY_FOR_REVIEW"
    assert service.prepare_from_manifest(MANIFESTS[0]).id == row.id

    service.approve(row, 1, "controlled-test-approval")
    session.commit()
    assert row.workflow_state == "APPROVED"
    result = service.apply(row, "user:1")
    assert result["status"] == "APPLIED"
    assert service.apply(row, "user:1")["status"] == "NO-OP"
    assert session.query(Jurisdiction).filter_by(canonical_identifier="AG").count() == 1
    assert session.query(JurisdictionBoundary).count() == 1
    assert session.query(JurisdictionOnboardingRecord).count() == 1
    jurisdiction_id = row.resulting_jurisdiction_id
    assert session.query(SpeciesProgram).filter_by(jurisdiction_id=jurisdiction_id).count() == 0
    assert session.query(SpeciesJurisdictionStatus).filter_by(jurisdiction_id=jurisdiction_id).count() == 0
    assert session.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=jurisdiction_id).count() == 0
    assert session.query(HistoricalOccurrence).count() == 0
    assert session.query(SuitabilityDeployment).count() == 0
    assert session.query(TrainingRun).count() == 0
    assert session.query(PredictionModelSample).count() == 0


def test_approval_binding_refuses_stale_hash(session):
    service = JurisdictionOnboardingService(session)
    row = service.prepare_from_manifest(MANIFESTS[0]); session.commit()
    service.approve(row, 1, "test"); session.commit()
    row.geometry_sha256 = "0" * 64
    with pytest.raises(ValueError, match="stale"):
        service.validate_approval(row)
    session.rollback()


def test_batch_partial_failure_preserves_success_and_allows_retry(session):
    service = JurisdictionOnboardingService(session)
    rows = [service.prepare_from_manifest(path) for path in MANIFESTS]
    session.commit()
    for row in rows:
        service.approve(row, 1, "batch-test")
    session.commit()

    class FailingSecondService(JurisdictionOnboardingService):
        def apply(self, row, operator_reference):
            if row.canonical_identifier == "LC":
                raise RuntimeError("controlled second-item failure")
            return super().apply(row, operator_reference)

    results = FailingSecondService(session).apply_batch([row.id for row in rows], "user:1")
    assert [item["status"] for item in results] == ["APPLIED", "BLOCKED"]
    assert session.query(Jurisdiction).filter_by(canonical_identifier="AG").count() == 1
    assert session.query(Jurisdiction).filter_by(canonical_identifier="LC").count() == 0
    retry = service.apply(session.get(JurisdictionOnboardingPreparation, rows[1].id), "user:1")
    assert retry["status"] == "APPLIED"


def test_api_surface_is_admin_guarded_and_country_agnostic():
    source = (ROOT / "api.py").read_text(encoding="utf-8")
    required = (
        '/admin/jurisdiction-onboarding/prepare',
        '/admin/jurisdiction-onboarding/prepare-bulk',
        '/admin/regions/{region_id}/jurisdiction-onboarding/prepare',
        '/admin/jurisdiction-onboarding/{preparation_id}/approve',
        '/admin/jurisdiction-onboarding/{preparation_id}/apply',
        '/admin/jurisdiction-onboarding/apply-batch',
    )
    assert all(route in source for route in required)
    assert source.count("Depends(require_platform_admin)") >= len(required)
    route_section = source[source.index('@app.post("/admin/jurisdiction-onboarding/prepare")'):source.index('@app.get("/admin/regions/{region_id}/species-baseline/contract")')]
    assert "Antigua" not in route_section and "Saint Lucia" not in route_section


def test_onboarding_endpoint_rejects_unauthenticated_request():
    from fastapi.testclient import TestClient
    from api import app

    response = TestClient(app).get("/admin/jurisdiction-onboarding/999")
    assert response.status_code == 401
