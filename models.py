from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
    event,
    inspect as sa_inspect,
)
from sqlalchemy.orm import relationship

from database import Base


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    jurisdictions = relationship("Jurisdiction", back_populates="region")


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"
    __table_args__ = (
        UniqueConstraint("region_id", "slug", name="uq_jurisdiction_region_slug"),
        UniqueConstraint(
            "canonical_identifier_scheme", "canonical_identifier",
            name="uq_jurisdiction_canonical_identity",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    country_code = Column(String(2), nullable=False)
    canonical_identifier_scheme = Column(String(32), nullable=True)
    canonical_identifier = Column(String(64), nullable=True)
    jurisdiction_type = Column(String(48), nullable=True)
    sovereign_parent_id = Column(
        Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    center_latitude = Column(Float, nullable=False)
    center_longitude = Column(Float, nullable=False)
    default_zoom = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    region = relationship("Region", back_populates="jurisdictions")
    observations = relationship("Observation", back_populates="jurisdiction")
    organization_links = relationship("OrganizationJurisdiction", back_populates="jurisdiction")
    boundaries = relationship("JurisdictionBoundary", back_populates="jurisdiction")
    investigations = relationship("Investigation", back_populates="jurisdiction")
    field_visits = relationship("FieldVisit", back_populates="jurisdiction")
    species_programs = relationship("SpeciesProgram", back_populates="jurisdiction")
    dataset_applicabilities = relationship(
        "ScientificDatasetApplicability", back_populates="jurisdiction"
    )
    sovereign_parent = relationship("Jurisdiction", remote_side=[id], foreign_keys=[sovereign_parent_id])


class JurisdictionBoundary(Base):
    __tablename__ = "jurisdiction_boundaries"
    __table_args__ = (Index("uq_active_boundary_per_type","jurisdiction_id","boundary_type",unique=True,sqlite_where=text("status = 'ACTIVE'"),postgresql_where=text("status = 'ACTIVE'")),)

    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    boundary_type = Column(String, nullable=False)
    geometry_json = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    source_version = Column(String, nullable=True)
    source_reference = Column(String, nullable=True)
    provider_boundary_identifier = Column(String(128), nullable=True)
    crs = Column(String(64), nullable=True)
    source_artifact_reference = Column(String(512), nullable=True)
    source_artifact_sha256 = Column(String(64), nullable=True, index=True)
    geometry_hash = Column(String(64), nullable=True, index=True)
    acquisition_metadata_json = Column(Text, nullable=True)
    limitations_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    activated_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    predecessor_boundary_id = Column(
        Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    jurisdiction = relationship("Jurisdiction", back_populates="boundaries")
    predecessor = relationship("JurisdictionBoundary", remote_side=[id])


class ArtifactReference(Base):
    """Hash-addressed metadata for local or externally stored artifacts."""
    __tablename__ = "artifact_references"
    __table_args__ = (UniqueConstraint("sha256", name="uq_artifact_reference_sha256"),)
    id = Column(Integer, primary_key=True, index=True)
    local_path = Column(String(512), nullable=True)
    external_uri = Column(String(1024), nullable=True)
    sha256 = Column(String(64), nullable=False, index=True)
    media_type = Column(String(128), nullable=False)
    artifact_type = Column(String(64), nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    provider = Column(String(256), nullable=True)
    source_reference = Column(String(1024), nullable=True)
    availability_status = Column(String(32), nullable=False, default="AVAILABLE", server_default="AVAILABLE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class JurisdictionOnboardingRecord(Base):
    """Immutable administrative audit record for one onboarding action."""
    __tablename__ = "jurisdiction_onboarding_records"
    __table_args__ = (
        UniqueConstraint("manifest_fingerprint", "execution_mode", name="uq_onboarding_manifest_mode"),
    )
    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    manifest_version = Column(String(128), nullable=False)
    manifest_fingerprint = Column(String(64), nullable=False, index=True)
    canonical_identifier_scheme = Column(String(32), nullable=False)
    canonical_identifier = Column(String(64), nullable=False)
    boundary_id = Column(Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_artifact_reference_id = Column(Integer, ForeignKey("artifact_references.id", ondelete="RESTRICT"), nullable=True)
    boundary_source_sha256 = Column(String(64), nullable=False)
    geometry_sha256 = Column(String(64), nullable=False)
    action_performed = Column(String(32), nullable=False)
    execution_mode = Column(String(16), nullable=False)
    approval_state = Column(String(64), nullable=False)
    applied_at = Column(DateTime, nullable=True)
    operator_reference = Column(String(256), nullable=True)
    before_state_json = Column(Text, nullable=False)
    after_state_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    jurisdiction = relationship("Jurisdiction")
    boundary = relationship("JurisdictionBoundary")
    source_artifact_reference = relationship("ArtifactReference")


class JurisdictionOnboardingPreparation(Base):
    """Mutable prepare/review/approval workflow; successful apply writes immutable audit."""
    __tablename__ = "jurisdiction_onboarding_preparations"
    __table_args__ = (UniqueConstraint("manifest_fingerprint", name="uq_onboarding_preparation_manifest"),)
    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True)
    canonical_name = Column(String(256), nullable=False)
    canonical_identifier_scheme = Column(String(32), nullable=False)
    canonical_identifier = Column(String(64), nullable=False, index=True)
    jurisdiction_type = Column(String(48), nullable=False)
    sovereign_parent_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=True)
    manifest_version = Column(String(128), nullable=False)
    manifest_path = Column(String(512), nullable=False)
    manifest_json = Column(Text, nullable=False)
    manifest_fingerprint = Column(String(64), nullable=False, index=True)
    boundary_artifact_path = Column(String(512), nullable=False)
    boundary_provider = Column(String(256), nullable=False)
    provider_boundary_identifier = Column(String(128), nullable=False)
    boundary_source_sha256 = Column(String(64), nullable=False)
    geometry_sha256 = Column(String(64), nullable=False)
    workflow_state = Column(String(32), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    approval_reference = Column(String(256), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_dependency_fingerprint = Column(String(64), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    resulting_jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=True)
    resulting_boundary_id = Column(Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    organization_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    jurisdiction_links = relationship("OrganizationJurisdiction", back_populates="organization")
    memberships = relationship("OrganizationMembership", back_populates="organization")
    assigned_investigations = relationship("Investigation", back_populates="assigned_organization")
    field_visits = relationship("FieldVisit", back_populates="organization")


class OrganizationJurisdiction(Base):
    __tablename__ = "organization_jurisdictions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "jurisdiction_id",
            name="uq_organization_jurisdiction",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="jurisdiction_links")
    jurisdiction = relationship("Jurisdiction", back_populates="organization_links")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    is_platform_admin = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime, nullable=True)
    organization_name = Column(String(256), nullable=True)
    job_title = Column(String(256), nullable=True)

    memberships = relationship("OrganizationMembership", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user")
    created_investigations = relationship("Investigation", back_populates="created_by_user")
    recorded_field_visits = relationship("FieldVisit", back_populates="recorded_by_user")


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_organization_membership"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")


class Observation(Base):

    __tablename__ = "observations"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Nullable at the ORM/schema level for additive compatibility with legacy
    # prototype databases; initialization assigns all existing rows to Jamaica.
    jurisdiction_id = Column(
        Integer,
        ForeignKey("jurisdictions.id"),
        nullable=True,
        index=True,
    )

    jurisdiction = relationship("Jurisdiction", back_populates="observations")

    image_filename = Column(
        String,
        nullable=False,
    )

    image_hash = Column(
        String(64),
        nullable=True,
        index=True,
    )

    is_possible_duplicate = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    duplicate_of_observation_id = Column(
        Integer,
        nullable=True,
    )
    reporter_suggested_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="SET NULL"), nullable=True, index=True)
    reporter_suggested_scientific_name = Column(String(512), nullable=True)

    # Provenance describes the final reported sighting coordinate, not a
    # separately retained reporter/device location.
    location_accuracy_m = Column(Float, nullable=True)
    location_captured_at = Column(DateTime, nullable=True)
    location_source = Column(String, nullable=True)

    latitude = Column(
        Float,
        nullable=False,
    )

    longitude = Column(
        Float,
        nullable=False,
    )

    # ----------------------------
    # AI identification
    # ----------------------------

    identification_status = Column(
        String,
        nullable=False,
    )

    species = Column(
        String,
        nullable=True,
    )

    nearest_candidate = Column(
        String,
        nullable=True,
    )

    score = Column(
        Float,
        nullable=True,
    )

    margin = Column(
        Float,
        nullable=True,
    )

    # Keep complete candidate output
    candidates_json = Column(
        Text,
        nullable=True,
    )

    # ----------------------------
    # Regional analysis
    # ----------------------------

    regional_evidence_json = Column(
        Text,
        nullable=True,
    )

    ecological_status = Column(
        String,
        nullable=False,
        default="UNKNOWN",
    )

    decision = Column(
        String,
        nullable=False,
    )

    priority = Column(
        String,
        nullable=False,
    )

    reason = Column(
        Text,
        nullable=True,
    )

    # ----------------------------
    # Human verification
    # ----------------------------

    verification_status = Column(
        String,
        nullable=False,
        default="PENDING",
    )

    verified_species = Column(
        String,
        nullable=True,
    )

    verification_notes = Column(
        Text,
        nullable=True,
    )

    verified_at = Column(
        DateTime,
        nullable=True,
    )

    verified_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    # ----------------------------
    # Metadata
    # ----------------------------

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(
            timezone.utc
        ),
        nullable=False,
    )


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    objective = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="PLANNED", server_default="PLANNED", index=True)
    priority = Column(String, nullable=False, index=True)
    assigned_organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    source_type = Column(String, nullable=False, index=True)
    source_observation_id = Column(Integer, ForeignKey("observations.id"), nullable=True, index=True)
    source_observation_species = Column(String, nullable=True)
    source_observation_verification_status = Column(String, nullable=True)
    source_observation_created_at = Column(DateTime, nullable=True)
    source_prediction_generation_id = Column(Integer, ForeignKey("next_area_snapshot_generations.id"), nullable=True, index=True)
    source_prediction_cell_id = Column(String, nullable=True)
    source_prediction_version = Column(String, nullable=True)
    source_priority_score = Column(Float, nullable=True)
    source_priority_band = Column(String, nullable=True)
    source_generated_at = Column(DateTime, nullable=True)
    outcome_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    jurisdiction = relationship("Jurisdiction", back_populates="investigations")
    assigned_organization = relationship("Organization", back_populates="assigned_investigations")
    created_by_user = relationship("User", back_populates="created_investigations")
    source_observation = relationship("Observation", foreign_keys=[source_observation_id])
    field_visits = relationship("FieldVisit", back_populates="investigation")


class FieldVisit(Base):
    __tablename__ = "field_visits"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    visited_at = Column(DateTime, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    survey_method = Column(String, nullable=False)
    effort_duration_minutes = Column(Integer, nullable=False)
    area_description = Column(Text, nullable=True)
    conditions_notes = Column(Text, nullable=True)
    target_detection_status = Column(String, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    investigation = relationship("Investigation", back_populates="field_visits")
    jurisdiction = relationship("Jurisdiction", back_populates="field_visits")
    organization = relationship("Organization", back_populates="field_visits")
    recorded_by_user = relationship("User", back_populates="recorded_field_visits")
    observations = relationship("FieldObservation", back_populates="field_visit", cascade="all, delete-orphan")


class FieldObservation(Base):
    __tablename__ = "field_observations"

    id = Column(Integer, primary_key=True, index=True)
    field_visit_id = Column(Integer, ForeignKey("field_visits.id"), nullable=False, index=True)
    scientific_name = Column(String, nullable=False)
    count_observed = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    field_visit = relationship("FieldVisit", back_populates="observations")


class HistoricalOccurrence(Base):

    __tablename__ = "historical_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "deduplication_key",
            name="uq_historical_occurrence_source_key",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    scientific_name = Column(
        String,
        nullable=False,
        index=True,
    )

    taxon_id = Column(
        Integer,
        nullable=False,
    )

    latitude = Column(
        Float,
        nullable=False,
    )

    longitude = Column(
        Float,
        nullable=False,
    )

    event_date = Column(
        DateTime,
        nullable=True,
    )

    basis_of_record = Column(
        String,
        nullable=True,
    )

    dataset_name = Column(
        String,
        nullable=True,
    )

    occurrence_id = Column(
        String,
        nullable=True,
    )

    raw_source_id = Column(
        String,
        nullable=True,
    )

    source = Column(
        String,
        nullable=False,
        default="OBIS",
    )

    deduplication_key = Column(
        String,
        nullable=False,
    )

    imported_at = Column(
        DateTime,
        default=lambda: datetime.now(
            timezone.utc
        ),
        nullable=False,
    )

    dataset_id = Column(
        Integer,
        ForeignKey("scientific_datasets.id"),
        nullable=True,
        index=True,
    )

    dataset = relationship("ScientificDataset", back_populates="occurrence_links")


class HistoricalEnvironmentalFeature(Base):

    __tablename__ = "historical_environmental_features"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    historical_occurrence_id = Column(
        Integer,
        ForeignKey("historical_occurrences.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    sst = Column(
        Float,
        nullable=True,
    )

    salinity = Column(
        Float,
        nullable=True,
    )

    depth = Column(
        Float,
        nullable=True,
    )

    sst_source = Column(
        String,
        nullable=True,
    )

    salinity_source = Column(
        String,
        nullable=True,
    )

    depth_source = Column(
        String,
        nullable=True,
    )

    sst_distance_km = Column(
        Float,
        nullable=True,
    )

    salinity_distance_km = Column(
        Float,
        nullable=True,
    )

    depth_distance_km = Column(
        Float,
        nullable=True,
    )

    sst_sampling_method = Column(
        String,
        nullable=False,
        default="MISSING",
    )

    salinity_sampling_method = Column(
        String,
        nullable=False,
        default="MISSING",
    )

    depth_sampling_method = Column(
        String,
        nullable=False,
        default="MISSING",
    )

    depth_quality_flag = Column(
        String,
        nullable=False,
        default="MISSING",
    )

    feature_date = Column(
        DateTime,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(
            timezone.utc
        ),
        nullable=False,
    )


class PredictionTrainingOccurrence(Base):

    __tablename__ = "prediction_training_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "deduplication_key",
            name="uq_prediction_training_occurrence_source_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    taxon_id = Column(Integer, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    event_date = Column(DateTime, nullable=True)
    occurrence_id = Column(String, nullable=True)
    raw_source_id = Column(String, nullable=True)
    dataset_name = Column(String, nullable=True)
    basis_of_record = Column(String, nullable=True)
    country_or_region = Column(String, nullable=True)
    source = Column(String, nullable=False, default="OBIS")
    deduplication_key = Column(String, nullable=False)
    imported_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PredictionTrainingEnvironmentalFeature(Base):

    __tablename__ = "prediction_training_environmental_features"

    id = Column(Integer, primary_key=True, index=True)
    prediction_training_occurrence_id = Column(
        Integer,
        ForeignKey("prediction_training_occurrences.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    sst = Column(Float, nullable=True)
    salinity = Column(Float, nullable=True)
    depth = Column(Float, nullable=True)
    sst_source = Column(String, nullable=True)
    salinity_source = Column(String, nullable=True)
    depth_source = Column(String, nullable=True)
    sst_distance_km = Column(Float, nullable=True)
    salinity_distance_km = Column(Float, nullable=True)
    depth_distance_km = Column(Float, nullable=True)
    sst_sampling_method = Column(String, nullable=False, default="MISSING")
    salinity_sampling_method = Column(String, nullable=False, default="MISSING")
    depth_sampling_method = Column(String, nullable=False, default="MISSING")
    depth_quality_flag = Column(String, nullable=False, default="MISSING")
    feature_date = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PredictionModelSample(Base):

    __tablename__ = "prediction_model_samples"
    __table_args__ = (
        UniqueConstraint(
            "scientific_name",
            "grid_cell_id",
            "generation_version",
            name="uq_prediction_model_sample_species_grid_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    grid_cell_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    sample_type = Column(String, nullable=False, index=True)
    occurrence_count = Column(Integer, nullable=False, default=0)
    unique_location_count = Column(Integer, nullable=False, default=0)
    earliest_occurrence_date = Column(DateTime, nullable=True)
    latest_occurrence_date = Column(DateTime, nullable=True)
    depth = Column(Float, nullable=True)
    sst = Column(Float, nullable=True)
    salinity = Column(Float, nullable=True)
    depth_source = Column(String, nullable=True)
    sst_source = Column(String, nullable=True)
    salinity_source = Column(String, nullable=True)
    depth_sampling_method = Column(String, nullable=False, default="MISSING")
    marine_filter_source = Column(String, nullable=True)
    generation_version = Column(String, nullable=False)
    generation_seed = Column(Integer, nullable=False)
    background_ratio = Column(Float, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PredictionModelDatasetGeneration(Base):

    __tablename__ = "prediction_model_dataset_generations"
    __table_args__ = (
        UniqueConstraint(
            "scientific_name",
            "generation_version",
            name="uq_prediction_model_generation_species_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    generation_version = Column(String, nullable=False)
    generation_seed = Column(Integer, nullable=False)
    background_ratio = Column(Float, nullable=False)
    grid_size = Column(Float, nullable=False)
    training_region = Column(String, nullable=False)
    marine_filter_source = Column(String, nullable=False)
    terrestrial_candidates_rejected = Column(Integer, nullable=False, default=0)
    unavailable_candidates_rejected = Column(Integer, nullable=False, default=0)
    presence_candidates_rejected = Column(Integer, nullable=False, default=0)
    candidates_evaluated = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class HabitatSuitabilityModel(Base):

    __tablename__ = "habitat_suitability_models"
    __table_args__ = (
        UniqueConstraint(
            "model_version",
            name="uq_habitat_suitability_model_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String, nullable=False)
    scientific_name = Column(String, nullable=False, index=True)
    algorithm = Column(String, nullable=False)
    feature_list_json = Column(Text, nullable=False)
    training_generation_version = Column(String, nullable=False)
    training_sample_count = Column(Integer, nullable=False)
    eligible_presence_count = Column(Integer, nullable=False)
    eligible_background_count = Column(Integer, nullable=False)
    spatial_block_count = Column(Integer, nullable=False)
    validation_metrics_json = Column(Text, nullable=False)
    coefficients_json = Column(Text, nullable=False)
    artifact_path = Column(String, nullable=False)
    trained_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Species(Base):
    __tablename__ = "species"
    __table_args__ = (
        UniqueConstraint("scientific_name", name="uq_species_scientific_name"),
        UniqueConstraint("authoritative_identifier_scheme", "authoritative_identifier", name="uq_species_authoritative_identity"),
        Index("uq_species_aphia_id","aphia_id",unique=True,sqlite_where=text("aphia_id IS NOT NULL"),postgresql_where=text("aphia_id IS NOT NULL")),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    common_name = Column(String, nullable=True)
    aphia_id = Column(Integer, nullable=True)
    taxonomic_rank = Column(String(32), nullable=True)
    authoritative_identifier_scheme = Column(String(64), nullable=True)
    authoritative_identifier = Column(String(128), nullable=True)
    accepted_name_status = Column(String(32), nullable=True)
    accepted_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True)
    parent_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True)
    authorship = Column(String(256), nullable=True)
    taxonomic_provenance_json = Column(Text, nullable=True)
    provenance_version = Column(String(128), nullable=True)
    provenance_fingerprint = Column(String(64), nullable=True, index=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    species_programs = relationship("SpeciesProgram", back_populates="species")
    jurisdiction_statuses = relationship("SpeciesJurisdictionStatus", back_populates="species", cascade="all, delete-orphan")
    accepted_taxon = relationship("Species", remote_side=[id], foreign_keys=[accepted_taxon_id])
    parent_taxon = relationship("Species", remote_side=[id], foreign_keys=[parent_taxon_id])
    regional_registry_entries = relationship("RegionalTaxonRegistry", back_populates="taxon")


class RegionalTaxonRegistry(Base):
    """Versioned governance inclusion; never jurisdiction presence or ecology."""
    __tablename__ = "regional_taxon_registry"
    __table_args__ = (
        UniqueConstraint("region_id", "taxon_id", "registry_version", name="uq_regional_taxon_registry_version"),
        UniqueConstraint("provenance_fingerprint", name="uq_regional_taxon_registry_fingerprint"),
    )
    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    registry_version = Column(String(128), nullable=False)
    inclusion_basis = Column(String(128), nullable=False)
    source_references_json = Column(Text, nullable=False)
    review_status = Column(String(24), nullable=False, default="CANDIDATE", server_default="CANDIDATE", index=True)
    reviewed_by = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_by = Column(String(256), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    provenance_json = Column(Text, nullable=False)
    provenance_fingerprint = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    superseded_at = Column(DateTime, nullable=True)
    region = relationship("Region")
    taxon = relationship("Species", back_populates="regional_registry_entries")


class TaxonomyPreparation(Base):
    """Controlled provider reconciliation and approval snapshot."""
    __tablename__ = "taxonomy_preparations"
    __table_args__ = (UniqueConstraint("preparation_fingerprint", name="uq_taxonomy_preparation_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider = Column(String(64), nullable=False)
    authoritative_identifier_scheme = Column(String(64), nullable=False)
    authoritative_identifier = Column(String(128), nullable=False)
    raw_artifact_reference = Column(String(512), nullable=False)
    raw_artifact_sha256 = Column(String(64), nullable=False)
    proposed_scientific_name = Column(String(256), nullable=False)
    proposed_rank = Column(String(32), nullable=False)
    proposed_accepted_name_status = Column(String(32), nullable=False)
    proposed_accepted_identifier = Column(String(128), nullable=True)
    proposed_parent_identifier = Column(String(128), nullable=True)
    proposed_authorship = Column(String(256), nullable=True)
    reconciliation_result = Column(String(24), nullable=False)
    limitations_json = Column(Text, nullable=False)
    manifest_json = Column(Text, nullable=False)
    preparation_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(24), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    prepared_by = Column(String(256), nullable=False)
    prepared_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approval_reference = Column(String(256), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_dependency_fingerprint = Column(String(64), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    registry_entry_id = Column(Integer, ForeignKey("regional_taxon_registry.id", ondelete="RESTRICT"), nullable=True)
    last_error = Column(Text, nullable=True)
    taxon = relationship("Species")
    region = relationship("Region")
    registry_entry = relationship("RegionalTaxonRegistry")


class LocalTaxonCandidate(Base):
    __tablename__ = "local_taxon_candidates"
    __table_args__ = (UniqueConstraint("dependency_fingerprint", name="uq_local_taxon_candidate_fingerprint"),)
    id=Column(Integer,primary_key=True,index=True); region_id=Column(Integer,ForeignKey("regions.id",ondelete="RESTRICT"),nullable=False,index=True)
    submitted_scientific_name=Column(String(256),nullable=False); submitted_identifier_scheme=Column(String(64),nullable=True); submitted_identifier=Column(String(128),nullable=True)
    canonical_scientific_name=Column(String(256),nullable=False); authorship=Column(String(256),nullable=True); taxonomic_rank=Column(String(32),nullable=False)
    authoritative_identifier_scheme=Column(String(64),nullable=False); authoritative_identifier=Column(String(128),nullable=False,index=True)
    accepted_name_status=Column(String(32),nullable=False); accepted_authoritative_identifier=Column(String(128),nullable=True); parent_authoritative_identifier=Column(String(128),nullable=True); parent_name=Column(String(256),nullable=True)
    provider=Column(String(64),nullable=False); provider_version=Column(String(128),nullable=False); provider_source_reference=Column(String(512),nullable=False)
    provider_artifact_reference=Column(String(512),nullable=False); provider_artifact_sha256=Column(String(64),nullable=False); provider_content_fingerprint=Column(String(64),nullable=False)
    candidate_source=Column(String(128),nullable=False); candidate_provenance_json=Column(Text,nullable=False); reconciliation_result=Column(String(24),nullable=False); limitations_json=Column(Text,nullable=False)
    dependency_fingerprint=Column(String(64),nullable=False,index=True); workflow_status=Column(String(24),nullable=False,default="READY_FOR_REVIEW",server_default="READY_FOR_REVIEW",index=True)
    created_by=Column(String(256),nullable=False); created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc)); reviewed_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=True); reviewed_at=Column(DateTime,nullable=True)
    approval_reference=Column(String(256),nullable=True); approved_dependency_fingerprint=Column(String(64),nullable=True); applied_at=Column(DateTime,nullable=True); resulting_species_id=Column(Integer,ForeignKey("species.id",ondelete="RESTRICT"),nullable=True); resulting_registry_entry_id=Column(Integer,ForeignKey("regional_taxon_registry.id",ondelete="RESTRICT"),nullable=True); last_error=Column(Text,nullable=True)


class RegionalTaxonManifestRun(Base):
    """Operational audit record; a manifest is review input, never occurrence evidence."""
    __tablename__ = "regional_taxon_manifest_runs"
    __table_args__ = (UniqueConstraint("manifest_fingerprint", name="uq_regional_taxon_manifest_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    manifest_id = Column(String(128), nullable=False)
    manifest_version = Column(String(64), nullable=False)
    manifest_fingerprint = Column(String(64), nullable=False, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True)
    operator_reference = Column(String(256), nullable=False)
    provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    canonical_manifest_json = Column(Text, nullable=False)
    execution_state = Column(String(24), nullable=False, default="PREPARED", server_default="PREPARED", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    firewall_report_json = Column(Text, nullable=True)


class RegionalTaxonManifestItem(Base):
    __tablename__ = "regional_taxon_manifest_items"
    __table_args__ = (UniqueConstraint("manifest_run_id", "item_key", name="uq_regional_taxon_manifest_item"),)
    id = Column(Integer, primary_key=True, index=True)
    manifest_run_id = Column(Integer, ForeignKey("regional_taxon_manifest_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    item_key = Column(String(256), nullable=False)
    ordinal = Column(Integer, nullable=False)
    submitted_identity_json = Column(Text, nullable=False)
    resolution_json = Column(Text, nullable=True)
    proposed_action = Column(String(48), nullable=False, index=True)
    workflow_state = Column(String(24), nullable=False, default="PREPARED", server_default="PREPARED", index=True)
    preparation_id = Column(Integer, ForeignKey("taxonomy_preparations.id", ondelete="RESTRICT"), nullable=True)
    local_taxon_candidate_id = Column(Integer, ForeignKey("local_taxon_candidates.id", ondelete="RESTRICT"), nullable=True)
    species_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True)
    registry_entry_id = Column(Integer, ForeignKey("regional_taxon_registry.id", ondelete="RESTRICT"), nullable=True)
    approval_reference = Column(String(256), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class OccurrenceAcquisitionPreparation(Base):
    """Governed jurisdiction/taxon/source acquisition snapshot; not ecological status."""
    __tablename__ = "occurrence_acquisition_preparations"
    __table_args__ = (UniqueConstraint("dependency_fingerprint", name="uq_occurrence_preparation_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_registration_id = Column(Integer, ForeignKey("occurrence_source_registrations.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_key = Column(String(128), nullable=False, index=True)
    scientific_provider = Column(String(256), nullable=False)
    transport_interface = Column(String(128), nullable=True)
    provider_dataset_id = Column(String(256), nullable=False)
    provider_dataset_version = Column(String(128), nullable=True)
    source_reference = Column(String(512), nullable=False)
    license_json = Column(Text, nullable=False)
    acquisition_parameters_json = Column(Text, nullable=False)
    declared_extent_json = Column(Text, nullable=False)
    ownership_scope_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    raw_artifact_reference = Column(String(512), nullable=False)
    raw_artifact_sha256 = Column(String(64), nullable=False)
    normalized_content_fingerprint = Column(String(64), nullable=False)
    boundary_id = Column(Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"), nullable=False)
    boundary_geometry_hash = Column(String(64), nullable=False)
    boundary_source_artifact_sha256 = Column(String(64), nullable=True)
    dependency_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(24), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    prepared_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    prepared_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approval_reference = Column(String(256), nullable=True)
    approved_dependency_fingerprint = Column(String(64), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    scientific_dataset_id = Column(Integer, ForeignKey("scientific_datasets.id", ondelete="RESTRICT"), nullable=True)
    last_error = Column(Text, nullable=True)
    provenance_json = Column(Text, nullable=False)
    firewall_report_json = Column(Text, nullable=True)


class OccurrenceSourceRegistration(Base):
    """Reviewed acquisition configuration; never blanket evidence authorization."""
    __tablename__ = "occurrence_source_registrations"
    __table_args__ = (UniqueConstraint("configuration_fingerprint", name="uq_occurrence_source_configuration_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    source_registration_id = Column(String(128), nullable=False, index=True)
    source_name = Column(String(256), nullable=False)
    scientific_provider = Column(String(256), nullable=False)
    transport_interface = Column(String(128), nullable=True)
    provider_dataset_id = Column(String(256), nullable=True)
    provider_dataset_version = Column(String(128), nullable=True)
    acquisition_mechanism = Column(String(64), nullable=False)
    documentation_reference = Column(String(512), nullable=False)
    license = Column(String(256), nullable=False)
    reuse_conditions = Column(Text, nullable=False)
    geographic_scope_json = Column(Text, nullable=False)
    taxonomic_scope_json = Column(Text, nullable=False)
    source_provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    configuration_json = Column(Text, nullable=False)
    configuration_version = Column(String(64), nullable=False)
    configuration_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(24), nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approval_reference = Column(String(256), nullable=True)
    approved_configuration_fingerprint = Column(String(64), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    predecessor_id = Column(Integer, ForeignKey("occurrence_source_registrations.id", ondelete="RESTRICT"), nullable=True)


class OccurrenceCandidateRecord(Base):
    __tablename__ = "occurrence_candidate_records"
    __table_args__ = (UniqueConstraint("preparation_id", "provenance_fingerprint", name="uq_occurrence_candidate_preparation_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("occurrence_acquisition_preparations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_occurrence_id = Column(String(512), nullable=True)
    upstream_occurrence_id = Column(String(512), nullable=True)
    event_id = Column(String(512), nullable=True)
    catalog_specimen_id = Column(String(512), nullable=True)
    observation_reference = Column(String(512), nullable=True)
    original_scientific_name = Column(String(512), nullable=True)
    reconciled_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True)
    taxonomy_reconciliation = Column(String(40), nullable=False, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    event_date = Column(DateTime, nullable=True)
    basis_of_record = Column(String(128), nullable=True)
    occurrence_status = Column(String(128), nullable=True)
    coordinate_uncertainty_m = Column(Float, nullable=True)
    depth_m = Column(Float, nullable=True)
    locality = Column(String(512), nullable=True)
    boundary_reconciliation = Column(String(32), nullable=False, index=True)
    boundary_id = Column(Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"), nullable=False)
    overlap_classification = Column(String(32), nullable=False, index=True)
    overlap_reason = Column(String(256), nullable=False)
    matching_evidence_ids_json = Column(Text, nullable=False)
    source_metadata_json = Column(Text, nullable=False)
    original_record_reference = Column(String(512), nullable=True)
    normalization_version = Column(String(64), nullable=False)
    provenance_fingerprint = Column(String(64), nullable=False, index=True)
    review_status = Column(String(32), nullable=False, default="PENDING_REVIEW", server_default="PENDING_REVIEW", index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    applied_evidence_id = Column(Integer, ForeignKey("governed_occurrence_evidence.id", ondelete="RESTRICT"), nullable=True)


class OccurrenceCandidateReview(Base):
    """Append-only scientific disposition of one acquisition candidate."""
    __tablename__ = "occurrence_candidate_reviews"
    __table_args__ = (UniqueConstraint("review_fingerprint", name="uq_occurrence_candidate_review_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("occurrence_acquisition_preparations.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("occurrence_candidate_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    disposition = Column(String(48), nullable=False, index=True)
    reason_code = Column(String(64), nullable=False)
    evidence_note = Column(Text, nullable=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    dependency_fingerprint = Column(String(64), nullable=False)
    source_license_json = Column(Text, nullable=False)
    provenance_json = Column(Text, nullable=False)
    review_fingerprint = Column(String(64), nullable=False, index=True)
    resulting_evidence_id = Column(Integer, ForeignKey("governed_occurrence_evidence.id", ondelete="RESTRICT"), nullable=True)


class OccurrenceLegacyLink(Base):
    """Immutable reconciliation link; it does not copy or reclassify legacy evidence."""
    __tablename__ = "occurrence_legacy_links"
    __table_args__ = (UniqueConstraint("candidate_id", "historical_occurrence_id", "overlap_basis", name="uq_occurrence_legacy_link"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("occurrence_acquisition_preparations.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("occurrence_candidate_records.id", ondelete="RESTRICT"), nullable=False, index=True)
    historical_occurrence_id = Column(Integer, ForeignKey("historical_occurrences.id", ondelete="RESTRICT"), nullable=False, index=True)
    overlap_basis = Column(String(128), nullable=False)
    provider_occurrence_id = Column(String(512), nullable=True)
    upstream_occurrence_id = Column(String(512), nullable=True)
    candidate_provenance_fingerprint = Column(String(64), nullable=False)
    link_fingerprint = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class GovernedOccurrenceEvidence(Base):
    """Accepted occurrence evidence only; never native/invasive/established status."""
    __tablename__ = "governed_occurrence_evidence"
    __table_args__ = (UniqueConstraint("evidence_fingerprint", name="uq_governed_occurrence_evidence_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("occurrence_acquisition_preparations.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_record_id = Column(Integer, ForeignKey("occurrence_candidate_records.id", ondelete="RESTRICT"), nullable=False, unique=True)
    scientific_dataset_id = Column(Integer, ForeignKey("scientific_datasets.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_occurrence_id = Column(String(512), nullable=True)
    upstream_occurrence_id = Column(String(512), nullable=True)
    event_id = Column(String(512), nullable=True)
    catalog_specimen_id = Column(String(512), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    event_date = Column(DateTime, nullable=True)
    basis_of_record = Column(String(128), nullable=True)
    boundary_id = Column(Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"), nullable=False)
    evidence_fingerprint = Column(String(64), nullable=False, index=True)
    provenance_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class GovernedPublicMedia(Base):
    __tablename__ = "governed_public_media"
    id = Column(Integer, primary_key=True, index=True)
    media_type = Column(String(48), nullable=False)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True, index=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_provider = Column(String(256), nullable=False)
    creator = Column(String(256), nullable=True)
    source_reference = Column(String(1024), nullable=False)
    license = Column(String(256), nullable=False)
    attribution_text = Column(Text, nullable=False)
    lifecycle_state = Column(String(24), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    public_visibility = Column(String(24), nullable=False, default="PRIVATE", server_default="PRIVATE", index=True)
    is_primary = Column(Boolean, nullable=False, default=False, server_default="0")
    remote_url = Column(String(2048), nullable=True)
    artifact_reference_id = Column(Integer, ForeignKey("artifact_references.id", ondelete="RESTRICT"), nullable=True)
    provenance_json = Column(Text, nullable=False, default="{}", server_default="{}")
    limitations_json = Column(Text, nullable=False, default="[]", server_default="[]")
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class IdentificationMediaSource(Base):
    """Governed provider configuration; registration is not asset approval."""
    __tablename__ = "identification_media_sources"
    __table_args__ = (UniqueConstraint("registration_key", "configuration_fingerprint", name="uq_identification_media_source_config"),)
    id = Column(Integer, primary_key=True, index=True)
    registration_key = Column(String(128), nullable=False, index=True)
    scientific_provider = Column(String(256), nullable=False)
    transport_interface = Column(String(128), nullable=True)
    documentation_reference = Column(String(1024), nullable=False)
    licensing_model = Column(String(256), nullable=False)
    attribution_requirements = Column(Text, nullable=False)
    access_method = Column(String(128), nullable=False)
    taxonomic_scope_json = Column(Text, nullable=False, default="{}", server_default="{}")
    geographic_scope_json = Column(Text, nullable=False, default="{}", server_default="{}")
    provider_version = Column(String(128), nullable=True)
    acquisition_configuration_json = Column(Text, nullable=False, default="{}", server_default="{}")
    provenance_json = Column(Text, nullable=False, default="{}", server_default="{}")
    limitations_json = Column(Text, nullable=False, default="[]", server_default="[]")
    configuration_fingerprint = Column(String(64), nullable=False, index=True)
    lifecycle_state = Column(String(32), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approval_reference = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    superseded_by_id = Column(Integer, ForeignKey("identification_media_sources.id", ondelete="RESTRICT"), nullable=True)


class IdentificationCorpus(Base):
    __tablename__ = "identification_corpora"
    __table_args__ = (UniqueConstraint("corpus_key", "version", name="uq_identification_corpus_version"), UniqueConstraint("fingerprint", name="uq_identification_corpus_fingerprint"))
    id = Column(Integer, primary_key=True, index=True)
    corpus_key = Column(String(128), nullable=False, index=True)
    version = Column(String(128), nullable=False)
    intended_purpose = Column(String(256), nullable=False)
    taxonomic_scope_json = Column(Text, nullable=False)
    lifecycle_state = Column(String(32), nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    configuration_json = Column(Text, nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approval_reference = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    approved_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)


class IdentificationMediaAsset(Base):
    __tablename__ = "identification_media_assets"
    __table_args__ = (
        UniqueConstraint("media_source_id", "provider_asset_identifier", name="uq_identification_provider_asset"),
        Index("ix_identification_asset_taxon_review", "taxon_id", "review_state"),
        Index("ix_identification_asset_sha256", "sha256"),
        Index("ix_identification_asset_source_event", "source_event_identifier"),
    )
    id = Column(Integer, primary_key=True, index=True)
    stable_asset_key = Column(String(256), nullable=False, unique=True, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    media_source_id = Column(Integer, ForeignKey("identification_media_sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider_asset_identifier = Column(String(512), nullable=False)
    source_reference = Column(String(2048), nullable=False)
    creator = Column(String(512), nullable=True)
    license_expression = Column(String(256), nullable=False)
    license_classification = Column(String(48), nullable=False, index=True)
    attribution_text = Column(Text, nullable=False)
    media_type = Column(String(128), nullable=False)
    artifact_reference_id = Column(Integer, ForeignKey("artifact_references.id", ondelete="RESTRICT"), nullable=True)
    sha256 = Column(String(64), nullable=True)
    width_px = Column(Integer, nullable=True); height_px = Column(Integer, nullable=True); size_bytes = Column(Integer, nullable=True)
    acquired_at = Column(DateTime, nullable=True)
    source_metadata_json = Column(Text, nullable=False, default="{}", server_default="{}")
    life_stage = Column(String(64), nullable=True); sex = Column(String(64), nullable=True); view_orientation = Column(String(128), nullable=True)
    biological_context = Column(String(64), nullable=True); locality = Column(String(512), nullable=True); event_date = Column(DateTime, nullable=True)
    source_event_identifier = Column(String(512), nullable=True); specimen_identifier = Column(String(512), nullable=True)
    taxonomic_linkage = Column(String(48), nullable=False); taxonomic_confidence_source = Column(String(256), nullable=True)
    quality_state = Column(String(48), nullable=False, default="NOT_VALIDATED", server_default="NOT_VALIDATED", index=True)
    quality_metadata_json = Column(Text, nullable=False, default="{}", server_default="{}")
    exact_duplicate_of_id = Column(Integer, ForeignKey("identification_media_assets.id", ondelete="RESTRICT"), nullable=True)
    perceptual_hash = Column(String(256), nullable=True); perceptual_hash_algorithm = Column(String(64), nullable=True); perceptual_group = Column(String(128), nullable=True)
    duplicate_state = Column(String(48), nullable=False, default="UNIQUE", server_default="UNIQUE", index=True)
    review_state = Column(String(32), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    exclusion_reason = Column(String(512), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(512), nullable=True); reviewed_at = Column(DateTime, nullable=True)
    provenance_fingerprint = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class IdentificationCorpusInclusion(Base):
    __tablename__ = "identification_corpus_inclusions"
    __table_args__ = (UniqueConstraint("corpus_id", "media_asset_id", name="uq_identification_corpus_asset"),)
    id = Column(Integer, primary_key=True, index=True)
    corpus_id = Column(Integer, ForeignKey("identification_corpora.id", ondelete="RESTRICT"), nullable=False, index=True)
    media_asset_id = Column(Integer, ForeignKey("identification_media_assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    split_name = Column(String(16), nullable=True, index=True)
    split_group_key = Column(String(512), nullable=True, index=True)
    split_version = Column(String(128), nullable=True)
    inclusion_state = Column(String(32), nullable=False, default="APPROVED", server_default="APPROVED", index=True)
    inclusion_fingerprint = Column(String(64), nullable=False, unique=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class IdentificationMediaAcquisitionRun(Base):
    __tablename__ = "identification_media_acquisition_runs"
    __table_args__ = (UniqueConstraint("run_fingerprint", name="uq_identification_media_acquisition_run"),)
    id = Column(Integer, primary_key=True, index=True)
    media_source_id = Column(Integer, ForeignKey("identification_media_sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    run_fingerprint = Column(String(64), nullable=False)
    request_json = Column(Text, nullable=False); provider_manifest_json = Column(Text, nullable=True)
    workflow_state = Column(String(32), nullable=False, default="PENDING", server_default="PENDING", index=True)
    claim_token = Column(String(64), nullable=True, unique=True); claimed_by = Column(String(256), nullable=True); claimed_at = Column(DateTime, nullable=True); lease_expires_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0, server_default="0"); last_error = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)); completed_at = Column(DateTime, nullable=True)


class IdentificationMediaReviewEvent(Base):
    __tablename__ = "identification_media_review_events"
    id=Column(Integer,primary_key=True,index=True); media_asset_id=Column(Integer,ForeignKey("identification_media_assets.id",ondelete="RESTRICT"),nullable=False,index=True)
    reviewer_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False); action=Column(String(48),nullable=False,index=True)
    prior_review_state=Column(String(32),nullable=False); current_review_state=Column(String(32),nullable=False); reason=Column(Text,nullable=False)
    license_state=Column(String(48),nullable=False); duplicate_state=Column(String(48),nullable=False); quality_state=Column(String(48),nullable=False)
    created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc))


class IdentificationBenchmarkRun(Base):
    __tablename__ = "identification_benchmark_runs"
    __table_args__=(UniqueConstraint("run_fingerprint",name="uq_identification_benchmark_run"),)
    id=Column(Integer,primary_key=True,index=True); model_identity=Column(String(256),nullable=False); model_hash=Column(String(64),nullable=True); model_version=Column(String(128),nullable=False)
    corpus_id=Column(Integer,ForeignKey("identification_corpora.id",ondelete="RESTRICT"),nullable=False,index=True); split_name=Column(String(16),nullable=False)
    inference_configuration_json=Column(Text,nullable=False); metrics_json=Column(Text,nullable=True); taxon_results_json=Column(Text,nullable=True); confusion_json=Column(Text,nullable=True); rejection_behavior_json=Column(Text,nullable=True)
    run_fingerprint=Column(String(64),nullable=False); workflow_state=Column(String(32),nullable=False,default="PREPARED",server_default="PREPARED");created_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False);created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc));completed_at=Column(DateTime,nullable=True)


class OccurrenceAcquisitionBatch(Base):
    __tablename__="occurrence_acquisition_batches";__table_args__=(UniqueConstraint("batch_fingerprint",name="uq_occurrence_batch_fingerprint"),)
    id=Column(Integer,primary_key=True,index=True);batch_key=Column(String(128),nullable=False);region_id=Column(Integer,ForeignKey("regions.id",ondelete="RESTRICT"),nullable=False,index=True);configuration_json=Column(Text,nullable=False);batch_fingerprint=Column(String(64),nullable=False);workflow_state=Column(String(32),nullable=False,default="PREPARED",server_default="PREPARED",index=True);created_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False);created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc));completed_at=Column(DateTime,nullable=True)


class OccurrenceAcquisitionBatchItem(Base):
    __tablename__="occurrence_acquisition_batch_items";__table_args__=(UniqueConstraint("batch_id","jurisdiction_id","taxon_id","source_key",name="uq_occurrence_batch_item"),Index("ix_occurrence_batch_claim","workflow_state","lease_expires_at"))
    id=Column(Integer,primary_key=True,index=True);batch_id=Column(Integer,ForeignKey("occurrence_acquisition_batches.id",ondelete="CASCADE"),nullable=False,index=True);jurisdiction_id=Column(Integer,ForeignKey("jurisdictions.id",ondelete="RESTRICT"),nullable=False,index=True);taxon_id=Column(Integer,ForeignKey("species.id",ondelete="RESTRICT"),nullable=False,index=True);source_key=Column(String(128),nullable=False);readiness_state=Column(String(48),nullable=False);workflow_state=Column(String(32),nullable=False,default="PENDING",server_default="PENDING",index=True);claim_token=Column(String(64),nullable=True,unique=True);claimed_by=Column(String(256),nullable=True);claimed_at=Column(DateTime,nullable=True);lease_expires_at=Column(DateTime,nullable=True);retry_count=Column(Integer,nullable=False,default=0,server_default="0");result_json=Column(Text,nullable=True);last_error=Column(Text,nullable=True);preparation_id=Column(Integer,ForeignKey("occurrence_acquisition_preparations.id",ondelete="RESTRICT"),nullable=True);created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc));completed_at=Column(DateTime,nullable=True)


@event.listens_for(IdentificationMediaReviewEvent, "before_update")
def _protect_identification_media_review_event(_mapper, _connection, _target):
    raise ValueError("IdentificationMediaReviewEvent rows are append-only")


@event.listens_for(IdentificationMediaReviewEvent, "before_delete")
def _protect_identification_media_review_event_delete(_mapper, _connection, _target):
    raise ValueError("IdentificationMediaReviewEvent rows are append-only")


class ObservationOperationalCase(Base):
    __tablename__ = "observation_operational_cases"
    __table_args__ = (UniqueConstraint("observation_id", name="uq_observation_operational_case"),)
    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    workflow_state = Column(String(40), nullable=False, default="TRIAGE_REQUIRED", server_default="TRIAGE_REQUIRED", index=True)
    triage_route = Column(String(40), nullable=True, index=True)
    operational_priority = Column(String(16), nullable=False, default="NORMAL", server_default="NORMAL", index=True)
    priority_reason = Column(Text, nullable=True)
    priority_changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    assigned_reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    duplicate_disposition = Column(String(32), nullable=False, default="NOT_ASSESSED", server_default="NOT_ASSESSED")
    final_disposition = Column(String(40), nullable=True)
    evidence_handoff_state = Column(String(48), nullable=False, default="NOT_EVALUATED", server_default="NOT_EVALUATED")
    opened_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ObservationOperationalEvent(Base):
    __tablename__ = "observation_operational_events"
    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("observation_operational_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    event_type = Column(String(48), nullable=False, index=True)
    previous_state = Column(String(40), nullable=True)
    current_state = Column(String(40), nullable=False)
    reason_reference = Column(Text, nullable=True)
    identity_state_json = Column(Text, nullable=False, default="{}", server_default="{}")
    provenance_version = Column(String(64), nullable=False, default="observation-operations-v1", server_default="observation-operations-v1")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ObservationReviewerGrant(Base):
    """Explicit operational authority; organization membership is not sufficient."""
    __tablename__ = "observation_reviewer_grants"
    __table_args__ = (UniqueConstraint("user_id", "jurisdiction_id", name="uq_observation_reviewer_grant"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="JURISDICTION_REVIEWER", server_default="JURISDICTION_REVIEWER")
    status = Column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE", index=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    grant_reference = Column(String(256), nullable=False)
    granted_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    revoked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class ObservationNotificationEvent(Base):
    """Delivery-neutral operational notification outbox; no email/SMS is implied."""
    __tablename__ = "observation_notification_events"
    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("observation_operational_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type = Column(String(48), nullable=False, index=True)
    recipient_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    payload_json = Column(Text, nullable=False, default="{}", server_default="{}")
    delivery_state = Column(String(32), nullable=False, default="PENDING_DELIVERY_INTEGRATION", server_default="PENDING_DELIVERY_INTEGRATION")
    delivery_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_delivery_error = Column(Text, nullable=True)
    last_attempted_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ReporterAccessToken(Base):
    __tablename__ = "reporter_access_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_reporter_access_token_hash"),)
    id = Column(Integer, primary_key=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("observation_operational_cases.id", ondelete="RESTRICT"), nullable=True, index=True)
    purpose = Column(String(24), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, index=True)
    public_reference = Column(String(32), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ReporterAdditionalInformation(Base):
    __tablename__ = "reporter_additional_information"
    id = Column(Integer, primary_key=True)
    observation_id = Column(Integer, ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("observation_operational_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    token_id = Column(Integer, ForeignKey("reporter_access_tokens.id", ondelete="RESTRICT"), nullable=False)
    response_text = Column(Text, nullable=False)
    image_filename = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class PilotFeedback(Base):
    __tablename__ = "pilot_feedback"
    id = Column(Integer, primary_key=True)
    category = Column(String(32), nullable=False, index=True)
    feedback_text = Column(Text, nullable=False)
    page_context = Column(String(512), nullable=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    state = Column(String(24), nullable=False, default="OPEN", server_default="OPEN", index=True)
    admin_disposition = Column(Text, nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


class EcologicalStatusSourceRegistration(Base):
    __tablename__ = "ecological_status_source_registrations"
    __table_args__ = (UniqueConstraint("configuration_fingerprint", name="uq_ecological_source_configuration_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    source_registration_id = Column(String(128), nullable=False, index=True)
    source_organization = Column(String(256), nullable=False)
    source_title = Column(String(512), nullable=False)
    source_type = Column(String(64), nullable=False)
    scope_type = Column(String(32), nullable=False)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_version = Column(String(128), nullable=True)
    publication_date = Column(DateTime, nullable=True)
    source_reference = Column(String(1024), nullable=False)
    documentation_reference = Column(String(1024), nullable=True)
    license = Column(String(256), nullable=False)
    reuse_terms = Column(Text, nullable=False)
    acquisition_method = Column(String(64), nullable=False)
    expected_semantics_json = Column(Text, nullable=False)
    field_mapping_json = Column(Text, nullable=False)
    semantic_mapping_json = Column(Text, nullable=False)
    provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    configuration_version = Column(String(64), nullable=False)
    configuration_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(24), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approval_reference = Column(String(256), nullable=True)
    approved_configuration_fingerprint = Column(String(64), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    predecessor_id = Column(Integer, ForeignKey("ecological_status_source_registrations.id", ondelete="RESTRICT"), nullable=True)


class EcologicalStatusIngestionRun(Base):
    __tablename__ = "ecological_status_ingestion_runs"
    __table_args__ = (UniqueConstraint("run_fingerprint", name="uq_ecological_status_ingestion_run_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    source_registration_id = Column(Integer, ForeignKey("ecological_status_source_registrations.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    original_filename = Column(String(256), nullable=False)
    media_type = Column(String(128), nullable=False)
    byte_size = Column(Integer, nullable=False)
    artifact_sha256 = Column(String(64), nullable=False, index=True)
    artifact_reference = Column(String(512), nullable=False)
    parser_version = Column(String(64), nullable=False)
    normalized_content_fingerprint = Column(String(64), nullable=False)
    mapping_json = Column(Text, nullable=False)
    semantic_mapping_json = Column(Text, nullable=False)
    warnings_json = Column(Text, nullable=False)
    errors_json = Column(Text, nullable=False)
    provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    source_row_count = Column(Integer, nullable=False)
    run_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(32), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    operator_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    applied_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)


class EcologicalStatusIngestionRow(Base):
    __tablename__ = "ecological_status_ingestion_rows"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "row_fingerprint", name="uq_ecological_status_ingestion_row_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    ingestion_run_id = Column(Integer, ForeignKey("ecological_status_ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_row_number = Column(Integer, nullable=False)
    source_record_identifier = Column(String(512), nullable=True)
    raw_row_json = Column(Text, nullable=False)
    normalized_scientific_name = Column(String(512), nullable=True)
    common_name = Column(String(512), nullable=True)
    submitted_taxon_identifier = Column(String(256), nullable=True)
    reconciled_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True, index=True)
    taxonomy_result = Column(String(48), nullable=False, index=True)
    jurisdiction_result = Column(String(48), nullable=False, index=True)
    source_status = Column(String(256), nullable=True)
    semantic_result = Column(String(48), nullable=False, index=True)
    proposed_statuses_json = Column(Text, nullable=False)
    conflict_state = Column(String(48), nullable=False)
    preflight_classification = Column(String(48), nullable=False, index=True)
    effective_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    row_fingerprint = Column(String(64), nullable=False)
    review_status = Column(String(32), nullable=False, default="REVIEW_REQUIRED", server_default="REVIEW_REQUIRED", index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    apply_status = Column(String(24), nullable=False, default="NOT_APPLIED", server_default="NOT_APPLIED", index=True)
    ecological_preparation_id = Column(Integer, ForeignKey("ecological_status_preparations.id", ondelete="RESTRICT"), nullable=True)
    last_error = Column(Text, nullable=True)


class EcologicalStatusIngestionReview(Base):
    __tablename__ = "ecological_status_ingestion_reviews"
    id = Column(Integer, primary_key=True, index=True)
    ingestion_row_id = Column(Integer, ForeignKey("ecological_status_ingestion_rows.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    disposition = Column(String(32), nullable=False, index=True)
    review_reference = Column(String(256), nullable=False)
    dependency_fingerprint = Column(String(64), nullable=False)
    source_license_reference = Column(String(512), nullable=True)
    resulting_assertion_ids_json = Column(Text, nullable=False, default="[]", server_default="[]")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class EcologicalStatusPreparation(Base):
    """Reviewed jurisdiction-scoped source manifest; preparation never changes status."""
    __tablename__ = "ecological_status_preparations"
    __table_args__ = (UniqueConstraint("dependency_fingerprint", name="uq_ecological_status_preparation_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_organization = Column(String(256), nullable=False)
    source_title = Column(String(512), nullable=False)
    source_version = Column(String(128), nullable=True)
    publication_date = Column(DateTime, nullable=True)
    source_reference = Column(String(1024), nullable=False)
    evidence_type = Column(String(64), nullable=False)
    authority_classification = Column(String(48), nullable=False)
    geographic_scope_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    manifest_json = Column(Text, nullable=False)
    dependency_fingerprint = Column(String(64), nullable=False, index=True)
    workflow_status = Column(String(32), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    prepared_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    prepared_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_dependency_fingerprint = Column(String(64), nullable=True)
    applied_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)


class EcologicalStatusCandidate(Base):
    __tablename__ = "ecological_status_candidates"
    __table_args__ = (UniqueConstraint("preparation_id", "candidate_fingerprint", name="uq_ecological_status_candidate_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("ecological_status_preparations.id", ondelete="CASCADE"), nullable=False, index=True)
    submitted_scientific_name = Column(String(512), nullable=False)
    submitted_identifier_scheme = Column(String(64), nullable=True)
    submitted_identifier = Column(String(256), nullable=True)
    reconciled_taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=True, index=True)
    taxonomy_reconciliation = Column(String(40), nullable=False)
    asserted_statuses_json = Column(Text, nullable=False)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    source_note = Column(Text, nullable=True)
    preflight_classification = Column(String(48), nullable=False, index=True)
    candidate_fingerprint = Column(String(64), nullable=False)
    review_status = Column(String(32), nullable=False, default="REVIEW_REQUIRED", server_default="REVIEW_REQUIRED", index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)


class EcologicalStatusAssertion(Base):
    """Immutable, versioned, single-status scientific assertion."""
    __tablename__ = "ecological_status_assertions"
    __table_args__ = (UniqueConstraint("provenance_fingerprint", name="uq_ecological_status_assertion_fingerprint"),)
    id = Column(Integer, primary_key=True, index=True)
    preparation_id = Column(Integer, ForeignKey("ecological_status_preparations.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id = Column(Integer, ForeignKey("ecological_status_candidates.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    asserted_status = Column(String(32), nullable=False, index=True)
    source_organization = Column(String(256), nullable=False)
    source_title = Column(String(512), nullable=False)
    source_version = Column(String(128), nullable=True)
    publication_date = Column(DateTime, nullable=True)
    source_reference = Column(String(1024), nullable=False)
    evidence_type = Column(String(64), nullable=False)
    authority_classification = Column(String(48), nullable=False)
    geographic_scope_json = Column(Text, nullable=False)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    review_status = Column(String(24), nullable=False, default="APPROVED", server_default="APPROVED", index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    review_reference = Column(String(256), nullable=False)
    reviewed_at = Column(DateTime, nullable=False)
    limitations_json = Column(Text, nullable=False)
    supporting_occurrence_evidence_ids_json = Column(Text, nullable=False, default="[]", server_default="[]")
    provenance_json = Column(Text, nullable=False)
    provenance_fingerprint = Column(String(64), nullable=False, index=True)
    lifecycle_state = Column(String(24), nullable=False, default="CURRENT", server_default="CURRENT", index=True)
    supersedes_assertion_id = Column(Integer, ForeignKey("ecological_status_assertions.id", ondelete="RESTRICT"), nullable=True)
    superseded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class SpeciesJurisdictionStatus(Base):
    __tablename__ = "species_jurisdiction_status"
    __table_args__ = (
        UniqueConstraint("species_id", "jurisdiction_id", name="uq_species_jurisdiction_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    ecological_status = Column(String(16), nullable=False)
    status_set_json = Column(Text, nullable=True)
    projection_state = Column(String(32), nullable=True)
    projection_fingerprint = Column(String(64), nullable=True)
    source_assertion_ids_json = Column(Text, nullable=True)
    source = Column(String(64), nullable=False)
    source_url = Column(String(512), nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    species = relationship("Species", back_populates="jurisdiction_statuses")
    jurisdiction = relationship("Jurisdiction")


class ScientificDataset(Base):
    """A provenance-bearing snapshot of a scientific input source.

    Phase 10C architecture: separate source from snapshot. Each
    ScientificDataset is a frozen record describing where a set of
    scientific inputs (occurrences, environmental features, or
    derived training samples) came from. The deployment that
    consumed the dataset references it through
    ``ScientificDatasetDeployment``.

    A ScientificDataset MUST NOT be silently overwritten once it has
    been referenced by a deployment. To re-acquire data, a NEW
    ScientificDataset row is created with a new ``retrieved_at``
    timestamp and a new ``record_count``.
    """
    __tablename__ = "scientific_datasets"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_scientific_dataset_slug"),
    )

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(128), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    dataset_type = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    description = Column(Text, nullable=True)
    # Ownership
    species_id = Column(Integer, ForeignKey("species.id"), nullable=True, index=True)
    species_program_id = Column(Integer, ForeignKey("species_programs.id"), nullable=True, index=True)
    # Geographic scope
    geographic_scope_type = Column(String(16), nullable=False, default="JURISDICTION", server_default="JURISDICTION")
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=True, index=True)
    # Source / acquisition
    source_name = Column(String(64), nullable=False)
    source_type = Column(String(32), nullable=True)
    source_reference = Column(String(512), nullable=True)
    source_version = Column(String(128), nullable=True)
    acquisition_manifest_json = Column(Text, nullable=True)
    retrieved_at = Column(DateTime, nullable=True)
    record_count = Column(Integer, nullable=True)
    # Artifact
    artifact_path = Column(String(512), nullable=True)
    artifact_sha256 = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    species_record = relationship("Species")
    species_program_record = relationship("SpeciesProgram")
    region_record = relationship("Region")
    jurisdiction_record = relationship("Jurisdiction")
    deployment_links = relationship(
        "ScientificDatasetDeployment",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    occurrence_links = relationship(
        "HistoricalOccurrence",
        back_populates="dataset",
    )
    applicability_assertions = relationship(
        "ScientificDatasetApplicability", back_populates="dataset"
    )


class ScientificDatasetApplicability(Base):
    """Auditable role-specific authorization for jurisdiction-level use."""

    __tablename__ = "scientific_dataset_applicabilities"
    __table_args__ = (
        UniqueConstraint(
            "scientific_dataset_id", "jurisdiction_id", "evidence_role",
            "provenance_fingerprint",
            name="uq_dataset_applicability_assertion",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_dataset_id = Column(
        Integer, ForeignKey("scientific_datasets.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    jurisdiction_id = Column(
        Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    evidence_role = Column(String(48), nullable=False, index=True)
    applicability_status = Column(
        String(24), nullable=False, default="PENDING_REVIEW",
        server_default="PENDING_REVIEW", index=True,
    )
    reconciliation_method = Column(String(64), nullable=False)
    reconciliation_version = Column(String(64), nullable=False)
    jurisdiction_boundary_id = Column(
        Integer, ForeignKey("jurisdiction_boundaries.id", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    provenance_reference = Column(String(512), nullable=False)
    provenance_json = Column(Text, nullable=False)
    provenance_fingerprint = Column(String(64), nullable=False, index=True)
    reviewed_by = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_by = Column(String(256), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    superseded_at = Column(DateTime, nullable=True)

    dataset = relationship("ScientificDataset", back_populates="applicability_assertions")
    jurisdiction = relationship("Jurisdiction", back_populates="dataset_applicabilities")
    jurisdiction_boundary = relationship("JurisdictionBoundary")


class ScientificDatasetDeployment(Base):
    """Many-to-many link between a ScientificDataset and a
    SuitabilityDeployment with a documented role.

    Examples of ``role``:
        ``TRAINING_OCCURRENCES``, ``ENVIRONMENTAL_INPUT``,
        ``VALIDATION_INPUT``.

    Roles are free-text labels, but each deployment should only
    attach datasets whose role can be supported by the existing
    Jamaica v3 pipeline. New roles are introduced explicitly in
    future phases; Phase 10C introduces the minimum set that the
    existing deployment can be supported with.
    """
    __tablename__ = "scientific_dataset_deployments"
    __table_args__ = (
        UniqueConstraint(
            "scientific_dataset_id",
            "suitability_deployment_id",
            "role",
            name="uq_scientific_dataset_deployment",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_dataset_id = Column(Integer, ForeignKey("scientific_datasets.id"), nullable=False, index=True)
    suitability_deployment_id = Column(Integer, ForeignKey("suitability_deployments.id"), nullable=False, index=True)
    role = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    dataset = relationship("ScientificDataset", back_populates="deployment_links")
    deployment = relationship("SuitabilityDeployment")


class SpeciesProgram(Base):
    __tablename__ = "species_programs"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "scientific_name", name="uq_species_program_jurisdiction_species"),
    )

    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    species_id = Column(Integer, ForeignKey("species.id"), nullable=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    common_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    jurisdiction = relationship("Jurisdiction", back_populates="species_programs")
    species = relationship("Species", back_populates="species_programs")
    suitability_deployments = relationship("SuitabilityDeployment", back_populates="species_program")
    training_runs = relationship("TrainingRun", back_populates="species_program")
    priority_generations = relationship("NextAreaSnapshotGeneration", back_populates="species_program")


class SuitabilityDeployment(Base):
    __tablename__ = "suitability_deployments"
    __table_args__ = (
        UniqueConstraint("species_program_id", "model_version", name="uq_suitability_deployment_program_version"),
    )

    id = Column(Integer, primary_key=True, index=True)
    species_program_id = Column(Integer, ForeignKey("species_programs.id"), nullable=False, index=True)
    habitat_suitability_model_id = Column(Integer, ForeignKey("habitat_suitability_models.id"), nullable=False, index=True)
    model_version = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    artifact_hash = Column(String(64), nullable=True)
    generated_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    public_display_status = Column(String(24), nullable=False, default="NOT_APPROVED", server_default="NOT_APPROVED", index=True)
    public_display_approval_reference = Column(String(256), nullable=True)
    public_display_approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    public_display_approved_at = Column(DateTime, nullable=True)
    public_display_revoked_at = Column(DateTime, nullable=True)
    public_display_limitations_json = Column(Text, nullable=False, default="[]", server_default="[]")
    # Nullable FK to TrainingRun. Phase 10E-2 added this column via
    # the additive migration. Future deployments can reference the
    # TrainingRun that produced their artifact; legacy deployments
    # remain valid with NULL.
    training_run_id = Column(Integer, ForeignKey("training_runs.id"), nullable=True, index=True)

    species_program = relationship("SpeciesProgram", back_populates="suitability_deployments")
    model = relationship("HabitatSuitabilityModel")
    priority_generations = relationship("NextAreaSnapshotGeneration", back_populates="suitability_deployment")
    training_run = relationship("TrainingRun", back_populates="deployments")


class TrainingRun(Base):
    """Durable provenance record for a single suitability training
    execution. Phase 10E-2 introduced this model to give future
    training runs a first-class persisted identity.

    A TrainingRun is created with ``status=BUILDING`` and updated to
    ``COMPLETED`` or ``FAILED``. COMPLETED runs are immutable with
    respect to scientific provenance (configuration snapshot,
    dataset relationships, artifact SHA, selected candidate,
    validation metrics). FAILED runs retain diagnostic context via
    the ``failure_reason`` and ``warnings_json`` columns.

    The ``provenance_origin`` column distinguishes:

    - ``NATIVE``: a run recorded by the explicit persistence
      boundary introduced in Phase 10E-2. Future native training
      runs MUST use this origin.
    - ``LEGACY_RECONSTRUCTED``: a run retroactively reconstructed
      from existing persisted/source provenance (Phase 10D-5).
      The ``configuration_json`` for these runs preserves the
      Phase 10D-5 source-classification distinction so future
      audits cannot mistake source-config values for historically
      persisted provenance.

    The model deliberately does not duplicate scientific information
    that is already better represented relationally:

    - Scientific dataset identity is preserved via the
      ``TrainingRunDataset`` link table.
    - Model metadata is preserved via the artifact SHA.
    """
    __tablename__ = "training_runs"

    id = Column(Integer, primary_key=True, index=True)
    species_program_id = Column(
        Integer,
        ForeignKey("species_programs.id"),
        nullable=False,
        index=True,
    )
    model_version = Column(String, nullable=False, index=True)
    status = Column(
        String,
        nullable=False,
        default="BUILDING",
        server_default="BUILDING",
        index=True,
    )
    provenance_origin = Column(
        String,
        nullable=False,
        default="NATIVE",
        server_default="NATIVE",
    )
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    random_seed = Column(Integer, nullable=True)
    selected_candidate = Column(String, nullable=True)
    artifact_path = Column(String, nullable=True)
    artifact_sha256 = Column(String(64), nullable=True, index=True)
    training_sample_count = Column(Integer, nullable=True)
    presence_count = Column(Integer, nullable=True)
    background_count = Column(Integer, nullable=True)
    validation_metrics_json = Column(Text, nullable=True)
    configuration_json = Column(Text, nullable=False)
    # Phase 10E-3 added this column via the additive migration.
    # It carries the SHA-256 hash of the canonical
    # configuration_json bytes. Future native runs MUST compute
    # and persist this hash; legacy reconstructed runs MAY have
    # it backfilled explicitly but the backfill does not elevate
    # the snapshot to historically persisted provenance.
    configuration_sha256 = Column(String(64), nullable=True, index=True)
    # Phase 10E-4 added this column. It is a SHA-256 over the
    # ordered set of (role, dataset_id, artifact_sha256_or_null,
    # record_count, source_version) tuples linked to the run via
    # the TrainingRunDataset rows. NULL until the hash is computed
    # explicitly by the repository. When any linked dataset has a
    # NULL artifact_sha256, the hash is still computed over the
    # remaining fields and ``input_integrity_status`` is set to
    # ``PARTIAL``.
    training_input_sha256 = Column(String(64), nullable=True, index=True)
    input_integrity_status = Column(
        String, nullable=True, default="NOT_COMPUTED", server_default="NOT_COMPUTED",
    )
    warnings_json = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    species_program = relationship(
        "SpeciesProgram", back_populates="training_runs"
    )
    dataset_links = relationship(
        "TrainingRunDataset",
        back_populates="training_run",
        cascade="all, delete-orphan",
    )
    deployments = relationship(
        "SuitabilityDeployment", back_populates="training_run"
    )


class TrainingRunDataset(Base):
    """Many-to-many link between a TrainingRun and a
    ScientificDataset, with an explicit role reusing the Phase 10C
    vocabulary.

    Roles are free-text labels but each TrainingRun should only
    attach datasets whose role can be supported by the existing
    training pipeline. The minimum set the training pipeline
    introduces is:

    - ``TRAINING_OCCURRENCES``
    - ``ENVIRONMENTAL_INPUT``
    - ``VALIDATION_INPUT`` (reserved for future use)
    """
    __tablename__ = "training_run_datasets"
    __table_args__ = (
        UniqueConstraint(
            "training_run_id",
            "scientific_dataset_id",
            "role",
            name="uq_training_run_dataset_role",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    training_run_id = Column(
        Integer,
        ForeignKey("training_runs.id"),
        nullable=False,
        index=True,
    )
    scientific_dataset_id = Column(
        Integer,
        ForeignKey("scientific_datasets.id"),
        nullable=False,
        index=True,
    )
    role = Column(String(64), nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    training_run = relationship(
        "TrainingRun", back_populates="dataset_links"
    )
    scientific_dataset = relationship("ScientificDataset")


class HabitatSuitabilityGridCell(Base):

    __tablename__ = "habitat_suitability_grid_cells"
    __table_args__ = (
        UniqueConstraint(
            "model_version",
            "grid_cell_id",
            name="uq_habitat_suitability_grid_model_cell",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    suitability_deployment_id = Column(Integer, ForeignKey("suitability_deployments.id"), nullable=True, index=True)
    model_version = Column(String, nullable=False, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    grid_cell_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    grid_size = Column(Float, nullable=False, default=0.1)
    depth = Column(Float, nullable=False)
    suitability_score = Column(Float, nullable=False)
    depth_source = Column(String, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class BathymetryGridCell(Base):

    __tablename__ = "bathymetry_grid_cells"

    grid_cell_id = Column(String, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    classification = Column(String, nullable=False)
    depth = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    sampled_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PredictionModelDatasetAudit(Base):

    __tablename__ = "prediction_model_dataset_audits"
    __table_args__ = (
        UniqueConstraint(
            "scientific_name",
            "generation_version",
            name="uq_prediction_model_dataset_audit_species_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    generation_version = Column(String, nullable=False)
    configuration_json = Column(Text, nullable=False)
    diagnostics_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PredictionSampleEnvironmentalFeature(Base):

    __tablename__ = "prediction_sample_environmental_features"
    __table_args__ = (
        UniqueConstraint(
            "scientific_dataset_id",
            "prediction_model_sample_id",
            "feature_name",
            "feature_version",
            name="uq_prediction_sample_environment_feature",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    # scientific_dataset_id is the provenance ownership reference.
    # Phase 10E-1 introduced this FK and backfilled it from the
    # feature_version + scientific_dataset_deployments linkage. The
    # column is intentionally NOT NULLABLE in the steady-state
    # invariant: every environmental feature row must belong to
    # exactly one ScientificDataset. The backfill is performed by
    # the Phase 10E-1 migration helper.
    scientific_dataset_id = Column(
        Integer,
        ForeignKey("scientific_datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    prediction_model_sample_id = Column(
        Integer,
        ForeignKey("prediction_model_samples.id"),
        nullable=False,
        index=True,
    )
    feature_name = Column(String, nullable=False, index=True)
    value = Column(Float, nullable=True)
    source = Column(String, nullable=False)
    sampling_method = Column(String, nullable=False)
    is_missing = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(Text, nullable=True)
    feature_version = Column(String, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    scientific_dataset = relationship(
        "ScientificDataset",
        foreign_keys=[scientific_dataset_id],
    )


class HabitatSuitabilityV3GridCell(Base):

    __tablename__ = "habitat_suitability_v3_grid_cells"
    __table_args__ = (
        UniqueConstraint(
            "model_version",
            "grid_cell_id",
            name="uq_habitat_suitability_v3_grid_model_cell",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    suitability_deployment_id = Column(Integer, ForeignKey("suitability_deployments.id"), nullable=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    model_version = Column(String, nullable=False, index=True)
    grid_cell_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    grid_size = Column(Float, nullable=False, default=0.1)
    suitability_score = Column(Float, nullable=True)
    suitability_band = Column(String, nullable=True)
    prediction_status = Column(String, nullable=False)
    feature_values_json = Column(Text, nullable=False)
    missing_features_json = Column(Text, nullable=False)
    generated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class NextAreaPredictionCell(Base):

    __tablename__ = "next_area_prediction_cells"
    __table_args__ = (
        UniqueConstraint(
            "prediction_version",
            "grid_cell_id",
            name="uq_next_area_prediction_version_cell",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    prediction_version = Column(String, nullable=False, index=True)
    grid_cell_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    suitability_score = Column(Float, nullable=False)
    distance_from_nearest_current_evidence_km = Column(Float, nullable=True)
    observation_evidence_score = Column(Float, nullable=False)
    recent_activity_score = Column(Float, nullable=False)
    current_evidence_score = Column(Float, nullable=False)
    monitoring_priority_score = Column(Float, nullable=False)
    priority_band = Column(String, nullable=False)
    source_observation_ids_json = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False)
    reason_codes_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False)


class NextAreaPredictionGeneration(Base):

    __tablename__ = "next_area_prediction_generations"
    __table_args__ = (
        UniqueConstraint(
            "prediction_version",
            name="uq_next_area_prediction_generation_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    species_program_id = Column(Integer, ForeignKey("species_programs.id"), nullable=True, index=True)
    suitability_deployment_id = Column(Integer, ForeignKey("suitability_deployments.id"), nullable=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    prediction_version = Column(String, nullable=False)
    suitability_model_version = Column(String, nullable=False)
    diagnostics_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False)


class NextAreaSnapshotGeneration(Base):

    __tablename__ = "next_area_snapshot_generations"
    __table_args__=(
        Index("uq_next_area_snapshot_active_program_version","species_program_id","prediction_version",unique=True,sqlite_where=text("is_active = 1"),postgresql_where=text("is_active IS TRUE")),
        Index("uq_next_area_snapshot_building_program_version","species_program_id","prediction_version",unique=True,sqlite_where=text("status = 'BUILDING'"),postgresql_where=text("status = 'BUILDING'")),
    )

    id = Column(Integer, primary_key=True, index=True)
    species_program_id = Column(Integer, ForeignKey("species_programs.id"), nullable=True, index=True)
    suitability_deployment_id = Column(Integer, ForeignKey("suitability_deployments.id"), nullable=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    prediction_version = Column(String, nullable=False, index=True)
    suitability_model_version = Column(String, nullable=False)
    status = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    diagnostics_json = Column(Text, nullable=False, default="{}")
    evidence_state_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    generated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    species_program = relationship("SpeciesProgram", back_populates="priority_generations")
    suitability_deployment = relationship("SuitabilityDeployment", back_populates="priority_generations")


class NextAreaSnapshotCell(Base):

    __tablename__ = "next_area_snapshot_cells"
    __table_args__ = (
        UniqueConstraint(
            "generation_id",
            "grid_cell_id",
            name="uq_next_area_snapshot_generation_cell",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    generation_id = Column(
        Integer,
        ForeignKey("next_area_snapshot_generations.id"),
        nullable=False,
        index=True,
    )
    scientific_name = Column(String, nullable=False, index=True)
    prediction_version = Column(String, nullable=False, index=True)
    grid_cell_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    suitability_score = Column(Float, nullable=False)
    distance_from_nearest_current_evidence_km = Column(Float, nullable=True)
    observation_evidence_score = Column(Float, nullable=False)
    recent_activity_score = Column(Float, nullable=False)
    current_evidence_score = Column(Float, nullable=False)
    monitoring_priority_score = Column(Float, nullable=False)
    priority_band = Column(String, nullable=False)
    source_observation_ids_json = Column(Text, nullable=False)
    evidence_json = Column(Text, nullable=False)
    reason_codes_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False)


# ============================================================================
# Phase 11B-1: Anomaly domain persistent foundation.
#
# This module ONLY defines the persistence schema for future anomaly
# assessments. NO scientific evaluation logic is implemented here. NO
# anomaly interpretation is performed by these models. The lifecycle
# state (CURRENT / STALE / SUPERSEDED) is distinct from the scientific
# result status. Scientific result fields are immutable after insert.
#
# Lifecycle transitions:
#     CURRENT -> STALE
#     STALE -> SUPERSEDED
# Reverse transitions are rejected at the repository layer.
# ============================================================================


class AnomalyAssessment(Base):
    """Immutable scientific-result snapshot for one observation.

    Lifecycle is tracked via ``current_state`` and ``invalidated_at``.
    STALE is a lifecycle state, NOT a result state. The scientific
    result (overall_status, overall_classification, signal statuses,
    assessment_confidence) is immutable after insert.
    """

    __tablename__ = "anomaly_assessments"
    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(
        Integer,
        ForeignKey("observations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jurisdiction_id = Column(
        Integer,
        ForeignKey("jurisdictions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    species_program_id = Column(
        Integer,
        ForeignKey("species_programs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    evaluated_species = Column(String, nullable=True)
    evaluated_species_source = Column(String, nullable=True)

    overall_status = Column(String, nullable=False)
    overall_classification = Column(String, nullable=True)
    assessment_confidence = Column(String, nullable=False)
    requires_review = Column(Boolean, nullable=False, default=False, server_default="0")
    review_type = Column(String, nullable=False, default="NO_REVIEW", server_default="NO_REVIEW")

    provenance_version = Column(String, nullable=False)
    dependency_fingerprint = Column(String, nullable=True)

    current_state = Column(
        String,
        nullable=False,
        default="CURRENT",
        server_default="CURRENT",
        index=True,
    )
    generated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    invalidated_at = Column(DateTime, nullable=True)
    superseded_at = Column(DateTime, nullable=True)

    evidence_summary_json = Column(Text, nullable=True)
    limitations_json = Column(Text, nullable=False)
    provenance_json = Column(Text, nullable=False)

    observation = relationship("Observation", foreign_keys=[observation_id])
    jurisdiction = relationship("Jurisdiction", foreign_keys=[jurisdiction_id])
    species_program = relationship(
        "SpeciesProgram", foreign_keys=[species_program_id]
    )
    signals = relationship(
        "AnomalySignal",
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class AnomalySignal(Base):
    """Immutable per-signal result for an AnomalyAssessment.

    Signal results feed the assessment combination rule but are
    NOT themselves ecological anomaly conclusions. Signals are
    immutable after insert.
    """

    __tablename__ = "anomaly_signals"
    __table_args__ = (
        UniqueConstraint(
            "anomaly_assessment_id",
            "signal_type",
            name="uq_anomaly_signal_assessment_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    anomaly_assessment_id = Column(
        Integer,
        ForeignKey("anomaly_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    anomaly_strength = Column(String, nullable=True)
    evidence_confidence = Column(String, nullable=False)
    evidence_summary_json = Column(Text, nullable=True)
    limitations_json = Column(Text, nullable=False)
    source_dataset_ids_json = Column(Text, nullable=True)
    suitability_deployment_id = Column(
        Integer,
        ForeignKey("suitability_deployments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supporting_observation_ids_json = Column(Text, nullable=True)
    generated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    provenance_version = Column(String, nullable=False)

    assessment = relationship("AnomalyAssessment", back_populates="signals")
    suitability_deployment = relationship("SuitabilityDeployment")


class AnomalySynthesisSnapshot(Base):
    """Immutable durable audit record of one conservative synthesis result."""

    __tablename__ = "anomaly_synthesis_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "anomaly_assessment_id",
            "synthesis_rules_version",
            "synthesis_fingerprint",
            name="uq_anomaly_synthesis_assessment_rules_fingerprint",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    anomaly_assessment_id = Column(
        Integer, ForeignKey("anomaly_assessments.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    observation_id = Column(
        Integer, ForeignKey("observations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    jurisdiction_id = Column(
        Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    synthesis_rules_version = Column(String, nullable=False, index=True)
    dependency_fingerprint = Column(String(64), nullable=False)
    synthesis_fingerprint = Column(String(64), nullable=False, index=True)
    overall_status = Column(String, nullable=False)
    overall_classification = Column(String, nullable=True)
    requires_review = Column(Boolean, nullable=False, default=False, server_default="0")
    review_type = Column(String, nullable=False)
    assessment_confidence = Column(String, nullable=False)
    provenance_json = Column(Text, nullable=False)
    limitations_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    assessment = relationship("AnomalyAssessment")
    observation = relationship("Observation")
    jurisdiction = relationship("Jurisdiction")


class AnomalyReviewEvent(Base):
    """Append-only human scientific disposition history."""
    __tablename__ = "anomaly_review_events"
    id = Column(Integer, primary_key=True, index=True)
    anomaly_assessment_id = Column(Integer, ForeignKey("anomaly_assessments.id", ondelete="RESTRICT"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_state = Column(String(32), nullable=True)
    to_state = Column(String(32), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class ScientificReviewerGrant(Base):
    __tablename__ = "scientific_reviewer_grants"
    __table_args__ = (UniqueConstraint("user_id", "jurisdiction_id", name="uq_scientific_reviewer_grant"),)
    id=Column(Integer,primary_key=True,index=True);user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False,index=True);jurisdiction_id=Column(Integer,ForeignKey("jurisdictions.id",ondelete="RESTRICT"),nullable=False,index=True)
    role=Column(String(48),nullable=False,default="JURISDICTION_SCIENTIFIC_REVIEWER",server_default="JURISDICTION_SCIENTIFIC_REVIEWER");status=Column(String(16),nullable=False,default="ACTIVE",server_default="ACTIVE",index=True)
    granted_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False);grant_reference=Column(String(256),nullable=False);granted_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc));revoked_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=True);revoked_at=Column(DateTime,nullable=True)


class AnomalyReviewAssignment(Base):
    __tablename__="anomaly_review_assignments"
    __table_args__=(Index("uq_anomaly_active_assignment","anomaly_assessment_id",unique=True,sqlite_where=text("status = 'ASSIGNED'"),postgresql_where=text("status = 'ASSIGNED'")),)
    id=Column(Integer,primary_key=True,index=True);anomaly_assessment_id=Column(Integer,ForeignKey("anomaly_assessments.id",ondelete="RESTRICT"),nullable=False,index=True);jurisdiction_id=Column(Integer,ForeignKey("jurisdictions.id",ondelete="RESTRICT"),nullable=False,index=True);reviewer_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False,index=True);status=Column(String(16),nullable=False,default="ASSIGNED",server_default="ASSIGNED",index=True);assigned_by_user_id=Column(Integer,ForeignKey("users.id",ondelete="RESTRICT"),nullable=False);assigned_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc));unassigned_at=Column(DateTime,nullable=True);reason=Column(Text,nullable=False)


class ScientificDomainEvent(Base):
    __tablename__="scientific_domain_events"
    __table_args__=(UniqueConstraint("event_fingerprint",name="uq_scientific_domain_event_fingerprint"),)
    id=Column(Integer,primary_key=True,index=True);event_type=Column(String(64),nullable=False,index=True);jurisdiction_id=Column(Integer,ForeignKey("jurisdictions.id",ondelete="RESTRICT"),nullable=False,index=True);taxon_id=Column(Integer,ForeignKey("species.id",ondelete="RESTRICT"),nullable=True,index=True);observation_id=Column(Integer,ForeignKey("observations.id",ondelete="RESTRICT"),nullable=True,index=True);dependency_reference=Column(String(256),nullable=True);event_fingerprint=Column(String(64),nullable=False,index=True);payload_json=Column(Text,nullable=False,default="{}",server_default="{}");processing_state=Column(String(24),nullable=False,default="PENDING",server_default="PENDING",index=True);attempts=Column(Integer,nullable=False,default=0,server_default="0");last_attempted_at=Column(DateTime,nullable=True);last_error=Column(Text,nullable=True);processed_at=Column(DateTime,nullable=True);created_at=Column(DateTime,nullable=False,default=lambda:datetime.now(timezone.utc),index=True)
    worker_id=Column(String(128),nullable=True,index=True);claimed_at=Column(DateTime,nullable=True);next_attempt_at=Column(DateTime,nullable=True,index=True);error_category=Column(String(48),nullable=True)


class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_events"
    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    operation_type = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=True, index=True)
    summary_json = Column(Text, nullable=False, default="{}", server_default="{}")
    correlation_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id = Column(Integer, primary_key=True)
    backup_identity = Column(String(128), nullable=False, unique=True, index=True)
    filename = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    source_database_fingerprint = Column(String(64), nullable=False)
    migration_version = Column(String(128), nullable=True)
    status = Column(String(24), nullable=False, default="VALID", server_default="VALID")
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class AnomalyConfiguration(Base):
    """Reviewed rules only; absence means descriptive fail-closed evaluation."""
    __tablename__ = "anomaly_configurations"
    __table_args__ = (UniqueConstraint("jurisdiction_id", "taxon_id", "configuration_version", name="uq_anomaly_configuration_version"),)
    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id", ondelete="RESTRICT"), nullable=False, index=True)
    taxon_id = Column(Integer, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True)
    configuration_version = Column(String(64), nullable=False)
    enabled_signal_types_json = Column(Text, nullable=False, default="[]", server_default="[]")
    spatial_rule_json = Column(Text, nullable=True)
    temporal_rule_json = Column(Text, nullable=True)
    mode = Column(String(32), nullable=False, default="DESCRIPTIVE_ONLY", server_default="DESCRIPTIVE_ONLY")
    environmental_context_json = Column(Text, nullable=False, default="{}", server_default="{}")
    minimum_evidence_json = Column(Text, nullable=False, default="{}", server_default="{}")
    algorithm_version = Column(String(64), nullable=False, default="marine-early-warning-v1", server_default="marine-early-warning-v1")
    automatic_evaluation_enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    provenance_json = Column(Text, nullable=False, default="{}", server_default="{}")
    limitations_json = Column(Text, nullable=False, default="[]", server_default="[]")
    review_status = Column(String(24), nullable=False, default="READY_FOR_REVIEW", server_default="READY_FOR_REVIEW", index=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    review_reference = Column(String(256), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    dependency_fingerprint = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    activated_at = Column(DateTime, nullable=True);deactivated_at=Column(DateTime,nullable=True);superseded_at=Column(DateTime,nullable=True);supersedes_configuration_id=Column(Integer,ForeignKey("anomaly_configurations.id",ondelete="RESTRICT"),nullable=True)


def _validate_anomaly_assessment_lifecycle_transition(
    current_state: str, new_state: str
) -> bool:
    """Lifecycle transition guard.

    Permitted transitions:
        CURRENT -> STALE
        STALE -> SUPERSEDED

    Reverse transitions are rejected. Any other transition is rejected.
    """
    return (current_state, new_state) in (("CURRENT", "STALE"), ("STALE", "SUPERSEDED"))


def _validate_anomaly_signal_uniqueness(existing_statuses, signal_type: str) -> bool:
    """Per-assessment per-signal-type uniqueness guard.

    Returns True if the new signal is allowed, False if a signal of
    the same type already exists for the assessment.
    """
    return signal_type not in existing_statuses


_ANOMALY_ASSESSMENT_IMMUTABLE_FIELDS = frozenset(
    {
        "observation_id", "jurisdiction_id", "species_program_id",
        "evaluated_species", "evaluated_species_source", "overall_status",
        "overall_classification", "assessment_confidence", "requires_review",
        "review_type", "provenance_version", "dependency_fingerprint",
        "generated_at", "evidence_summary_json", "limitations_json",
        "provenance_json",
    }
)


@event.listens_for(AnomalyAssessment, "before_update")
def _protect_anomaly_assessment_snapshot(_mapper, _connection, target):
    """Reject changes to scientific-result fields after insertion."""
    state = sa_inspect(target)
    changed = [
        name for name in _ANOMALY_ASSESSMENT_IMMUTABLE_FIELDS
        if state.attrs[name].history.has_changes()
    ]
    if changed:
        raise ValueError(
            "AnomalyAssessment scientific-result fields are immutable: "
            + ", ".join(sorted(changed))
        )

    history = state.attrs.current_state.history
    if history.has_changes() and history.deleted:
        old_state = history.deleted[0]
        new_state = history.added[0] if history.added else target.current_state
        if not _validate_anomaly_assessment_lifecycle_transition(old_state, new_state):
            raise ValueError(f"Invalid anomaly lifecycle transition: {old_state} -> {new_state}")


@event.listens_for(AnomalySignal, "before_update")
def _protect_anomaly_signal(_mapper, _connection, _target):
    """Signals are immutable snapshots; replacement requires a new assessment."""
    raise ValueError("AnomalySignal rows are immutable")


@event.listens_for(AnomalySynthesisSnapshot, "before_update")
def _protect_anomaly_synthesis_snapshot(_mapper, _connection, _target):
    """Durable conservative synthesis audit snapshots never change in place."""
    raise ValueError("AnomalySynthesisSnapshot rows are immutable")

@event.listens_for(AnomalyReviewEvent, "before_update")
def _protect_anomaly_review_event(_mapper, _connection, _target):
    raise ValueError("AnomalyReviewEvent rows are append-only")

@event.listens_for(AnomalyReviewEvent, "before_delete")
def _protect_anomaly_review_event_delete(_mapper, _connection, _target):
    raise ValueError("AnomalyReviewEvent rows are append-only")


_APPLICABILITY_IMMUTABLE_FIELDS = frozenset({
    "scientific_dataset_id", "jurisdiction_id", "evidence_role",
    "reconciliation_method", "reconciliation_version", "jurisdiction_boundary_id",
    "provenance_reference", "provenance_json", "provenance_fingerprint",
    "reviewed_by", "reviewed_at", "approved_by", "approved_at", "created_at",
})


@event.listens_for(ScientificDatasetApplicability, "before_update")
def _protect_dataset_applicability(_mapper, _connection, target):
    state = sa_inspect(target)
    changed = sorted(
        name for name in _APPLICABILITY_IMMUTABLE_FIELDS
        if state.attrs[name].history.has_changes()
    )
    if changed:
        raise ValueError("Dataset applicability assertions are immutable: " + ", ".join(changed))
    status = state.attrs.applicability_status.history
    if status.has_changes() and status.deleted:
        old = status.deleted[0]
        new = status.added[0] if status.added else target.applicability_status
        if new != "SUPERSEDED" or old == "SUPERSEDED":
            raise ValueError(f"Invalid applicability lifecycle transition: {old} -> {new}")


@event.listens_for(JurisdictionOnboardingRecord, "before_update")
def _protect_jurisdiction_onboarding_record(_mapper, _connection, _target):
    raise ValueError("JurisdictionOnboardingRecord rows are immutable")


@event.listens_for(ArtifactReference, "before_update")
def _protect_artifact_reference(_mapper, _connection, _target):
    raise ValueError("ArtifactReference rows are immutable")


@event.listens_for(OccurrenceCandidateReview, "before_update")
def _protect_occurrence_candidate_review(_mapper, _connection, _target):
    raise ValueError("OccurrenceCandidateReview rows are append-only")

@event.listens_for(OccurrenceCandidateReview, "before_delete")
def _prevent_occurrence_candidate_review_delete(_mapper, _connection, _target):
    raise ValueError("OccurrenceCandidateReview rows are append-only")


@event.listens_for(OccurrenceLegacyLink, "before_update")
def _protect_occurrence_legacy_link(_mapper, _connection, _target):
    raise ValueError("OccurrenceLegacyLink rows are immutable")

@event.listens_for(OccurrenceLegacyLink, "before_delete")
def _prevent_occurrence_legacy_link_delete(_mapper, _connection, _target):
    raise ValueError("OccurrenceLegacyLink rows are immutable")


@event.listens_for(EcologicalStatusAssertion, "before_update")
def _protect_ecological_status_assertion(_mapper, _connection, target):
    state = sa_inspect(target)
    allowed = {"lifecycle_state", "superseded_at"}
    changed = {name for name in state.attrs.keys() if state.attrs[name].history.has_changes()}
    if changed - allowed:
        raise ValueError("EcologicalStatusAssertion scientific fields are immutable")

@event.listens_for(ObservationOperationalEvent, "before_update")
def _immutable_observation_operational_event(mapper, connection, target):
    raise ValueError("ObservationOperationalEvent rows are append-only")

@event.listens_for(ObservationNotificationEvent, "before_update")
def _immutable_observation_notification_event(mapper, connection, target):
    changed={name for name in sa_inspect(target).attrs.keys() if sa_inspect(target).attrs[name].history.has_changes()}
    delivery_fields={"delivery_state","delivery_attempts","last_delivery_error","last_attempted_at","delivered_at"}
    if changed-delivery_fields:raise ValueError("ObservationNotificationEvent domain payload is immutable")
    if "lifecycle_state" in changed:
        history = state.attrs.lifecycle_state.history
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else target.lifecycle_state
        if old != "CURRENT" or new != "SUPERSEDED":
            raise ValueError(f"Invalid ecological assertion lifecycle transition: {old} -> {new}")


@event.listens_for(EcologicalStatusAssertion, "before_delete")
def _prevent_ecological_status_assertion_delete(_mapper, _connection, _target):
    raise ValueError("EcologicalStatusAssertion rows are immutable")
