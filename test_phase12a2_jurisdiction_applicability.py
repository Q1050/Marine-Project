"""Focused Phase 12A-2 identity and role-isolation tests."""

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

from anomaly_evidence_readiness import EvidenceReadinessResolver
from anomaly_geographic_evidence import GeographicEvidenceService
from models import Jurisdiction, ScientificDataset, ScientificDatasetApplicability
from phase12a2_migrate_jurisdiction_applicability import run_migration
from scientific_applicability_domain import ApplicabilityStatus, EvidenceRole
from scientific_dataset_applicability import (
    create_applicability,
    dataset_is_jurisdiction_compatible,
    supersede_applicability,
)
from test_phase11b2_evidence_readiness import add_observation, context


def _regional(db, region, species, slug="regional"):
    row = ScientificDataset(
        slug=slug, name=slug, dataset_type="OCCURRENCE", species_id=species.id,
        geographic_scope_type="REGION", region_id=region.id,
        source_name="Provider", source_version="v1", record_count=1,
    )
    db.add(row); db.flush()
    return row


def _authorize(db, dataset, jurisdiction, role, marker="one"):
    return create_applicability(
        db, scientific_dataset_id=dataset.id, jurisdiction_id=jurisdiction.id,
        evidence_role=role, applicability_status=ApplicabilityStatus.AUTHORIZED,
        reconciliation_method="BOUNDARY_REVIEW", reconciliation_version="v1",
        provenance_reference="phase12a2-test", provenance={"marker": marker},
    )


