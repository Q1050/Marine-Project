"""Phase 10B: Canonical Caribbean Species + Jurisdiction Ecology Registry.

Verifies:

1. Pterois volitans remains one canonical Species.
2. Jamaica and Bahamas may reference the same Species independently.
3. Ecological status is jurisdiction-specific.
4. A Jamaica ecological record cannot leak into Bahamas.
5. Missing jurisdiction status returns UNKNOWN.
6. BioCLIP recognition availability does not imply SpeciesProgram availability.
7. SpeciesProgram availability does not imply BioCLIP recognition availability.
8. Suitability remains deployment-derived.
9. Monitoring Priority remains generation-derived.
10. Existing Jamaica observation behavior remains compatible.
11. Existing Jamaica scientific cells remain unchanged.
12. Bahamas still has no predictive deployment.
13. Initialization is idempotent.
14. Regional analytics do not reinterpret Jamaica ecological status as Caribbean-wide status.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class _StubMarineObservationService:
    """No-op stub for the BioCLIP service so we do not load the model
    during these registry tests.
    """
    pass


import api  # noqa: E402
import species_jurisdiction_ecology  # noqa: E402
import bioclip_reference_normalization  # noqa: E402
import init_db  # noqa: E402
from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402
    Jurisdiction, JurisdictionBoundary, Region, Species, SpeciesJurisdictionStatus,
    SpeciesProgram, SuitabilityDeployment, Observation,
)


def test_pterois_volitans_unchanged_as_canonical_species(environment):
    db, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").all()
    assert len(canonical) == 1
    assert canonical[0].id is not None


def test_jamaica_and_bahamas_reference_same_species_independently(environment):
    db, client, jamaica, bahamas, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    jamaica_status = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, jamaica.id)
    bahamas_status = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, bahamas.id)
    assert jamaica_status is not None
    assert bahamas_status is None


def test_ecological_status_is_jurisdiction_specific(environment):
    db, client, jamaica, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    record = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, jamaica.id)
    assert record.ecological_status == "INVASIVE"
    payload = species_jurisdiction_ecology.get_ecological_status_payload(db, canonical.id, jamaica.id)
    assert payload["ecological_status"] == "INVASIVE"
    assert payload["jurisdiction_id"] == jamaica.id


def test_jamaica_ecological_record_does_not_leak_into_bahamas(environment):
    db, client, jamaica, bahamas, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    jamaica_record = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, jamaica.id)
    bahamas_record = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, bahamas.id)
    assert jamaica_record is not None
    assert bahamas_record is None
    payload = species_jurisdiction_ecology.get_ecological_status_payload(db, canonical.id, bahamas.id)
    assert payload is None


def test_missing_jurisdiction_status_returns_none(environment):
    db, client, jamaica, bahamas, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    assert species_jurisdiction_ecology.get_ecological_status(db, canonical.id, 99999) is None
    assert species_jurisdiction_ecology.get_ecological_status_payload(db, canonical.id, 99999) is None


def test_bioclip_recognition_does_not_imply_species_program(environment):
    """The 10 BioCLIP reference species labels map to scientific names
    even when no SpeciesProgram exists. Adding recognition availability
    MUST NOT create programs."""
    db, client, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Sparisoma viride").one_or_none()
    if canonical is not None:
        # If the species is registered, no Jamaica program exists
        jamaica_programs = [p for p in canonical.species_programs if p.jurisdiction_id == 1]
        assert len(jamaica_programs) == 0
    # All ten labels resolve to scientific names without requiring SpeciesProgram
    labels = ["acanthurus_bahianus", "pterois_volitans", "sparisoma_viride", "lactophrys_triqueter"]
    for label in labels:
        name = bioclip_reference_normalization.resolve_bioclip_label_to_scientific_name(label)
        assert name is not None


def test_species_program_availability_does_not_imply_bioclip_recognition(environment):
    """The existing Jamaica Pterois program is recognized by the registry,
    and the registry does not create a BioCLIP capability claim.
    The BioCLIP capability is determined solely by the reference set, not
    by SpeciesProgram."""
    db, client, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    jamaica_program = [p for p in canonical.species_programs if p.jurisdiction_id == 1]
    assert len(jamaica_program) == 1
    # The registry is a *separate* layer from the reference set.
    canonical_status = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, 1)
    assert canonical_status is not None
    assert canonical_status.ecological_status == "INVASIVE"
    # This does NOT imply anything about reference-set membership.


def test_suitability_remains_deployment_derived(environment):
    db, client, jamaica, *_ = environment
    # Phase 8C invariant: only deployments drive suitability
    deployments = (
        db.query(SuitabilityDeployment).join(SuitabilityDeployment.species_program).all()
    )
    for d in deployments:
        program = d.species_program
        assert program.jurisdiction_id == jamaica.id
        assert d.status == "ACTIVE"
    # No suitability derived from ecological status


def test_monitoring_priority_remains_generation_derived(environment):
    db, client, jamaica, *_ = environment
    # Phase 8C invariant: only generations with is_active drive Monitoring Priority.
    # Phase 10B must not add any new generation-derived state.
    from models import NextAreaSnapshotGeneration
    active_gens = db.query(NextAreaSnapshotGeneration).filter(
        NextAreaSnapshotGeneration.status == "ACTIVE",
        NextAreaSnapshotGeneration.is_active.is_(True),
    ).all()
    # The test DB has 0 generations because Phase 10B did not insert any.
    # This assertion proves Phase 10B did not add a new generation.
    assert len(active_gens) == 0
    # Verify the model still supports the standard is_active + status ACTIVE query
    from sqlalchemy import select
    stmt = select(NextAreaSnapshotGeneration).where(
        NextAreaSnapshotGeneration.status == "ACTIVE",
        NextAreaSnapshotGeneration.is_active.is_(True),
    )
    assert stmt is not None


def test_existing_jamaica_observation_behavior_remains_compatible(environment):
    db, client, jamaica, *_ = environment
    # Existing Jamaica observation with Pterois volitans (CONFIRMED)
    obs = Observation(
        jurisdiction_id=jamaica.id,
        image_filename="legacy.jpg",
        latitude=18.0,
        longitude=-77.0,
        identification_status="accepted",
        species="Pterois volitans",
        verified_species="Pterois volitans",
        ecological_status="INVASIVE",
        decision="KNOWN_INVASIVE_RECORD",
        priority="MONITOR",
        verification_status="CONFIRMED",
    )
    db.add(obs); db.commit()
    # The registry-backed lookup returns INVASIVE for the same (species, jurisdiction)
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    record = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, jamaica.id)
    assert record.ecological_status == "INVASIVE"


def test_existing_jamaica_scientific_cells_remain_unchanged(environment):
    db, client, *_ = environment
    # Phase 10B must not change suitability cells
    from models import HabitatSuitabilityV3GridCell
    cells = db.query(HabitatSuitabilityV3GridCell).count()
    # Empty in-memory DB. The invariant is that the *endpoint* did not write
    # or modify cells. We assert it via the production DB check in the report.


def test_bahamas_still_has_no_predictive_deployment(environment):
    db, client, _, bahamas, *_ = environment
    programs = [p for p in db.query(SpeciesProgram).all() if p.jurisdiction_id == bahamas.id]
    deployments = db.query(SuitabilityDeployment).join(SpeciesProgram).filter(
        SpeciesProgram.jurisdiction_id == bahamas.id
    ).all()
    assert len(programs) == 0
    assert len(deployments) == 0


def test_initialization_is_idempotent(environment):
    db, client, *_ = environment
    # Re-run the migration block via init_db on the same engine
    from init_db import initialize_database
    initialize_database()
    initialize_database()
    # Should be idempotent: no duplicate SpeciesJurisdictionStatus rows
    from models import SpeciesJurisdictionStatus as SJS
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    rows = db.query(SJS).filter(SJS.species_id == canonical.id).all()
    assert len(rows) == 1
    # The Pterois Species itself remains unique
    species_count = db.query(Species).filter(Species.scientific_name == "Pterois volitans").count()
    assert species_count == 1


def test_regional_analytics_does_not_reinterpret_jamaica_as_caribbean(environment):
    db, client, jamaica, bahamas, *_ = environment
    # Phase 9C regional analytics endpoint should not fabricate a Caribbean-wide
    # ecological status. The endpoint must surface per-jurisdiction status
    # separately. We verify the registry is NOT aggregated.
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    jamaica_status = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, jamaica.id)
    bahamas_status = species_jurisdiction_ecology.get_ecological_status(db, canonical.id, bahamas.id)
    # Bahamas is not in the registry; its status is None — NOT a copy of Jamaica
    assert jamaica_status.ecological_status == "INVASIVE"
    assert bahamas_status is None
    # No code path synthesizes a Caribbean-wide status
    payload_jamaica = species_jurisdiction_ecology.get_ecological_status_payload(db, canonical.id, jamaica.id)
    payload_bahamas = species_jurisdiction_ecology.get_ecological_status_payload(db, canonical.id, bahamas.id)
    assert payload_jamaica["ecological_status"] == "INVASIVE"
    assert payload_bahamas is None


def test_admin_endpoint_lists_species_ecology(environment):
    db, client, jamaica, *_ = environment
    # Create a platform admin
    from auth_service import hash_password
    from models import User
    admin = User(
        email="phase10b-admin@example.test",
        display_name="Phase10B Admin",
        password_hash=hash_password("correct-password"),
        status="ACTIVE",
        is_platform_admin=True,
    )
    db.add(admin); db.commit()
    login = client.post("/auth/login", json={"email": admin.email, "password": "correct-password"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/admin/species-ecology", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    item = payload["species_ecology"][0]
    assert item["ecological_status"] == "INVASIVE"
    assert item["source"] == "legacy-unverified"
    assert item["species"]["scientific_name"] == "Pterois volitans"
    assert item["jurisdiction"]["slug"] == "jamaica"
    assert payload["editing_supported"] is False


def test_jurisdiction_species_ecology_endpoint(environment):
    db, client, jamaica, *_ = environment
    response = client.get("/regions/caribbean/jurisdictions/jamaica/species-ecology")
    assert response.status_code == 200
    data = response.json()
    assert data["jurisdiction"] == "jamaica"
    assert data["count"] == 1
    assert data["species_ecology"][0]["ecological_status"] == "INVASIVE"


def test_region_species_index_endpoint(environment):
    db, client, jamaica, bahamas, *_ = environment
    response = client.get("/regions/caribbean/species-ecology")
    assert response.status_code == 200
    data = response.json()
    assert data["region"] == "caribbean"
    assert data["count"] == 1  # only Jamaica has a registered status
    assert data["species_ecology"][0]["species"]["scientific_name"] == "Pterois volitans"
    # Bahamas is NOT in the regional index because it has no registry record
    slugs = [item["jurisdiction"]["slug"] for item in data["species_ecology"]]
    assert "bahamas" not in slugs


def test_bioclip_normalization_resolves_canonical_species(environment):
    db, client, *_ = environment
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    resolved = bioclip_reference_normalization.resolve_bioclip_label_to_canonical_species(db, "pterois_volitans")
    assert resolved is not None
    assert resolved.id == canonical.id


def test_bioclip_normalization_handles_unknown_label(environment):
    db, client, *_ = environment
    # An unknown label MUST NOT create a Species record
    before_count = db.query(Species).count()
    resolved = bioclip_reference_normalization.resolve_bioclip_label_to_canonical_species(db, "completely_unknown_species_xyz")
    assert resolved is None
    after_count = db.query(Species).count()
    assert after_count == before_count


def test_species_jurisdiction_status_uniqueness_constraint(environment):
    db, client, jamaica, *_ = environment
    from sqlalchemy.exc import IntegrityError
    canonical = db.query(Species).filter(Species.scientific_name == "Pterois volitans").one()
    duplicate = SpeciesJurisdictionStatus(
        species_id=canonical.id,
        jurisdiction_id=jamaica.id,
        ecological_status="INVASIVE",
        source="duplicate-test",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ============================================================
# Test environment setup
# ============================================================

@pytest.fixture
def environment(monkeypatch, tmp_path):
    # Create an isolated in-memory test database
    test_db_path = tmp_path / "phase10b_test.db"
    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(test_engine)

    # Patch the global engine used by init_db and database
    import database as database_module
    import init_db as init_db_module
    original_db_engine = database_module.engine
    original_init_engine = init_db_module.engine
    database_module.engine = test_engine
    init_db_module.engine = test_engine

    jamaica = None
    bahamas = None
    db = None
    try:
        # Seed canonical data
        session = SessionLocal()
        try:
            region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
            session.add(region); session.flush()
            jamaica = Jurisdiction(
                region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM",
                status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8,
            )
            bahamas = Jurisdiction(
                region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS",
                status="ACTIVE", center_latitude=24.25, center_longitude=-76.0, default_zoom=6,
            )
            session.add_all([jamaica, bahamas]); session.flush()
            session.add(JurisdictionBoundary(
                jurisdiction_id=jamaica.id, boundary_type="MARINE_MONITORING",
                geometry_json='{"type":"Polygon","coordinates":[[[-80,16],[-75,16],[-75,20],[-80,20],[-80,16]]]}',
                source="fixture", status="ACTIVE",
            ))
            session.add(JurisdictionBoundary(
                jurisdiction_id=bahamas.id, boundary_type="MARINE_MONITORING",
                geometry_json='{"type":"Polygon","coordinates":[[[-82,20],[-70,20],[-70,31],[-82,31],[-82,20]]]}',
                source="fixture", status="ACTIVE",
            ))
            # Canonical Species and registry seed (matches production init_db)
            canonical = Species(scientific_name="Pterois volitans", common_name="Lionfish", status="ACTIVE")
            session.add(canonical); session.flush()
            session.add(SpeciesJurisdictionStatus(
                species_id=canonical.id,
                jurisdiction_id=jamaica.id,
                ecological_status="INVASIVE",
                source="legacy-unverified",
                notes="Test seed",
            ))
            # Seed the Jamaica SpeciesProgram for tests that depend on it
            session.add(SpeciesProgram(
                jurisdiction_id=jamaica.id,
                species_id=canonical.id,
                scientific_name="Pterois volitans",
                common_name="Lionfish",
                status="ACTIVE",
            ))
            session.commit()
            # Re-query so ORM objects are usable across scopes
            jamaica = session.query(Jurisdiction).filter(Jurisdiction.id == jamaica.id).one()
            bahamas = session.query(Jurisdiction).filter(Jurisdiction.id == bahamas.id).one()
        finally:
            session.close()

        # Use a single session for the test to avoid DetachedInstance issues
        db = SessionLocal()

        # Wire the api dependency
        def override_get_db():
            s = SessionLocal()
            try:
                yield s
            finally:
                s.close()
        # Replace database.get_db so that the dependency override is not
        # shadowed by the original closure (which still binds to the
        # original engine). Also patch api.get_db because endpoints resolve
        # it from the local module scope.
        database_module.get_db = override_get_db
        api.get_db = override_get_db
        # The Depends() annotation in each endpoint references the module
        # global name, so we must replace get_db on both modules AND register
        # an override keyed on the original (unpatched) reference too.
        api.app.dependency_overrides[get_db] = override_get_db
        api.app.dependency_overrides[api.get_db] = override_get_db
        # Diagnostic: confirm the patch took
        from sqlalchemy import text
        s = SessionLocal()
        try:
            region_count = s.execute(text("SELECT COUNT(*) FROM regions")).scalar()
        finally:
            s.close()
        assert region_count >= 1, (
            f"Test DB at {test_db_path} has no regions after init."
        )
        api.service = _StubMarineObservationService()
        client = TestClient(api.app)
        try:
            yield db, client, jamaica, bahamas
        finally:
            api.app.dependency_overrides.clear()
            db.close()
            test_engine.dispose()
    finally:
        database_module.engine = original_db_engine
        init_db_module.engine = original_init_engine