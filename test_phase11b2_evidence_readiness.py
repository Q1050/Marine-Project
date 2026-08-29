"""Focused Phase 11B-2 evidence-readiness tests."""

import inspect as pyinspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from anomaly_evidence_readiness import (
    AvailabilityState,
    DuplicateState,
    EvidenceReadinessResolver,
    IdentitySource,
    dependency_fingerprint,
    resolve_observation_identity,
)
from database import Base
from models import (
    AnomalyAssessment,
    AnomalySignal,
    HabitatSuitabilityModel,
    Jurisdiction,
    Observation,
    Region,
    ScientificDataset,
    Species,
    SpeciesProgram,
    SuitabilityDeployment,
    TrainingRun,
)
from scientific_applicability_domain import ApplicabilityStatus, EvidenceRole
from scientific_dataset_applicability import create_applicability


@pytest.fixture()
def context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    region = Region(name="Caribbean", slug="caribbean")
    db.add(region)
    db.flush()
    jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", center_latitude=18, center_longitude=-77, default_zoom=8)
    bahamas = Jurisdiction(region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS", center_latitude=24, center_longitude=-76, default_zoom=6)
    species = Species(scientific_name="Pterois volitans")
    db.add_all([jamaica, bahamas, species])
    db.flush()
    jamaica_program = SpeciesProgram(jurisdiction_id=jamaica.id, species_id=species.id, scientific_name=species.scientific_name)
    db.add(jamaica_program)
    db.flush()
    db.add(ScientificDataset(
        slug="jamaica-occ", name="Jamaica occurrences", dataset_type="OCCURRENCE",
        species_id=species.id, geographic_scope_type="JURISDICTION",
        jurisdiction_id=jamaica.id, source_name="OBIS", source_version="v1",
        record_count=54,
    ))
    model = HabitatSuitabilityModel(
        model_version="suitability-v3", scientific_name=species.scientific_name,
        algorithm="test", feature_list_json="[]", training_generation_version="v2",
        training_sample_count=1, eligible_presence_count=1, eligible_background_count=0,
        spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}",
        artifact_path="artifact.bin",
    )
    db.add(model)
    db.flush()
    db.add(SuitabilityDeployment(
        species_program_id=jamaica_program.id, habitat_suitability_model_id=model.id,
        model_version=model.model_version, artifact_hash="abc123", status="ACTIVE",
    ))
    db.commit()
    yield db, region, jamaica, bahamas, species
    db.close()


def observation(jurisdiction, **overrides):
    values = dict(
        jurisdiction_id=jurisdiction.id, image_filename="sample.jpg", image_hash="image-hash",
        latitude=18.4, longitude=-77.1, identification_status="accepted",
        species="Pterois volitans", ecological_status="UNKNOWN", decision="REVIEW",
        priority="REVIEW", verification_status="PENDING",
    )
    values.update(overrides)
    return Observation(**values)


def add_observation(db, jurisdiction, **overrides):
    row = observation(jurisdiction, **overrides)
    db.add(row)
    db.commit()
    return row


def test_expert_identity_overrides_ai(context):
    db, _, jamaica, _, _ = context
    row = add_observation(db, jamaica, species="Wrong AI species", verification_status="CORRECTED", verified_species="Pterois volitans")
    identity = resolve_observation_identity(row)
    assert identity.species == "Pterois volitans"
    assert identity.source is IdentitySource.EXPERT_VERIFIED


def test_unresolved_identity_remains_unresolved(context):
    db, _, jamaica, _, _ = context
    row = add_observation(db, jamaica, identification_status="unresolved", species=None)
    identity = resolve_observation_identity(row)
    assert identity.species is None and identity.source is IdentitySource.UNRESOLVED


def test_existing_accepted_semantics_have_no_new_confidence_threshold(context):
    db, _, jamaica, _, _ = context
    row = add_observation(db, jamaica, score=0.01, identification_status="accepted")
    assert resolve_observation_identity(row).source is IdentitySource.ACCEPTED_AI


def test_jamaica_evidence_and_deployment_resolve_for_jamaica(context):
    db, _, jamaica, _, _ = context
    result = EvidenceReadinessResolver(db).resolve(add_observation(db, jamaica))
    assert result.occurrence_history_availability is AvailabilityState.AVAILABLE
    assert result.suitability_model_availability is AvailabilityState.AVAILABLE
    assert result.jurisdiction_compatibility is AvailabilityState.AVAILABLE


def test_jamaica_evidence_and_deployment_refused_for_bahamas(context):
    db, _, _, bahamas, _ = context
    result = EvidenceReadinessResolver(db).resolve(add_observation(db, bahamas))
    assert result.compatible_dataset_ids == ()
    assert result.occurrence_history_availability is AvailabilityState.UNAVAILABLE
    assert result.suitability_model_availability is AvailabilityState.UNAVAILABLE


