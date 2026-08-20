from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    )

    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    country_code = Column(String(2), nullable=False)
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


class JurisdictionBoundary(Base):
    __tablename__ = "jurisdiction_boundaries"

    id = Column(Integer, primary_key=True, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    boundary_type = Column(String, nullable=False)
    geometry_json = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    source_version = Column(String, nullable=True)
    source_reference = Column(String, nullable=True)
    geometry_hash = Column(String(64), nullable=True, index=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    jurisdiction = relationship("Jurisdiction", back_populates="boundaries")


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
    )

    id = Column(Integer, primary_key=True, index=True)
    scientific_name = Column(String, nullable=False, index=True)
    common_name = Column(String, nullable=True)
    aphia_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE", server_default="ACTIVE")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    species_programs = relationship("SpeciesProgram", back_populates="species")
    jurisdiction_statuses = relationship("SpeciesJurisdictionStatus", back_populates="species", cascade="all, delete-orphan")


class SpeciesJurisdictionStatus(Base):
    __tablename__ = "species_jurisdiction_status"
    __table_args__ = (
        UniqueConstraint("species_id", "jurisdiction_id", name="uq_species_jurisdiction_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False, index=True)
    jurisdiction_id = Column(Integer, ForeignKey("jurisdictions.id"), nullable=False, index=True)
    ecological_status = Column(String(16), nullable=False)
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
    source_version = Column(String(64), nullable=True)
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
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "provenance_version",
            name="uq_anomaly_assessment_observation_version",
        ),
    )

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