def test_canonical_identity_and_uniqueness(context):
    db, region, jamaica, _, _ = context
    jamaica.canonical_identifier_scheme = "ISO_3166_1_ALPHA_2"
    jamaica.canonical_identifier = "JM"
    jamaica.jurisdiction_type = "SOVEREIGN_STATE"
    db.commit()
    duplicate = Jurisdiction(
        region_id=region.id, name="Duplicate", slug="duplicate", country_code="XX",
        canonical_identifier_scheme="ISO_3166_1_ALPHA_2", canonical_identifier="JM",
        jurisdiction_type="OTHER_OPERATIONAL_JURISDICTION",
        center_latitude=0, center_longitude=0, default_zoom=4,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_third_jurisdiction_role_isolation(context):
    db, region, jamaica, bahamas, species = context
    third = Jurisdiction(
        region_id=region.id, name="Test Territory", slug="test-territory", country_code="TT",
        canonical_identifier_scheme="TEST_SCHEME", canonical_identifier="TEST-001",
        jurisdiction_type="OTHER_OPERATIONAL_JURISDICTION",
        center_latitude=15, center_longitude=-70, default_zoom=6,
    )
    db.add(third); db.flush()
    jamaica_dataset = db.query(ScientificDataset).filter_by(slug="jamaica-occ").one()
    regional = _regional(db, region, species)
    assert not dataset_is_jurisdiction_compatible(db, jamaica_dataset, third, EvidenceRole.OCCURRENCE_HISTORY)
    assert not dataset_is_jurisdiction_compatible(db, regional, third, EvidenceRole.OCCURRENCE_HISTORY)
    _authorize(db, regional, third, EvidenceRole.ENVIRONMENTAL_COVARIATE)
    db.commit()
    assert dataset_is_jurisdiction_compatible(db, regional, third, EvidenceRole.ENVIRONMENTAL_COVARIATE)
    assert not dataset_is_jurisdiction_compatible(db, regional, third, EvidenceRole.OCCURRENCE_HISTORY)
    assert not dataset_is_jurisdiction_compatible(db, regional, jamaica, EvidenceRole.ENVIRONMENTAL_COVARIATE)
    assert not dataset_is_jurisdiction_compatible(db, regional, bahamas, EvidenceRole.ENVIRONMENTAL_COVARIATE)


def test_readiness_refuses_region_then_accepts_only_occurrence_role(context):
    db, region, _, bahamas, species = context
    regional = _regional(db, region, species)
    observation = add_observation(db, bahamas)
    first = EvidenceReadinessResolver(db).resolve(observation)
    _authorize(db, regional, bahamas, EvidenceRole.ENVIRONMENTAL_COVARIATE)
    db.commit()
    wrong_role = EvidenceReadinessResolver(db).resolve(observation)
    assert regional.id not in wrong_role.compatible_dataset_ids
    assert wrong_role.dependency_fingerprint == first.dependency_fingerprint
    _authorize(db, regional, bahamas, EvidenceRole.OCCURRENCE_HISTORY, marker="occurrence")
    db.commit()
    authorized = EvidenceReadinessResolver(db).resolve(observation)
    assert regional.id in authorized.compatible_dataset_ids
    assert authorized.dependency_fingerprint != first.dependency_fingerprint


def test_geographic_evidence_requires_geographic_role(context):
    db, region, jamaica, _, species = context
    regional = _regional(db, region, species)
    observation = add_observation(db, jamaica)
    _authorize(db, regional, jamaica, EvidenceRole.OCCURRENCE_HISTORY)
    db.commit()
    assert regional.id not in GeographicEvidenceService(db, .1).evaluate_observation(observation.id).occurrence_dataset_ids
    _authorize(db, regional, jamaica, EvidenceRole.GEOGRAPHIC_EVIDENCE, marker="geo")
    db.commit()
    assert regional.id in GeographicEvidenceService(db, .1).evaluate_observation(observation.id).occurrence_dataset_ids


def test_assertion_is_immutable_and_supersession_is_auditable(context):
    db, region, jamaica, _, species = context
    regional = _regional(db, region, species)
    row = _authorize(db, regional, jamaica, EvidenceRole.ENVIRONMENTAL_COVARIATE)
    db.commit()
    row.reconciliation_method = "CHANGED"
    with pytest.raises(ValueError): db.commit()
    db.rollback()
    row = db.get(ScientificDatasetApplicability, row.id)
    supersede_applicability(db, row); db.commit()
    assert row.applicability_status == "SUPERSEDED" and row.superseded_at is not None


def test_migration_is_idempotent_and_backfills_only_existing_jamaica_relationship():
    db = sqlite3.connect(":memory:")
    db.executescript("""
      CREATE TABLE regions(id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE jurisdictions(id INTEGER PRIMARY KEY, region_id INTEGER, name TEXT, country_code TEXT);
      CREATE TABLE jurisdiction_boundaries(id INTEGER PRIMARY KEY, jurisdiction_id INTEGER);
      CREATE TABLE scientific_datasets(id INTEGER PRIMARY KEY, slug TEXT, geographic_scope_type TEXT);
      INSERT INTO regions VALUES(1,'Caribbean');
      INSERT INTO jurisdictions VALUES(1,1,'Jamaica','JM');
      INSERT INTO jurisdictions VALUES(2,1,'Bahamas','BS');
      INSERT INTO scientific_datasets VALUES(1,'pterois-volitans-jamaica-obis-iNaturalist-2025-08','JURISDICTION');
      INSERT INTO scientific_datasets VALUES(2,'pterois-volitans-environmental-caribbean-grid-v2-environment-v1','REGION');
    """)
    first = run_migration(db); second = run_migration(db)
    assert first["identity_columns_added"] == 3
    assert second["identity_columns_added"] == 0
    assert db.execute("SELECT COUNT(*) FROM jurisdictions").fetchone()[0] == 2
    identities = db.execute("SELECT name,canonical_identifier FROM jurisdictions ORDER BY id").fetchall()
    assert identities == [("Jamaica", "JM"), ("Bahamas", "BS")]
    assertions = db.execute(
        "SELECT jurisdiction_id,evidence_role,applicability_status FROM scientific_dataset_applicabilities"
    ).fetchall()
    assert assertions == [(1, "ENVIRONMENTAL_COVARIATE", "AUTHORIZED")]
    assert second["jamaica_applicabilities_backfilled"] == 0
