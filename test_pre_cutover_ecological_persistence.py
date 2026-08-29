import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base
from ecological_status_governance import EcologicalStatusGovernanceService
from models import (
    EcologicalStatusAssertion,
    Jurisdiction,
    Region,
    RegionalTaxonRegistry,
    Species,
    User,
)


def _prove_persistence(engine):
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    suffix = uuid.uuid4().hex[:10]
    admin = User(
        email=f"ecological-{suffix}@test.invalid",
        display_name="Ecological persistence test",
        password_hash="x",
        is_platform_admin=True,
    )
    region = Region(name=f"Test region {suffix}", slug=f"region-{suffix}", status="ACTIVE")
    session.add_all([admin, region]); session.flush()
    jurisdiction = Jurisdiction(
        region_id=region.id, name=f"Test jurisdiction {suffix}", slug=f"jurisdiction-{suffix}",
        country_code="ZZ", status="ACTIVE", center_latitude=0, center_longitude=0,
        default_zoom=4,
    )
    taxon = Species(
        scientific_name=f"Test species {suffix}", taxonomic_rank="SPECIES",
        accepted_name_status="ACCEPTED", provenance_fingerprint=uuid.uuid4().hex * 2,
    )
    session.add_all([jurisdiction, taxon]); session.flush()
    session.add(RegionalTaxonRegistry(
        region_id=region.id, taxon_id=taxon.id, registry_version="test-v1",
        inclusion_basis="controlled persistence test", source_references_json="[]",
        review_status="APPROVED", provenance_json="{}",
        provenance_fingerprint=uuid.uuid4().hex * 2,
    )); session.commit()
    payload = {
        "jurisdiction_id": jurisdiction.id,
        "source_organization": "Controlled test source",
        "source_title": "Controlled ecological persistence test",
        "source_reference": "https://test.invalid/ecological-persistence",
        "evidence_type": "EXPERT_REVIEW",
        "authority_classification": "AUTHORITATIVE_FOR_JURISDICTION",
        "geographic_scope": {"type": "JURISDICTION", "jurisdiction_id": jurisdiction.id},
        "limitations": ["Synthetic disposable test record."],
        "assertions": [{"scientific_name": taxon.scientific_name, "statuses": ["PRESENT"]}],
    }
    service = EcologicalStatusGovernanceService(session)
    prepared = service.prepare(payload, admin.id)
    service.approve(prepared["id"], [prepared["candidates"][0]["id"]], admin.id, "controlled-test")
    result = service.apply(prepared["id"])
    assert result["apply_status"] == "APPLIED"
    assert service.apply(prepared["id"])["apply_status"] == "NO-OP"
    jurisdiction_id, taxon_id = jurisdiction.id, taxon.id
    session.close()
    fresh = Session()
    assert fresh.query(EcologicalStatusAssertion).filter_by(jurisdiction_id=jurisdiction_id, taxon_id=taxon_id).count() == 1
    assert EcologicalStatusGovernanceService(fresh).projection(jurisdiction_id, taxon_id)["statuses"] == ["PRESENT"]
    fresh.close()


def test_ecological_assertion_persists_in_memory_sqlite():
    _prove_persistence(create_engine("sqlite:///:memory:"))


def test_ecological_assertion_persists_file_backed_sqlite(tmp_path):
    _prove_persistence(create_engine(f"sqlite:///{tmp_path / 'ecological.db'}"))


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL is required")
def test_ecological_assertion_persists_postgresql():
    root = create_engine(os.environ["TEST_POSTGRES_URL"])
    schema = f"ecological_test_{uuid.uuid4().hex[:12]}"
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(os.environ["TEST_POSTGRES_URL"], connect_args={"options": f"-csearch_path={schema}"})
    try:
        _prove_persistence(engine)
    finally:
        engine.dispose()
        with root.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()