def test_region_dataset_requires_explicit_role_applicability(context):
    db, region, _, bahamas, species = context
    row = add_observation(db, bahamas)
    initial = EvidenceReadinessResolver(db).resolve(row)
    assert initial.compatible_dataset_ids == ()
    regional = ScientificDataset(
        slug="caribbean-occ", name="Caribbean occurrences", dataset_type="OCCURRENCE",
        species_id=species.id, geographic_scope_type="REGION", region_id=region.id,
        source_name="OBIS", source_version="v2", record_count=10,
    )
    db.add(regional)
    db.flush()
    assert EvidenceReadinessResolver(db).resolve(row).compatible_dataset_ids == ()
    create_applicability(
        db, scientific_dataset_id=regional.id, jurisdiction_id=bahamas.id,
        evidence_role=EvidenceRole.OCCURRENCE_HISTORY,
        applicability_status=ApplicabilityStatus.AUTHORIZED,
        reconciliation_method="TEST", reconciliation_version="v1",
        provenance_reference="test", provenance={"assertion": "test"},
    )
    db.commit()
    resolved = EvidenceReadinessResolver(db).resolve(row)
    assert resolved.compatible_dataset_ids == (regional.id,)
    assert resolved.occurrence_history_availability is AvailabilityState.AVAILABLE


@pytest.mark.parametrize("fields", [
    {"is_possible_duplicate": True},
    {"duplicate_of_observation_id": 99},
])
def test_existing_duplicate_semantics_exclude_independent_evidence(context, fields):
    db, _, jamaica, _, _ = context
    result = EvidenceReadinessResolver(db).resolve(add_observation(db, jamaica, **fields))
    assert result.is_duplicate is True
    assert result.duplicate_status in {
        DuplicateState.POSSIBLE_DUPLICATE,
        DuplicateState.DUPLICATE_OF_OBSERVATION,
    }
    assert result.contributes_independent_evidence is False


def test_missing_evidence_is_not_normal_or_no_anomaly(context):
    db, _, _, bahamas, _ = context
    result = EvidenceReadinessResolver(db).resolve(add_observation(db, bahamas))
    assert result.occurrence_history_availability is AvailabilityState.UNAVAILABLE
    assert result.suitability_model_availability is AvailabilityState.UNAVAILABLE
    assert not hasattr(result, "overall_classification")


def test_fingerprint_is_deterministic_and_order_timestamp_insensitive():
    first = {"datasets": [{"id": 2}, {"id": 3}], "species": "Pterois", "metadata": {"a": 1, "b": 2}}
    reordered_keys = {"metadata": {"b": 2, "a": 1}, "species": "Pterois", "datasets": [{"id": 2}, {"id": 3}]}
    assert dependency_fingerprint(first) == dependency_fingerprint(reordered_keys)
    assert dependency_fingerprint(first) != dependency_fingerprint({**first, "species": "Other"})
    # Volatile timestamps are deliberately outside the fingerprint payload.
    assert dependency_fingerprint(first) == dependency_fingerprint(reordered_keys)


def test_resolver_fingerprint_changes_only_for_relevant_state(context):
    db, _, jamaica, _, _ = context
    row = add_observation(db, jamaica)
    resolver = EvidenceReadinessResolver(db)
    first = resolver.resolve(row).dependency_fingerprint
    row.created_at = row.created_at + timedelta(days=1)
    db.commit()
    assert resolver.resolve(row).dependency_fingerprint == first
    row.verification_status = "CONFIRMED"
    row.verified_species = "Pterois volitans"
    db.commit()
    assert resolver.resolve(row).dependency_fingerprint != first


def test_readiness_creates_no_anomaly_rows_and_mutates_no_protected_science(context):
    db, _, jamaica, _, _ = context
    row = add_observation(db, jamaica)
    before_observation = (row.species, row.verification_status, row.is_possible_duplicate)
    before_datasets = [(d.id, d.slug, d.record_count, d.artifact_sha256) for d in db.query(ScientificDataset).order_by(ScientificDataset.id)]
    before_deployments = [(d.id, d.model_version, d.artifact_hash, d.status) for d in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)]
    before_training = db.query(TrainingRun).count()
    EvidenceReadinessResolver(db).resolve(row)
    assert db.query(AnomalyAssessment).count() == 0
    assert db.query(AnomalySignal).count() == 0
    assert (row.species, row.verification_status, row.is_possible_duplicate) == before_observation
    assert [(d.id, d.slug, d.record_count, d.artifact_sha256) for d in db.query(ScientificDataset).order_by(ScientificDataset.id)] == before_datasets
    assert [(d.id, d.model_version, d.artifact_hash, d.status) for d in db.query(SuitabilityDeployment).order_by(SuitabilityDeployment.id)] == before_deployments
    assert db.query(TrainingRun).count() == before_training


def test_no_scoring_or_new_numeric_threshold_implementation():
    import anomaly_evidence_readiness

    source = pyinspect.getsource(anomaly_evidence_readiness)
    assert "anomaly_probability" not in source
    assert "OverallClassification" not in source
    assert "observation.score" not in source
    assert "distance_km" not in source
