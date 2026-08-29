from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import logging
import time
from math import asin, cos, radians, sin, sqrt
import shutil
import tempfile
import uuid
import json
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from database import get_db
from models import (
    HistoricalEnvironmentalFeature,
    HistoricalOccurrence,
    Observation,
    Organization,
    OrganizationJurisdiction,
    OrganizationMembership,
    AuthSession,
    User,
    Region,
    Jurisdiction,
    JurisdictionBoundary,
    Investigation,
    FieldVisit,
    FieldObservation,
    NextAreaSnapshotCell,
    NextAreaSnapshotGeneration,
    Species,
    SpeciesJurisdictionStatus,
    SpeciesProgram,
    SuitabilityDeployment,
    PredictionTrainingEnvironmentalFeature,
    PredictionTrainingOccurrence,
    PredictionModelSample,
    JurisdictionOnboardingPreparation,
    JurisdictionOnboardingRecord,
    ScientificDatasetApplicability,
    RegionalTaxonRegistry,
    TaxonomyPreparation,
    LocalTaxonCandidate,
    OccurrenceAcquisitionPreparation,
    OccurrenceSourceRegistration,
    EcologicalStatusAssertion,
    EcologicalStatusSourceRegistration,
    EcologicalStatusIngestionRun,
    EcologicalStatusIngestionRow,
    GovernedPublicMedia,
    HabitatSuitabilityV3GridCell,
    ObservationOperationalCase,
    ObservationOperationalEvent,
    ObservationReviewerGrant,
    ObservationNotificationEvent,
    ReporterAdditionalInformation,
    ReporterAccessToken,
    PilotFeedback,
    GovernedOccurrenceEvidence,
    AnomalyAssessment,
    AnomalyConfiguration, AnomalyReviewEvent, AnomalyReviewAssignment,
    ScientificDomainEvent, ScientificReviewerGrant,
    BackupRecord,
    IdentificationMediaSource, IdentificationMediaAsset, IdentificationCorpus,
    IdentificationMediaAcquisitionRun, IdentificationMediaReviewEvent,
    IdentificationCorpusInclusion, IdentificationBenchmarkRun, ArtifactReference,
    OccurrenceAcquisitionBatch, OccurrenceAcquisitionBatchItem,
)
from sqlalchemy import func
from hotspot_service import HotspotService
from historical_spatial_service import HistoricalSpatialService
from prediction_training_occurrence_service import (
    GRID_SIZE as TRAINING_GRID_SIZE,
    TRAINING_REGION_NAME,
)
from prediction_model_dataset_service import PredictionModelDatasetService
from habitat_suitability_service import HabitatSuitabilityService
from species_jurisdiction_ecology import (
    get_ecological_status,
    get_ecological_status_payload,
)
from next_area_prediction_service import (
    PREDICTION_VERSION as NEXT_AREA_PREDICTION_VERSION,
    NextAreaPredictionService,
    RegenerationInProgressError,
)
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from auth_service import (
    create_session,
    hash_password,
    jurisdiction_roles,
    require_authenticated_user,
    require_platform_admin,
    require_operational_reviewer,
    require_review_jurisdiction,
    reviewer_jurisdiction_ids,
    require_roles,
    revoke_session,
    user_payload,
    verify_password,
    require_scientific_reviewer, require_scientific_jurisdiction,
    scientific_reviewer_jurisdiction_ids,
)

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from platform_config import settings
from production_operations import EventWorker, audit, create_backup, rate_limiter, readiness_report
from migration_manager import current_versions

from marine_observation_service import MarineObservationService
from jurisdiction_resolution_service import JurisdictionResolutionService
from jurisdiction_onboarding_service import JurisdictionOnboardingService
from bulk_scientific_readiness import SPECIES_BASELINE_PREPARE_CONTRACT
from jurisdiction_taxon_readiness import JurisdictionTaxonReadinessService
from taxonomy_preparation_service import TaxonomyPreparationService
from regional_taxonomy_bulk_service import RegionalTaxonomyBulkService
from local_taxon_candidate_service import LocalTaxonCandidateService
from regional_taxon_manifest_service import RegionalTaxonManifestService
from occurrence_evidence_service import OccurrenceEvidenceService
from occurrence_source_governance import OccurrenceSourceGovernanceService
from occurrence_candidate_review import OccurrenceCandidateReviewService
from ecological_status_governance import EcologicalStatusGovernanceService
from ecological_status_source_governance import EcologicalStatusSourceGovernanceService
from ecological_status_ingestion import EcologicalStatusIngestionService
from ecological_status_read_service import EcologicalStatusReadService
from public_media_service import PublicMediaService
from observation_operations_service import ObservationOperationsService
from pilot_readiness_service import NotificationDeliveryService, ReporterAccessService
from regional_scientific_scaling import RegionalScientificScalingService
from early_warning_service import EarlyWarningService
from early_warning_operations import EarlyWarningOperations
from anomaly_repository import canonical_json
from suitability_deployment_governance import SuitabilityDeploymentGovernance
from scientific_corpus_service import parse_manifest_content, storage_contract, TAXON_GROUPS
from identification_corpus_service import (MediaSourceGovernanceService,
    IdentificationCorpusService, AcquisitionRunService, IdentificationBenchmarkService)
from occurrence_batch_service import OccurrenceBatchService

class VerificationRequest(BaseModel):
    status: str
    verified_species: Optional[str] = None
    notes: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class InvestigationCreateRequest(BaseModel):
    title: str
    objective: str
    priority: str
    assigned_organization_id: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source_type: str
    source_observation_id: Optional[int] = None
    source_prediction_generation_id: Optional[int] = None
    source_prediction_cell_id: Optional[str] = None


class InvestigationUpdateRequest(BaseModel):
    title: Optional[str] = None
    objective: Optional[str] = None
    priority: Optional[str] = None
    assigned_organization_id: Optional[int] = None
    outcome_summary: Optional[str] = None


class InvestigationStatusRequest(BaseModel):
    status: str
    outcome_summary: Optional[str] = None


class FieldVisitWriteRequest(BaseModel):
    organization_id: Optional[int] = None
    visited_at: datetime
    latitude: float
    longitude: float
    survey_method: str
    effort_duration_minutes: int
    area_description: Optional[str] = None
    conditions_notes: Optional[str] = None
    target_detection_status: str
    notes: Optional[str] = None
    status: str = "DRAFT"


class FieldVisitUpdateRequest(BaseModel):
    organization_id: Optional[int] = None
    visited_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    survey_method: Optional[str] = None
    effort_duration_minutes: Optional[int] = None
    area_description: Optional[str] = None
    conditions_notes: Optional[str] = None
    target_detection_status: Optional[str] = None
    notes: Optional[str] = None


class FieldObservationRequest(BaseModel):
    scientific_name: str
    count_observed: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: Optional[str] = None


class AdminRegionRequest(BaseModel):
    name: str
    slug: str
    status: str = "ACTIVE"


class AdminRegionUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    status: Optional[str] = None


class AdminJurisdictionRequest(BaseModel):
    region_id: int
    name: str
    slug: str
    country_code: str
    status: str = "ACTIVE"
    center_latitude: float
    center_longitude: float
    default_zoom: float


class AdminJurisdictionUpdateRequest(BaseModel):
    region_id: Optional[int] = None
    name: Optional[str] = None
    slug: Optional[str] = None
    country_code: Optional[str] = None
    status: Optional[str] = None
    center_latitude: Optional[float] = None
    center_longitude: Optional[float] = None
    default_zoom: Optional[float] = None


class AdminJurisdictionPrepareRequest(BaseModel):
    canonical_name: str
    canonical_identifier_scheme: str
    canonical_identifier: str
    jurisdiction_type: str
    region_id: int
    sovereign_parent_id: Optional[int] = None
    boundary_provider: str
    provider_boundary_identifier: str
    expected_provider_iso: str
    boundary_type: str = "MARINE_MONITORING"
    provider_version: str


class AdminJurisdictionBulkPrepareRequest(BaseModel):
    items: list[AdminJurisdictionPrepareRequest]


class AdminJurisdictionApprovalRequest(BaseModel):
    approval_reference: str
    expected_manifest_fingerprint: str


class AdminJurisdictionBatchApplyRequest(BaseModel):
    preparation_ids: list[int]

class AdminTaxonomyPrepareRequest(BaseModel):
    taxon_id: int
    region_id: int

class AdminTaxonomyApprovalRequest(BaseModel):
    expected_preparation_fingerprint: str
    approval_reference: str

class AdminRegionalTaxonCandidate(BaseModel):
    submitted_scientific_name: str
    submitted_identifier_scheme: Optional[str] = None
    submitted_identifier: Optional[str] = None
    candidate_source: str = "ADMIN_SUBMISSION"
    source_reference: Optional[str] = None
    source_artifact_reference: Optional[str] = None
    source_artifact_sha256: Optional[str] = None
    discovery_method: str = "EXPLICIT_NAME"
    discovery_version: str = "regional-taxonomy-candidate-v1"
    provenance: Optional[dict] = None
    limitations: list[str] = Field(default_factory=list)

class AdminTaxonomyBulkPrepareRequest(BaseModel):
    candidates: list[AdminRegionalTaxonCandidate]
    dry_run: bool = True

class AdminTaxonomyBatchApprovalRequest(BaseModel):
    preparation_ids: list[int]
    approval_reference: str

class AdminTaxonomyBatchApplyRequest(BaseModel):
    preparation_ids: list[int]
class AdminLocalTaxonCandidateBatchRequest(BaseModel):
    candidate_ids: list[int]
    approval_reference: Optional[str] = None

class AdminRegionalTaxonManifestRequest(BaseModel):
    manifest_id: str
    manifest_version: str
    region_id: int
    operator_reference: str
    provenance: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    configuration: dict = Field(default_factory=lambda: {"provider_resolution": "GOVERNED_DEFAULT"})
    candidates: list[AdminRegionalTaxonCandidate]

class AdminManifestSelectionRequest(BaseModel):
    item_ids: list[int]
    approval_reference: Optional[str] = None

class AdminCorpusManifestParseRequest(BaseModel):
    input_format: str = "PASTED_NAMES"
    content: str

class AdminMediaSourceRequest(BaseModel):
    registration_key: str; scientific_provider: str; transport_interface: Optional[str] = None
    documentation_reference: str; licensing_model: str; attribution_requirements: str; access_method: str
    taxonomic_scope: dict = Field(default_factory=dict); geographic_scope: dict = Field(default_factory=dict)
    provider_version: Optional[str] = None; acquisition_configuration: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict); limitations: list[str] = Field(default_factory=list)
class AdminMediaSourceTransitionRequest(BaseModel): target_state: str; reference: str
class AdminMediaAcquisitionRequest(BaseModel): media_source_id: int; taxon_id: int; request: dict = Field(default_factory=dict)
class AdminMediaReviewRequest(BaseModel): decision: str; reference: str
class AdminCorpusRequest(BaseModel):
    corpus_key: str; version: str; intended_purpose: str
    taxonomic_scope: dict = Field(default_factory=dict); configuration: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict); limitations: list[str] = Field(default_factory=list)
class AdminCorpusInclusionRequest(BaseModel):
    asset_ids: list[int]; seed: str = "visual-corpus-v1"; split_recommended: bool = True
class AdminCorpusTransitionRequest(BaseModel): target_state: str; reference: str
class AdminBenchmarkRequest(BaseModel):
    corpus_id: int; model_identity: str; model_version: str; model_hash: Optional[str] = None
    split_name: str; inference_configuration: dict = Field(default_factory=dict)
class AdminOccurrenceBatchRequest(BaseModel):
    region_id: int; batch_key: str; items: list[dict]; configuration: dict = Field(default_factory=dict)

class AdminOccurrencePreparationRequest(BaseModel):
    jurisdiction_id: int
    taxon_id: int
    source_key: str
    dry_run: bool = False

class AdminOccurrenceReviewRequest(BaseModel):
    candidate_ids: list[int]
    review_reference: Optional[str] = None
    disposition: Optional[str] = None
    evidence_note: Optional[str] = None

class AdminOccurrenceSourceRequest(BaseModel):
    source_registration_id: str
    source_name: str
    scientific_provider: str
    transport_interface: Optional[str] = None
    provider_dataset_id: Optional[str] = None
    provider_dataset_version: Optional[str] = None
    acquisition_mechanism: str
    documentation_reference: str
    license: str
    reuse_conditions: str
    geographic_scope: dict = Field(default_factory=dict)
    taxonomic_scope: dict = Field(default_factory=dict)
    source_provenance: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    configuration: dict = Field(default_factory=dict)
    configuration_version: str

class AdminOccurrenceSourceReviewRequest(BaseModel):
    approval_reference: str

class AdminEcologicalStatusRow(BaseModel):
    scientific_name: str
    authoritative_identifier_scheme: Optional[str] = None
    authoritative_identifier: Optional[str] = None
    statuses: list[str]
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    notes: Optional[str] = None

class AnomalyDispositionRequest(BaseModel):
    state: str
    reason: str = Field(min_length=1, max_length=2000)

class ScientificReviewerGrantRequest(BaseModel):
    user_id:int; jurisdiction_id:int; reference:str=Field(min_length=1,max_length=256)
class AnomalyClaimRequest(BaseModel):
    reviewer_user_id:Optional[int]=None; reason:str=Field(min_length=1,max_length=1000)
class AnomalyConfigRequest(BaseModel):
    jurisdiction_id:int;taxon_id:int;configuration_version:str;mode:str="DESCRIPTIVE_ONLY";enabled_signal_types:list[str]=[];spatial_rule:Optional[dict]=None;temporal_rule:Optional[dict]=None;minimum_evidence:dict={};environmental_context:dict={};provenance:dict={};limitations:list[str]=[]
class AnomalyConfigTransitionRequest(BaseModel):
    target_state:str;reference:Optional[str]=None
class ScientificEventRequest(BaseModel):
    event_type:str;jurisdiction_id:int;taxon_id:Optional[int]=None;observation_id:Optional[int]=None;dependency_reference:Optional[str]=None;payload:dict={}

class AdminEcologicalStatusPreparationRequest(BaseModel):
    jurisdiction_id: int
    source_organization: str
    source_title: str
    source_version: Optional[str] = None
    publication_date: Optional[str] = None
    source_reference: str
    evidence_type: str
    authority_classification: str
    geographic_scope: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    assertions: list[AdminEcologicalStatusRow]
    dry_run: bool = False

class AdminEcologicalStatusReviewRequest(BaseModel):
    candidate_ids: list[int]
    review_reference: str
    disposition: str = "APPROVED"

class AdminEcologicalSourceRequest(BaseModel):
    source_registration_id: str
    source_organization: str
    source_title: str
    source_type: str
    scope_type: str
    jurisdiction_id: Optional[int] = None
    region_id: Optional[int] = None
    source_version: Optional[str] = None
    publication_date: Optional[str] = None
    source_reference: str
    documentation_reference: Optional[str] = None
    license: str
    reuse_terms: str
    acquisition_method: str = "CONTROLLED_UPLOAD"
    expected_semantics: dict = Field(default_factory=dict)
    field_mapping: dict = Field(default_factory=dict)
    semantic_mapping: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    configuration_version: str

class AdminEcologicalSourceReviewRequest(BaseModel):
    review_reference: str

class AdminEcologicalIngestionReviewRequest(BaseModel):
    row_ids: list[int]
    disposition: str = "APPROVED"
    review_reference: str

class AdminPublicMediaRequest(BaseModel):
    media_type: str
    taxon_id: Optional[int] = None
    observation_id: Optional[int] = None
    source_provider: str
    creator: Optional[str] = None
    source_reference: str
    license: str
    attribution_text: str
    remote_url: Optional[str] = None
    artifact_reference_id: Optional[int] = None
    provenance_json: str = "{}"
    limitations_json: str = "[]"

class ObservationOperationRequest(BaseModel):
    reviewer_user_id: Optional[int] = None
    priority: Optional[str] = None
    disposition: Optional[str] = None
    species: Optional[str] = None
    reason: Optional[str] = None
    expected_reviewer_user_id: Optional[int] = None

class ReviewerGrantRequest(BaseModel):
    user_id: int
    jurisdiction_id: int
    grant_reference: str
class PilotFeedbackRequest(BaseModel):
    category: str
    feedback_text: str
    page_context: Optional[str] = None
    jurisdiction_id: int
class ReporterResponseRequest(BaseModel):
    response_text: str


class AdminOrganizationRequest(BaseModel):
    name: str
    slug: str
    organization_type: str
    status: str = "ACTIVE"


class AdminOrganizationUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    organization_type: Optional[str] = None
    status: Optional[str] = None


class AdminParticipationRequest(BaseModel):
    jurisdiction_id: int
    status: str = "ACTIVE"


class AdminParticipationUpdateRequest(BaseModel):
    status: str


class AdminUserRequest(BaseModel):
    email: str
    display_name: str
    initial_password: str
    status: str = "ACTIVE"
    organization_name: Optional[str] = None
    job_title: Optional[str] = None


class AdminUserUpdateRequest(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None
    organization_name: Optional[str] = None
    job_title: Optional[str] = None

class PilotFeedbackUpdateRequest(BaseModel):
    state: str
    admin_disposition: Optional[str] = None


class AdminMembershipRequest(BaseModel):
    organization_id: int
    role: str
    status: str = "ACTIVE"


class AdminMembershipUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None
# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Marine Observation API",
    description=(
        "Marine species identification and "
        "regional anomaly analysis."
    ),
    version="0.1.0",
)
if settings.production_like and settings.validate():
    raise RuntimeError("Invalid deployment configuration: " + "; ".join(settings.validate()))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
UPLOAD_DIRECTORY = settings.upload_directory

UPLOAD_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
)

logging.basicConfig(level=getattr(logging,settings.log_level,"INFO"),format="%(message)s")
api_logger=logging.getLogger("marine_platform.api")

@app.middleware("http")
async def request_observability(request:Request,call_next):
    correlation_id=request.headers.get("X-Request-ID") or uuid.uuid4().hex;request.state.correlation_id=correlation_id;started=time.perf_counter()
    try:response=await call_next(request)
    except Exception:
        api_logger.exception(json.dumps({"event":"request_failed","correlation_id":correlation_id,"method":request.method,"route":request.url.path},separators=(",",":")))
        return JSONResponse(status_code=500,content={"error":{"category":"INTERNAL_FAILURE","message":"The request could not be completed.","correlation_id":correlation_id}})
    response.headers["X-Request-ID"]=correlation_id
    api_logger.info(json.dumps({"event":"request_completed","correlation_id":correlation_id,"method":request.method,"route":request.url.path,"status":response.status_code,"duration_ms":round((time.perf_counter()-started)*1000,2)},separators=(",",":")))
    return response

@app.exception_handler(HTTPException)
async def controlled_http_error(request:Request,exc:HTTPException):
    categories={400:"VALIDATION_ERROR",401:"AUTHENTICATION_FAILURE",403:"AUTHORIZATION_FAILURE",404:"NOT_FOUND",409:"CONFLICT",422:"VALIDATION_ERROR",429:"RATE_LIMITED",503:"PROVIDER_UNAVAILABLE"}
    return JSONResponse(status_code=exc.status_code,headers=exc.headers,content={"error":{"category":categories.get(exc.status_code,"REQUEST_FAILURE"),"message":exc.detail,"correlation_id":getattr(request.state,"correlation_id",None)}})

# Observation uploads are private evidence. Public governed media uses its
# separately reviewed remote/artifact references and never this filesystem.
# ============================================================
# LOAD SERVICE ONCE
# ============================================================

service = MarineObservationService()
hotspot_service = HotspotService(
    grid_size=0.1
)
auth_bearer = HTTPBearer(auto_error=False)
historical_spatial_service = HistoricalSpatialService(
    grid_size=0.1
)
prediction_model_dataset_service = PredictionModelDatasetService()
habitat_suitability_service = HabitatSuitabilityService()
jurisdiction_resolution_service = JurisdictionResolutionService()


@app.get("/geography/resolve")
def resolve_geography(
    latitude: float,
    longitude: float,
    db: Session = Depends(get_db),
):
    try:
        return jurisdiction_resolution_service.resolve(db, latitude, longitude)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/auth/login")
def login(payload: LoginRequest, request:Request, db: Session = Depends(get_db)):
    key=f"login:{request.client.host if request.client else 'unknown'}"
    if not rate_limiter.allow(key,settings.rate_limit_login_per_minute):raise HTTPException(429,"Too many login attempts. Try again shortly.")
    user = db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first()
    if user is None or user.status != "ACTIVE" or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_session(db, user)
    return {"access_token": token, "token_type": "bearer", "user": user_payload(db, user)}


@app.get("/auth/me")
def auth_me(current_user: User = Depends(require_authenticated_user), db: Session = Depends(get_db)):
    return user_payload(db, current_user)


@app.post("/auth/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(auth_bearer),
    db: Session = Depends(get_db),
):
    revoke_session(db, credentials)
    return {"message": "Signed out."}


@app.get("/admin/users")
def get_trusted_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    users = db.query(User).order_by(User.display_name, User.email).all()
    return {"count": len(users), "users": [user_payload(db, item) for item in users]}


ADMIN_STATUSES = {"ACTIVE", "INACTIVE"}
ADMIN_ROLES = {"VIEWER", "REVIEWER", "MANAGER"}
ADMIN_ORGANIZATION_TYPES = {"GOVERNMENT_AGENCY", "RESEARCH_INSTITUTION", "UNIVERSITY", "CONSERVATION_ORGANIZATION", "OTHER"}


def _admin_status(value):
    status = value.upper()
    if status not in ADMIN_STATUSES:
        raise HTTPException(status_code=400, detail="Status must be ACTIVE or INACTIVE.")
    return status


def _admin_slug(value):
    slug = value.strip().lower()
    if not slug or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in slug):
        raise HTTPException(status_code=400, detail="Slug must contain only lowercase letters, numbers, and hyphens.")
    return slug


def _admin_region_payload(item):
    return {"id": item.id, "name": item.name, "slug": item.slug, "status": item.status, "jurisdiction_count": len(item.jurisdictions), "created_at": item.created_at, "updated_at": item.updated_at}


def _admin_jurisdiction_payload(item):
    active_links = [link for link in item.organization_links if link.status == "ACTIVE" and link.organization.status == "ACTIVE"]
    user_ids = {membership.user_id for link in active_links for membership in link.organization.memberships if membership.status == "ACTIVE" and membership.user.status == "ACTIVE"}
    boundaries = [{"id": boundary.id, "boundary_type": boundary.boundary_type, "status": boundary.status, "source": boundary.source, "source_version": boundary.source_version, "source_reference": boundary.source_reference, "geometry_hash": boundary.geometry_hash, "created_at": boundary.created_at, "updated_at": boundary.updated_at} for boundary in item.boundaries]
    return {**_jurisdiction_payload(item), "region": {"id": item.region.id, "name": item.region.name, "slug": item.region.slug, "status": item.region.status}, "participating_organization_count": len(active_links), "trusted_user_count": len(user_ids), "boundaries": boundaries, "created_at": item.created_at, "updated_at": item.updated_at}


def _admin_organization_payload(item):
    return {**_organization_payload(item), "memberships": [{"id": membership.id, "user": {"id": membership.user.id, "display_name": membership.user.display_name, "email": membership.user.email, "status": membership.user.status}, "role": membership.role, "status": membership.status} for membership in item.memberships], "created_at": item.created_at, "updated_at": item.updated_at}


def _require_admin_record(db, model, identifier, label):
    item = db.query(model).filter(model.id == identifier).first()
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    return item


@app.get("/admin/overview")
def admin_overview(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    jurisdictions = db.query(Jurisdiction).all(); organizations = db.query(Organization).all()
    warnings = []
    for jurisdiction in jurisdictions:
        if not any(boundary.status == "ACTIVE" and boundary.boundary_type == "MARINE_MONITORING" for boundary in jurisdiction.boundaries): warnings.append({"type": "JURISDICTION_WITHOUT_BOUNDARY", "jurisdiction_id": jurisdiction.id, "message": f"{jurisdiction.name} has no active monitoring boundary."})
        active_links = [link for link in jurisdiction.organization_links if link.status == "ACTIVE" and link.organization.status == "ACTIVE"]
        if not active_links: warnings.append({"type": "JURISDICTION_WITHOUT_ORGANIZATION", "jurisdiction_id": jurisdiction.id, "message": f"{jurisdiction.name} has no active participating organization."})
        if not any(membership.status == "ACTIVE" and membership.role == "MANAGER" and membership.user.status == "ACTIVE" for link in active_links for membership in link.organization.memberships): warnings.append({"type": "JURISDICTION_WITHOUT_MANAGER", "jurisdiction_id": jurisdiction.id, "message": f"{jurisdiction.name} has no active jurisdiction manager."})
        capabilities = _jurisdiction_capabilities(jurisdiction)
        if not capabilities["habitat_suitability"]: warnings.append({"type": "SUITABILITY_NOT_CONFIGURED", "jurisdiction_id": jurisdiction.id, "message": f"{jurisdiction.name} habitat suitability is not configured."})
        if not capabilities["monitoring_priority"]: warnings.append({"type": "MONITORING_PRIORITY_NOT_CONFIGURED", "jurisdiction_id": jurisdiction.id, "message": f"{jurisdiction.name} Monitoring Priority is not configured."})
    for organization in organizations:
        if not any(membership.status == "ACTIVE" and membership.user.status == "ACTIVE" for membership in organization.memberships): warnings.append({"type": "ORGANIZATION_WITHOUT_ACTIVE_MEMBERS", "organization_id": organization.id, "message": f"{organization.name} has no active members."})
    return {"counts": {"regions": db.query(Region).count(), "active_jurisdictions": db.query(Jurisdiction).filter(Jurisdiction.status == "ACTIVE").count(), "organizations": len(organizations), "trusted_users": db.query(User).count()}, "warnings": warnings}


@app.get("/admin/regions")
def admin_regions(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    items = db.query(Region).order_by(Region.name).all(); return {"count": len(items), "regions": [_admin_region_payload(item) for item in items]}


@app.post("/admin/regions")
def admin_create_region(payload: AdminRegionRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    slug = _admin_slug(payload.slug)
    if db.query(Region).filter(func.lower(Region.slug) == slug).first(): raise HTTPException(status_code=409, detail="Region slug already exists.")
    if not payload.name.strip(): raise HTTPException(status_code=400, detail="Region name is required.")
    item = Region(name=payload.name.strip(), slug=slug, status=_admin_status(payload.status)); db.add(item); db.commit(); db.refresh(item); return _admin_region_payload(item)


@app.patch("/admin/regions/{region_id}")
def admin_update_region(region_id: int, payload: AdminRegionUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, Region, region_id, "Region"); values = payload.model_dump(exclude_unset=True)
    if "slug" in values:
        values["slug"] = _admin_slug(values["slug"]); duplicate = db.query(Region).filter(func.lower(Region.slug) == values["slug"], Region.id != item.id).first()
        if duplicate: raise HTTPException(status_code=409, detail="Region slug already exists.")
    if "name" in values and not values["name"].strip(): raise HTTPException(status_code=400, detail="Region name cannot be empty.")
    if "status" in values: values["status"] = _admin_status(values["status"])
    for key, value in values.items(): setattr(item, key, value.strip() if key == "name" else value)
    db.commit(); db.refresh(item); return _admin_region_payload(item)


@app.get("/admin/jurisdictions")
def admin_jurisdictions(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    items = db.query(Jurisdiction).order_by(Jurisdiction.name).all(); return {"count": len(items), "jurisdictions": [_admin_jurisdiction_payload(item) for item in items]}


@app.get("/admin/jurisdictions/{jurisdiction_id}")
def admin_jurisdiction_detail(jurisdiction_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, Jurisdiction, jurisdiction_id, "Jurisdiction")
    records = db.query(JurisdictionOnboardingRecord).filter_by(jurisdiction_id=item.id).order_by(JurisdictionOnboardingRecord.created_at.desc()).all()
    return {**_admin_jurisdiction_payload(item), "onboarding_history": [{"id": record.id, "manifest_version": record.manifest_version, "manifest_fingerprint": record.manifest_fingerprint, "action_performed": record.action_performed, "approval_state": record.approval_state, "operator_reference": record.operator_reference, "applied_at": record.applied_at, "boundary_id": record.boundary_id} for record in records]}


def _onboarding_preparation_payload(row):
    manifest = json.loads(row.manifest_json)
    artifact = {}
    try:
        artifact = json.loads(Path(row.boundary_artifact_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {
        "id": row.id, "region_id": row.region_id, "jurisdiction": row.canonical_name,
        "canonical_identifier_scheme": row.canonical_identifier_scheme,
        "canonical_identifier": row.canonical_identifier,
        "jurisdiction_type": row.jurisdiction_type, "workflow_state": row.workflow_state,
        "manifest_version": row.manifest_version,
        "manifest_fingerprint": row.manifest_fingerprint,
        "boundary_provider": row.boundary_provider,
        "boundary_provider_version": artifact.get("provider_version") or manifest.get("provider_version"),
        "provider_boundary_identifier": row.provider_boundary_identifier,
        "boundary_type": artifact.get("boundary_type"), "crs": artifact.get("crs"),
        "geometry_validation_state": "VALID" if artifact.get("geometry_valid") is True else "UNAVAILABLE",
        "boundary_source_sha256": row.boundary_source_sha256,
        "geometry_sha256": row.geometry_sha256,
        "approval_reference": row.approval_reference, "approved_at": row.approved_at,
        "applied_at": row.applied_at,
        "resulting_jurisdiction_id": row.resulting_jurisdiction_id,
        "resulting_boundary_id": row.resulting_boundary_id,
        "last_error": row.last_error, "created_at": row.created_at,
    }


def _onboarding_error(exc):
    message = str(exc)
    status = 409 if any(word in message.lower() for word in ("stale", "conflict", "already")) else 400
    raise HTTPException(status_code=status, detail=message)


@app.post("/admin/jurisdiction-onboarding/prepare")
def admin_prepare_jurisdiction(payload: AdminJurisdictionPrepareRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try:
        row = JurisdictionOnboardingService(db).prepare(payload.model_dump())
        db.commit(); db.refresh(row)
        return _onboarding_preparation_payload(row)
    except Exception as exc:
        db.rollback(); _onboarding_error(exc)


@app.post("/admin/jurisdiction-onboarding/prepare-bulk")
def admin_prepare_jurisdictions(payload: AdminJurisdictionBulkPrepareRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    results = []
    for item in payload.items:
        try:
            row = JurisdictionOnboardingService(db).prepare(item.model_dump())
            db.commit(); db.refresh(row)
            results.append({"jurisdiction": item.canonical_name, "status": "READY", "preparation": _onboarding_preparation_payload(row)})
        except Exception as exc:
            db.rollback(); results.append({"jurisdiction": item.canonical_name, "status": "BLOCKED", "reason": str(exc)})
    return {"results": results}


def _region_onboarding_plan(db, region, persist, selected_identifiers=None):
    inventory = json.loads(Path("artifacts/onboarding/caribbean-jurisdiction-candidates-v1.json").read_text(encoding="utf-8"))
    manifests = {}
    for path in Path("artifacts/onboarding").glob("*-onboarding-manifest-v1.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")); identity = value.get("jurisdiction", {})
            if value.get("region") == region.slug:
                manifests[(identity.get("canonical_identifier_scheme"), identity.get("canonical_identifier"))] = path
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    results = []
    for entry in inventory["entries"]:
        if entry.get("parent_region_identifier") != region.slug:
            continue
        if selected_identifiers is not None and entry["canonical_identifier"] not in selected_identifiers:
            continue
        identity = (entry["canonical_identifier_scheme"], entry["canonical_identifier"])
        base = {"jurisdiction": entry["canonical_name"], "canonical_identifier_scheme": identity[0], "canonical_identifier": identity[1], "jurisdiction_type": entry["jurisdiction_type"]}
        existing = db.query(Jurisdiction).filter_by(canonical_identifier_scheme=identity[0], canonical_identifier=identity[1]).one_or_none()
        if existing:
            science_count = db.query(SpeciesProgram).filter_by(jurisdiction_id=existing.id).count() + db.query(SpeciesJurisdictionStatus).filter_by(jurisdiction_id=existing.id).count() + db.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=existing.id).count()
            results.append({**base, "status": "ALREADY_ONBOARDED", "jurisdiction_id": existing.id, "scientific_state": "CONFIGURED" if science_count else "SCIENTIFICALLY_EMPTY"}); continue
        preparation = db.query(JurisdictionOnboardingPreparation).filter_by(region_id=region.id, canonical_identifier_scheme=identity[0], canonical_identifier=identity[1]).order_by(JurisdictionOnboardingPreparation.id.desc()).first()
        if preparation:
            results.append({**base, "status": preparation.workflow_state, "preparation_id": preparation.id, "scientific_state": "SCIENTIFICALLY_EMPTY"}); continue
        classification = entry["review_classification"]
        if classification == "REQUIRES_IDENTIFIER_VALIDATION":
            results.append({**base, "status": "REQUIRES_REVIEW", "reason": "IDENTIFIER_VALIDATION", "scientific_state": "SCIENTIFICALLY_EMPTY"}); continue
        if classification != "READY_FOR_ONBOARDING":
            results.append({**base, "status": "REQUIRES_REVIEW", "reason": "SCOPE_DECISION", "scientific_state": "SCIENTIFICALLY_EMPTY"}); continue
        path = manifests.get(identity)
        if path is None:
            results.append({**base, "status": "BLOCKED", "reason": "UNAVAILABLE_BOUNDARY_METADATA", "scientific_state": "SCIENTIFICALLY_EMPTY"}); continue
        if persist:
            try:
                row = JurisdictionOnboardingService(db).prepare_from_manifest(path)
                db.commit(); db.refresh(row)
                results.append({**base, "status": "READY_FOR_REVIEW", "preparation_id": row.id, "scientific_state": "SCIENTIFICALLY_EMPTY"})
            except Exception as exc:
                db.rollback(); results.append({**base, "status": "CONFLICT", "reason": str(exc), "scientific_state": "SCIENTIFICALLY_EMPTY"})
        else:
            results.append({**base, "status": "READY", "scientific_state": "SCIENTIFICALLY_EMPTY"})
    return results


@app.post("/admin/regions/{region_id}/jurisdiction-onboarding/prepare")
def admin_prepare_region_jurisdictions(region_id: int, dry_run: bool = Query(True), canonical_identifiers: Optional[str] = Query(None), db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    region = _require_admin_record(db, Region, region_id, "Region")
    selected = {value.strip().upper() for value in canonical_identifiers.split(",") if value.strip()} if canonical_identifiers else None
    results = _region_onboarding_plan(db, region, not dry_run, selected)
    counts = {status: sum(item["status"] == status for item in results) for status in ("READY", "READY_FOR_REVIEW", "APPROVED", "APPLIED", "ALREADY_ONBOARDED", "REQUIRES_REVIEW", "BLOCKED", "CONFLICT")}
    return {"region": region.slug, "dry_run": dry_run, "total": len(results), "counts": counts, "results": results}


@app.post("/admin/jurisdiction-onboarding/apply-batch")
def admin_apply_onboarding_batch(payload: AdminJurisdictionBatchApplyRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try:
        return {"results": JurisdictionOnboardingService(db).apply_batch(payload.preparation_ids, f"user:{current_user.id}")}
    except Exception as exc:
        db.rollback(); _onboarding_error(exc)


@app.get("/admin/jurisdiction-onboarding/{preparation_id}")
def admin_onboarding_detail(preparation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    return _onboarding_preparation_payload(_require_admin_record(db, JurisdictionOnboardingPreparation, preparation_id, "Onboarding preparation"))


@app.post("/admin/jurisdiction-onboarding/{preparation_id}/approve")
def admin_approve_onboarding(preparation_id: int, payload: AdminJurisdictionApprovalRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    row = _require_admin_record(db, JurisdictionOnboardingPreparation, preparation_id, "Onboarding preparation")
    if payload.expected_manifest_fingerprint != row.manifest_fingerprint:
        raise HTTPException(status_code=409, detail="Manifest fingerprint changed; approval refused.")
    try:
        JurisdictionOnboardingService(db).approve(row, current_user.id, payload.approval_reference)
        db.commit(); db.refresh(row); return _onboarding_preparation_payload(row)
    except Exception as exc:
        db.rollback(); _onboarding_error(exc)


@app.post("/admin/jurisdiction-onboarding/{preparation_id}/apply")
def admin_apply_onboarding(preparation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    row = _require_admin_record(db, JurisdictionOnboardingPreparation, preparation_id, "Onboarding preparation")
    try:
        return JurisdictionOnboardingService(db).apply(row, f"user:{current_user.id}")
    except Exception as exc:
        db.rollback(); _onboarding_error(exc)


@app.get("/admin/regions/{region_id}/species-baseline/contract")
def admin_species_baseline_contract(region_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    region = _require_admin_record(db, Region, region_id, "Region")
    return {"region": {"id": region.id, "slug": region.slug}, **SPECIES_BASELINE_PREPARE_CONTRACT}


def _admin_taxon_payload(taxon):
    scheme = taxon.authoritative_identifier_scheme or ("WORMS_APHIA_ID" if taxon.aphia_id else None)
    identifier = taxon.authoritative_identifier or taxon.aphia_id
    return {"id": taxon.id, "canonical_scientific_name": taxon.scientific_name,
            "common_name": taxon.common_name, "taxonomic_rank": taxon.taxonomic_rank or ("SPECIES" if taxon.aphia_id else "UNKNOWN"),
            "authoritative_identifier_scheme": scheme, "authoritative_identifier": identifier,
            "accepted_name_status": taxon.accepted_name_status or ("ACCEPTED" if taxon.aphia_id else "UNRESOLVED"),
            "accepted_taxon_id": taxon.accepted_taxon_id, "parent_taxon_id": taxon.parent_taxon_id,
            "authorship": taxon.authorship, "provenance_version": taxon.provenance_version,
            "provenance_fingerprint": taxon.provenance_fingerprint, "status": taxon.status}

def _taxonomy_preparation_payload(row):
    manifest=json.loads(row.manifest_json)
    return {"id":row.id,"taxon_id":row.taxon_id,"region_id":row.region_id,"provider":row.provider,"provider_version":manifest.get("provider_version"),"provider_reference":manifest.get("provider_reference"),"authoritative_identifier_scheme":row.authoritative_identifier_scheme,"authoritative_identifier":row.authoritative_identifier,"proposed_scientific_name":row.proposed_scientific_name,"proposed_rank":row.proposed_rank,"proposed_accepted_name_status":row.proposed_accepted_name_status,"proposed_accepted_identifier":row.proposed_accepted_identifier,"proposed_parent_identifier":row.proposed_parent_identifier,"proposed_parent_name":manifest.get("parent_name"),"proposed_authorship":row.proposed_authorship,"classification":manifest.get("classification",[]),"reconciliation_result":row.reconciliation_result,"limitations":json.loads(row.limitations_json),"raw_artifact_sha256":row.raw_artifact_sha256,"preparation_fingerprint":row.preparation_fingerprint,"workflow_status":row.workflow_status,"prepared_by":row.prepared_by,"prepared_at":row.prepared_at,"approval_reference":row.approval_reference,"approved_at":row.approved_at,"applied_at":row.applied_at,"registry_entry_id":row.registry_entry_id}

@app.post("/admin/taxonomy/prepare")
def admin_prepare_taxonomy(payload:AdminTaxonomyPrepareRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        row=TaxonomyPreparationService(db).prepare(taxon_id=payload.taxon_id,region_id=payload.region_id,prepared_by=f"user:{current_user.id}"); db.commit(); db.refresh(row); return _taxonomy_preparation_payload(row)
    except Exception as exc: db.rollback(); raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/regions/{region_id}/taxonomy/prepare-bulk")
def admin_prepare_taxonomy_bulk(region_id:int,payload:AdminTaxonomyBulkPrepareRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return {"region_id":region_id,"dry_run":payload.dry_run,"results":RegionalTaxonomyBulkService(db).plan(region_id,[{**item.model_dump(),"limitations":tuple(item.limitations)} for item in payload.candidates],payload.dry_run,f"user:{current_user.id}")}
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/taxonomy/preparations/approve-batch")
def admin_approve_taxonomy_batch(payload:AdminTaxonomyBatchApprovalRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"results":RegionalTaxonomyBulkService(db).approve_batch(payload.preparation_ids,current_user.id,payload.approval_reference)}

@app.post("/admin/taxonomy/preparations/apply-batch")
def admin_apply_taxonomy_batch(payload:AdminTaxonomyBatchApplyRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return {"results":RegionalTaxonomyBulkService(db).apply_batch(payload.preparation_ids)}
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

def _local_candidate_payload(row):
    return {"id":row.id,"region_id":row.region_id,"submitted_scientific_name":row.submitted_scientific_name,"canonical_scientific_name":row.canonical_scientific_name,"authorship":row.authorship,"taxonomic_rank":row.taxonomic_rank,"authoritative_identifier_scheme":row.authoritative_identifier_scheme,"authoritative_identifier":row.authoritative_identifier,"accepted_name_status":row.accepted_name_status,"accepted_authoritative_identifier":row.accepted_authoritative_identifier,"parent_authoritative_identifier":row.parent_authoritative_identifier,"parent_name":row.parent_name,"provider":row.provider,"provider_version":row.provider_version,"provider_source_reference":row.provider_source_reference,"provider_artifact_sha256":row.provider_artifact_sha256,"provider_content_fingerprint":row.provider_content_fingerprint,"candidate_source":row.candidate_source,"reconciliation_result":row.reconciliation_result,"limitations":json.loads(row.limitations_json),"dependency_fingerprint":row.dependency_fingerprint,"workflow_status":row.workflow_status,"created_by":row.created_by,"created_at":row.created_at,"reviewed_at":row.reviewed_at,"approval_reference":row.approval_reference,"applied_at":row.applied_at,"resulting_species_id":row.resulting_species_id,"resulting_registry_entry_id":row.resulting_registry_entry_id}

@app.get("/admin/taxonomy/local-candidates/{candidate_id}")
def admin_local_candidate(candidate_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return _local_candidate_payload(_require_admin_record(db,LocalTaxonCandidate,candidate_id,"Local taxon candidate"))
@app.post("/admin/taxonomy/local-candidates/{candidate_id}/approve")
def admin_approve_local_candidate(candidate_id:int,payload:AdminTaxonomyApprovalRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,LocalTaxonCandidate,candidate_id,"Local taxon candidate")
    if payload.expected_preparation_fingerprint!=row.dependency_fingerprint:raise HTTPException(409,"Candidate fingerprint changed")
    try:LocalTaxonCandidateService(db).approve(row,current_user.id,payload.approval_reference);db.commit();db.refresh(row);return _local_candidate_payload(row)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))
@app.post("/admin/taxonomy/local-candidates/{candidate_id}/reject")
def admin_reject_local_candidate(candidate_id:int,payload:AdminTaxonomyApprovalRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,LocalTaxonCandidate,candidate_id,"Local taxon candidate");LocalTaxonCandidateService(db).reject(row,current_user.id,payload.approval_reference);db.commit();return _local_candidate_payload(row)
@app.post("/admin/taxonomy/local-candidates/{candidate_id}/apply")
def admin_apply_local_candidate(candidate_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,LocalTaxonCandidate,candidate_id,"Local taxon candidate")
    try:return LocalTaxonCandidateService(db).apply(row)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))
@app.post("/admin/taxonomy/local-candidate-batches/approve")
def admin_approve_local_candidates(payload:AdminLocalTaxonCandidateBatchRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"results":RegionalTaxonomyBulkService(db).approve_candidate_batch(payload.candidate_ids,current_user.id,payload.approval_reference or "admin-batch")}
@app.post("/admin/taxonomy/local-candidate-batches/apply")
def admin_apply_local_candidates(payload:AdminLocalTaxonCandidateBatchRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"results":RegionalTaxonomyBulkService(db).apply_candidate_batch(payload.candidate_ids)}

@app.post("/admin/taxonomy/manifests/preflight")
def admin_taxonomy_manifest_preflight(payload:AdminRegionalTaxonManifestRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).preflight(payload.model_dump())
    except Exception as exc:raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/scientific-corpus/manifests/parse")
def admin_parse_corpus_manifest(payload: AdminCorpusManifestParseRequest, current_user: User = Depends(require_platform_admin)):
    try: return parse_manifest_content(payload.content, payload.input_format)
    except (ValueError, json.JSONDecodeError) as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.get("/admin/scientific-corpus/contract")
def admin_scientific_corpus_contract(current_user: User = Depends(require_platform_admin)):
    return {"taxonomic_groups": list(TAXON_GROUPS), "storage": storage_contract(),
            "firewall": "REGIONAL TAXON GOVERNANCE != JURISDICTION PRESENCE OR ECOLOGICAL STATUS"}

@app.get("/admin/identification-corpus/media-sources")
def admin_identification_media_sources(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=MediaSourceGovernanceService(db);return {"items":[service.payload(row) for row in db.query(IdentificationMediaSource).order_by(IdentificationMediaSource.id).all()]}

@app.post("/admin/identification-corpus/media-sources")
def admin_create_identification_media_source(payload:AdminMediaSourceRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return MediaSourceGovernanceService(db).payload(MediaSourceGovernanceService(db).register(payload.model_dump(),current_user.id))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/identification-corpus/media-sources/{source_id}/transition")
def admin_transition_identification_media_source(source_id:int,payload:AdminMediaSourceTransitionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,IdentificationMediaSource,source_id,"Identification media source")
    try:return MediaSourceGovernanceService(db).payload(MediaSourceGovernanceService(db).transition(row,payload.target_state,current_user.id,payload.reference))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/regions/{region_id}/identification-corpus/coverage")
def admin_identification_corpus_coverage(region_id:int,page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=500),search:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return IdentificationCorpusService(db).coverage(region_id,page,page_size,search)

@app.post("/admin/identification-corpus/acquisition-runs")
def admin_prepare_media_acquisition(payload:AdminMediaAcquisitionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=AcquisitionRunService(db).prepare(payload.media_source_id,payload.taxon_id,payload.request,current_user.id);return {"id":row.id,"workflow_state":row.workflow_state,"run_fingerprint":row.run_fingerprint}

@app.get("/admin/identification-corpus/corpora/{corpus_id}/export-manifest")
def admin_identification_corpus_export(corpus_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not db.get(IdentificationCorpus,corpus_id):raise HTTPException(404,"Corpus not found")
    return IdentificationCorpusService(db).export_manifest(corpus_id)

def _identification_asset_payload(db,row):
    source=db.get(IdentificationMediaSource,row.media_source_id);taxon=db.get(Species,row.taxon_id)
    return {"id":row.id,"stable_asset_key":row.stable_asset_key,"taxon_id":row.taxon_id,"scientific_name":taxon.scientific_name if taxon else None,"source":{"id":source.id,"provider":source.scientific_provider} if source else None,"provider_asset_identifier":row.provider_asset_identifier,"source_reference":row.source_reference,"creator":row.creator,"license_expression":row.license_expression,"license_classification":row.license_classification,"attribution_text":row.attribution_text,"media_type":row.media_type,"width_px":row.width_px,"height_px":row.height_px,"size_bytes":row.size_bytes,"locality":row.locality,"event_date":row.event_date,"life_stage":row.life_stage,"biological_context":row.biological_context,"taxonomic_linkage":row.taxonomic_linkage,"quality_state":row.quality_state,"quality_metadata":json.loads(row.quality_metadata_json),"duplicate_state":row.duplicate_state,"exact_duplicate_of_id":row.exact_duplicate_of_id,"perceptual_hash":row.perceptual_hash,"perceptual_group":row.perceptual_group,"review_state":row.review_state,"exclusion_reason":row.exclusion_reason,"training_eligible":row.review_state=="APPROVED" and row.license_classification in {"TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"} and row.quality_state=="VALID" and row.duplicate_state in {"UNIQUE","DISTINCT"},"content_url":f"/admin/identification-corpus/assets/{row.id}/content" if row.artifact_reference_id else None}

@app.get("/admin/identification-corpus/acquisition-runs")
def admin_media_acquisition_runs(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    rows=db.query(IdentificationMediaAcquisitionRun).order_by(IdentificationMediaAcquisitionRun.id.desc()).all();return {"items":[{"id":r.id,"media_source_id":r.media_source_id,"taxon_id":r.taxon_id,"workflow_state":r.workflow_state,"retry_count":r.retry_count,"run_fingerprint":r.run_fingerprint,"request":json.loads(r.request_json),"manifest":json.loads(r.provider_manifest_json) if r.provider_manifest_json else None,"created_at":r.created_at,"completed_at":r.completed_at} for r in rows]}

@app.get("/admin/identification-corpus/assets")
def admin_media_assets(review_state:Optional[str]=None,taxon_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    query=db.query(IdentificationMediaAsset)
    if review_state:query=query.filter_by(review_state=review_state)
    if taxon_id:query=query.filter_by(taxon_id=taxon_id)
    return {"items":[_identification_asset_payload(db,r) for r in query.order_by(IdentificationMediaAsset.id).all()]}

@app.get("/admin/identification-corpus/assets/{asset_id}")
def admin_media_asset(asset_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return _identification_asset_payload(db,_require_admin_record(db,IdentificationMediaAsset,asset_id,"Identification media asset"))

@app.get("/admin/identification-corpus/assets/{asset_id}/content")
def admin_media_asset_content(asset_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,IdentificationMediaAsset,asset_id,"Identification media asset")
    if not row.artifact_reference_id:raise HTTPException(404,"Asset was not stored locally")
    artifact=_require_admin_record(db,ArtifactReference,row.artifact_reference_id,"Artifact")
    root=settings.artifact_directory.resolve();path=(root/artifact.local_path).resolve()
    if root not in path.parents or not path.is_file():raise HTTPException(404,"Controlled artifact unavailable")
    return FileResponse(path,media_type=artifact.media_type)

@app.get("/admin/identification-corpus/assets/{asset_id}/review-events")
def admin_media_review_events(asset_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    _require_admin_record(db,IdentificationMediaAsset,asset_id,"Identification media asset");rows=db.query(IdentificationMediaReviewEvent).filter_by(media_asset_id=asset_id).order_by(IdentificationMediaReviewEvent.created_at,IdentificationMediaReviewEvent.id).all();return {"items":[{"id":r.id,"action":r.action,"prior_review_state":r.prior_review_state,"current_review_state":r.current_review_state,"reason":r.reason,"license_state":r.license_state,"duplicate_state":r.duplicate_state,"quality_state":r.quality_state,"reviewer_user_id":r.reviewer_user_id,"created_at":r.created_at} for r in rows]}

@app.post("/admin/identification-corpus/assets/{asset_id}/review")
def admin_review_media_asset(asset_id:int,payload:AdminMediaReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,IdentificationMediaAsset,asset_id,"Identification media asset")
    try:return _identification_asset_payload(db,IdentificationCorpusService(db).review(row,payload.decision,current_user.id,payload.reference))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/identification-corpus/corpora")
def admin_identification_corpora(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=IdentificationCorpusService(db);return {"items":[service.corpus_payload(r) for r in db.query(IdentificationCorpus).order_by(IdentificationCorpus.id.desc()).all()]}

@app.post("/admin/identification-corpus/corpora")
def admin_create_identification_corpus(payload:AdminCorpusRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return IdentificationCorpusService(db).corpus_payload(IdentificationCorpusService(db).create_corpus(payload.model_dump(),current_user.id))

@app.post("/admin/identification-corpus/corpora/{corpus_id}/inclusions")
def admin_include_identification_assets(corpus_id:int,payload:AdminCorpusInclusionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return {"assignments":IdentificationCorpusService(db).include_assets(corpus_id,payload.asset_ids,current_user.id,payload.seed,payload.split_recommended)}
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/identification-corpus/corpora/{corpus_id}/transition")
def admin_transition_identification_corpus(corpus_id:int,payload:AdminCorpusTransitionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,IdentificationCorpus,corpus_id,"Identification corpus")
    try:return IdentificationCorpusService(db).corpus_payload(IdentificationCorpusService(db).transition_corpus(row,payload.target_state,current_user.id,payload.reference))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/identification-corpus/corpora/{corpus_id}/training-readiness")
def admin_identification_training_readiness(corpus_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return IdentificationCorpusService(db).training_readiness(corpus_id)

@app.post("/admin/identification-corpus/benchmarks")
def admin_prepare_identification_benchmark(payload:AdminBenchmarkRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        row=IdentificationBenchmarkService(db).prepare(payload.model_dump(),current_user.id);return {"id":row.id,"workflow_state":row.workflow_state,"run_fingerprint":row.run_fingerprint}
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/occurrence-acquisition-batches")
def admin_prepare_occurrence_batch(payload:AdminOccurrenceBatchRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        row=OccurrenceBatchService(db).prepare(payload.region_id,payload.batch_key,payload.items,current_user.id,payload.configuration);return OccurrenceBatchService(db).summary(row.id)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/occurrence-acquisition-batches/{batch_id}")
def admin_occurrence_batch(batch_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    _require_admin_record(db,OccurrenceAcquisitionBatch,batch_id,"Occurrence acquisition batch");return OccurrenceBatchService(db).summary(batch_id)

@app.post("/admin/taxonomy/manifests")
def admin_prepare_taxonomy_manifest(payload:AdminRegionalTaxonManifestRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).prepare(payload.model_dump(),current_user.id)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/taxonomy/manifests/{run_id}")
def admin_taxonomy_manifest_detail(run_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).detail(run_id)
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.get("/admin/taxonomy/manifests/{run_id}/items/{item_id}")
def admin_taxonomy_manifest_item(run_id:int,item_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).item_payload(RegionalTaxonManifestService(db)._items(run_id,[item_id])[0])
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.post("/admin/taxonomy/manifests/{run_id}/approve")
def admin_approve_taxonomy_manifest(run_id:int,payload:AdminManifestSelectionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not payload.approval_reference:raise HTTPException(status_code=422,detail="approval_reference is required")
    try:return RegionalTaxonManifestService(db).approve(run_id,payload.item_ids,current_user.id,payload.approval_reference)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/taxonomy/manifests/{run_id}/items/{item_id}/reject")
def admin_reject_taxonomy_manifest_item(run_id:int,item_id:int,payload:AdminManifestSelectionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not payload.approval_reference:raise HTTPException(status_code=422,detail="approval_reference is required")
    try:return RegionalTaxonManifestService(db).reject(run_id,item_id,current_user.id,payload.approval_reference)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/taxonomy/manifests/{run_id}/apply")
def admin_apply_taxonomy_manifest(run_id:int,payload:AdminManifestSelectionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).apply(run_id,payload.item_ids)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/taxonomy/manifests/{run_id}/retry")
def admin_retry_taxonomy_manifest(run_id:int,payload:AdminManifestSelectionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return RegionalTaxonManifestService(db).apply(run_id,payload.item_ids,retry=True)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/occurrence-sources")
def admin_occurrence_sources(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=OccurrenceSourceGovernanceService(db);rows=db.query(OccurrenceSourceRegistration).order_by(OccurrenceSourceRegistration.id).all();return {"sources":[service.payload(row) for row in rows],"note":"Scientific provider identity is distinct from transport or aggregator identity."}

@app.post("/admin/occurrence-sources")
def admin_register_occurrence_source(payload:AdminOccurrenceSourceRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceSourceGovernanceService(db).payload(OccurrenceSourceGovernanceService(db).register(payload.model_dump(),current_user.id))
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/occurrence-sources/{source_id}")
def admin_occurrence_source(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,OccurrenceSourceRegistration,source_id,"Occurrence source");return OccurrenceSourceGovernanceService(db).payload(row)

@app.post("/admin/occurrence-sources/{source_id}/approve")
def admin_approve_occurrence_source(source_id:int,payload:AdminOccurrenceSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceSourceGovernanceService(db).payload(OccurrenceSourceGovernanceService(db).approve(_require_admin_record(db,OccurrenceSourceRegistration,source_id,"Occurrence source"),current_user.id,payload.approval_reference))
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-sources/{source_id}/reject")
def admin_reject_occurrence_source(source_id:int,payload:AdminOccurrenceSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceSourceGovernanceService(db).payload(OccurrenceSourceGovernanceService(db).reject(_require_admin_record(db,OccurrenceSourceRegistration,source_id,"Occurrence source"),current_user.id,payload.approval_reference))
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-sources/{source_id}/activate")
def admin_activate_occurrence_source(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceSourceGovernanceService(db).payload(OccurrenceSourceGovernanceService(db).activate(_require_admin_record(db,OccurrenceSourceRegistration,source_id,"Occurrence source")))
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-sources/{source_id}/deactivate")
def admin_deactivate_occurrence_source(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceSourceGovernanceService(db).payload(OccurrenceSourceGovernanceService(db).deactivate(_require_admin_record(db,OccurrenceSourceRegistration,source_id,"Occurrence source")))
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/occurrence-evidence/readiness")
def admin_occurrence_readiness(jurisdiction_id:int,taxon_id:int,source_key:str,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"jurisdiction_id":jurisdiction_id,"taxon_id":taxon_id,"source_key":source_key,"status":OccurrenceEvidenceService(db).readiness(jurisdiction_id,taxon_id,source_key)}

@app.get("/admin/regions/{region_id}/occurrence-readiness")
def admin_regional_occurrence_readiness(region_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    region=_require_admin_record(db,Region,region_id,"Region")
    jurisdictions=db.query(Jurisdiction).filter_by(region_id=region.id).order_by(Jurisdiction.name).all()
    taxa=db.query(RegionalTaxonRegistry).filter_by(region_id=region.id,review_status="APPROVED").order_by(RegionalTaxonRegistry.id).all()
    sources=db.query(OccurrenceSourceRegistration).filter_by(workflow_status="ACTIVE").order_by(OccurrenceSourceRegistration.id).all()
    service=OccurrenceEvidenceService(db)
    rows=[{"jurisdiction":{"id":jurisdiction.id,"name":jurisdiction.name},"taxon":{"id":entry.taxon.id,"scientific_name":entry.taxon.scientific_name},"source":{"id":source.id,"source_registration_id":source.source_registration_id,"source_name":source.source_name},"status":service.readiness(jurisdiction.id,entry.taxon.id,source.source_registration_id)} for jurisdiction in jurisdictions for entry in taxa for source in sources]
    return {"region":{"id":region.id,"name":region.name,"slug":region.slug},"count":len(rows),"evaluations":rows,"semantics":"Read-only categorical readiness; no occurrence or ecological state is created."}

@app.post("/admin/occurrence-evidence/preparations")
def admin_prepare_occurrence(payload:AdminOccurrencePreparationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).prepare(payload.jurisdiction_id,payload.taxon_id,payload.source_key,current_user.id,payload.dry_run)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/occurrence-evidence/preparations/{preparation_id}")
def admin_occurrence_preparation(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).detail(preparation_id)
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/initialize-review")
def admin_initialize_occurrence_review(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceCandidateReviewService(db).initialize(preparation_id,current_user.id)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/occurrence-evidence/preparations/{preparation_id}/review-report")
def admin_occurrence_review_report(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceCandidateReviewService(db).report(preparation_id)
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.get("/admin/occurrence-evidence/preparations/{preparation_id}/candidates/{candidate_id}")
def admin_occurrence_candidate(preparation_id:int,candidate_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).candidate_payload(OccurrenceEvidenceService(db)._candidates(preparation_id,[candidate_id])[0])
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.get("/admin/occurrence-evidence/preparations/{preparation_id}/legacy-reconciliation")
def admin_occurrence_legacy_reconciliation(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).legacy_reconciliation(preparation_id)
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/approve")
def admin_approve_occurrence(preparation_id:int,payload:AdminOccurrenceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not payload.review_reference:raise HTTPException(status_code=422,detail="review_reference is required")
    try:return OccurrenceEvidenceService(db).approve(preparation_id,payload.candidate_ids,current_user.id,payload.review_reference)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/reject")
def admin_reject_occurrence(preparation_id:int,payload:AdminOccurrenceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not payload.review_reference:raise HTTPException(status_code=422,detail="review_reference is required")
    try:return OccurrenceEvidenceService(db).reject(preparation_id,payload.candidate_ids,current_user.id,payload.review_reference,payload.disposition or "UNRESOLVED",payload.evidence_note)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/dispositions")
def admin_dispose_occurrence(preparation_id:int,payload:AdminOccurrenceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    if not payload.review_reference or not payload.disposition:raise HTTPException(status_code=422,detail="review_reference and disposition are required")
    try:return OccurrenceCandidateReviewService(db).review(preparation_id,payload.candidate_ids,payload.disposition,current_user.id,payload.review_reference,payload.evidence_note)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/apply")
def admin_apply_occurrence(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).apply(preparation_id)
    except Exception as exc:
        db.rollback();row=db.get(OccurrenceAcquisitionPreparation,preparation_id)
        if row and row.workflow_status!="STALE":row.workflow_status="FAILED";row.last_error=str(exc);db.commit()
        raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/occurrence-evidence/preparations/{preparation_id}/retry")
def admin_retry_occurrence(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return OccurrenceEvidenceService(db).retry(preparation_id)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/ecological-status/preparations")
def admin_prepare_ecological_status(payload:AdminEcologicalStatusPreparationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusGovernanceService(db).prepare(payload.model_dump(exclude={"dry_run"}),current_user.id,payload.dry_run)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/ecological-status/preflight")
def admin_preflight_ecological_status(payload:AdminEcologicalStatusPreparationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return EcologicalStatusGovernanceService(db).preflight(payload.model_dump(exclude={"dry_run"}))

@app.get("/admin/ecological-status/preparations/{preparation_id}")
def admin_ecological_status_preparation(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusGovernanceService(db).detail(preparation_id)
    except Exception as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.post("/admin/ecological-status/preparations/{preparation_id}/review")
def admin_review_ecological_status(preparation_id:int,payload:AdminEcologicalStatusReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=EcologicalStatusGovernanceService(db)
    try:return service.approve(preparation_id,payload.candidate_ids,current_user.id,payload.review_reference) if payload.disposition=="APPROVED" else service.dispose(preparation_id,payload.candidate_ids,payload.disposition,current_user.id,payload.review_reference)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/ecological-status/preparations/{preparation_id}/apply")
def admin_apply_ecological_status(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusGovernanceService(db).apply(preparation_id)
    except Exception as exc:db.rollback();raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/jurisdictions/{jurisdiction_id}/taxa/{taxon_id}/ecological-status")
def admin_ecological_status_projection(jurisdiction_id:int,taxon_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=EcologicalStatusGovernanceService(db);return {"projection":service.projection(jurisdiction_id,taxon_id),"history":service.history(jurisdiction_id,taxon_id),"semantics":"Approved jurisdiction assertions only; occurrence evidence and regional membership do not create status."}

@app.get("/admin/jurisdictions/{jurisdiction_id}/ecological-status/assertions")
def admin_ecological_status_assertions(jurisdiction_id:int,taxon_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=EcologicalStatusGovernanceService(db)
    if taxon_id:return {"assertions":service.history(jurisdiction_id,taxon_id)}
    rows=db.query(EcologicalStatusAssertion).filter_by(jurisdiction_id=jurisdiction_id).order_by(EcologicalStatusAssertion.id).all();return {"assertions":[service._assertion_payload(row) for row in rows]}

@app.get("/admin/ecological-status/sources")
def admin_ecological_sources(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=EcologicalStatusSourceGovernanceService(db);return {"sources":[service.payload(row) for row in db.query(EcologicalStatusSourceRegistration).order_by(EcologicalStatusSourceRegistration.id).all()]}

@app.post("/admin/ecological-status/sources")
def admin_register_ecological_source(payload:AdminEcologicalSourceRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        service=EcologicalStatusSourceGovernanceService(db);return service.payload(service.register(payload.model_dump(),current_user.id))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/ecological-status/sources/{source_id}")
def admin_ecological_source_detail(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,EcologicalStatusSourceRegistration,source_id,"Ecological-status source");service=EcologicalStatusSourceGovernanceService(db);return {**service.payload(row),"version_history":[service.payload(item) for item in db.query(EcologicalStatusSourceRegistration).filter_by(source_registration_id=row.source_registration_id).order_by(EcologicalStatusSourceRegistration.id).all()]}

@app.post("/admin/ecological-status/sources/{source_id}/approve")
def admin_approve_ecological_source(source_id:int,payload:AdminEcologicalSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        service=EcologicalStatusSourceGovernanceService(db);return service.payload(service.approve(_require_admin_record(db,EcologicalStatusSourceRegistration,source_id,"Ecological-status source"),current_user.id,payload.review_reference))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/sources/{source_id}/reject")
def admin_reject_ecological_source(source_id:int,payload:AdminEcologicalSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        service=EcologicalStatusSourceGovernanceService(db);return service.payload(service.reject(_require_admin_record(db,EcologicalStatusSourceRegistration,source_id,"Ecological-status source"),current_user.id,payload.review_reference))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/sources/{source_id}/activate")
def admin_activate_ecological_source(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        service=EcologicalStatusSourceGovernanceService(db);return service.payload(service.activate(_require_admin_record(db,EcologicalStatusSourceRegistration,source_id,"Ecological-status source")))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/sources/{source_id}/deactivate")
def admin_deactivate_ecological_source(source_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        service=EcologicalStatusSourceGovernanceService(db);return service.payload(service.deactivate(_require_admin_record(db,EcologicalStatusSourceRegistration,source_id,"Ecological-status source")))
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/ingestion/preflight")
async def admin_preflight_ecological_ingestion(source_id:int=Form(...),jurisdiction_id:int=Form(...),mapping_json:str=Form("{}"),artifact:UploadFile=File(...),db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).preflight(source_id,jurisdiction_id,await artifact.read(),artifact.filename or "artifact",artifact.content_type or "",json.loads(mapping_json) or None)
    except Exception as exc:raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/ingestion-runs")
async def admin_create_ecological_ingestion(source_id:int=Form(...),jurisdiction_id:int=Form(...),mapping_json:str=Form("{}"),artifact:UploadFile=File(...),db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).create_run(source_id,jurisdiction_id,await artifact.read(),artifact.filename or "artifact",artifact.content_type or "",current_user.id,json.loads(mapping_json) or None)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/ecological-status/ingestion-runs")
def admin_ecological_ingestion_runs(source_id:Optional[int]=None,jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    query=db.query(EcologicalStatusIngestionRun)
    if source_id is not None:query=query.filter_by(source_registration_id=source_id)
    if jurisdiction_id is not None:query=query.filter_by(jurisdiction_id=jurisdiction_id)
    service=EcologicalStatusIngestionService(db)
    return {"runs":[service.detail(row.id,include_rows=False) for row in query.order_by(EcologicalStatusIngestionRun.id.desc()).all()]}

@app.get("/admin/ecological-status/ingestion-runs/{run_id}")
def admin_ecological_ingestion_detail(run_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).detail(run_id)
    except Exception as exc:raise HTTPException(404,str(exc))

@app.get("/admin/ecological-status/ingestion-runs/{run_id}/rows/{row_id}")
def admin_ecological_ingestion_row(run_id:int,row_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).row_payload(EcologicalStatusIngestionService(db)._rows(run_id,[row_id])[0])
    except Exception as exc:raise HTTPException(404,str(exc))

@app.post("/admin/ecological-status/ingestion-runs/{run_id}/review")
def admin_review_ecological_ingestion(run_id:int,payload:AdminEcologicalIngestionReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).review(run_id,payload.row_ids,payload.disposition,current_user.id,payload.review_reference)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/ingestion-runs/{run_id}/apply")
def admin_apply_ecological_ingestion(run_id:int,payload:AdminEcologicalIngestionReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).apply(run_id,payload.row_ids)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/ecological-status/ingestion-runs/{run_id}/retry")
def admin_retry_ecological_ingestion(run_id:int,payload:AdminEcologicalIngestionReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return EcologicalStatusIngestionService(db).retry(run_id,payload.row_ids)
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/admin/ecological-status/ingestion-runs/{run_id}/conflicts")
def admin_ecological_ingestion_conflicts(run_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    service=EcologicalStatusIngestionService(db);return {"rows":[service.row_payload(row) for row in service._rows(run_id) if row.conflict_state!="NONE"]}

def _paginate_public(items,page,page_size):
    page=max(1,page);page_size=max(1,min(100,page_size));start=(page-1)*page_size;return {"page":page,"page_size":page_size,"total":len(items),"items":items[start:start+page_size]}

@app.get("/jurisdictions/{jurisdiction_id}/marine-species")
def public_jurisdiction_marine_species(jurisdiction_id:int,page:int=Query(1),page_size:int=Query(25),search:Optional[str]=None,db:Session=Depends(get_db)):
    _require_admin_record(db,Jurisdiction,jurisdiction_id,"Jurisdiction");items=EcologicalStatusReadService(db).marine_species(jurisdiction_id)
    if search:items=[item for item in items if search.casefold() in f"{item.get('scientific_name') or ''} {item.get('common_name') or ''}".casefold()]
    return _paginate_public(items,page,page_size)

@app.get("/regions/{region_id}/governed-marine-taxa")
def public_regional_governed_taxa(region_id:int,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100),db:Session=Depends(get_db)):
    try:return RegionalScientificScalingService(db).regional_taxa(region_id,page=page,page_size=page_size)
    except ValueError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@app.get("/regions/{region_id}/governed-marine-taxa/{taxon_id}/jurisdictions")
def public_taxon_jurisdiction_comparison(region_id:int,taxon_id:int,db:Session=Depends(get_db)):
    try:return RegionalScientificScalingService(db).taxon_comparison(region_id,taxon_id)
    except ValueError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@app.get("/jurisdictions/{jurisdiction_id}/invasive-species")
def public_jurisdiction_invasive_species(jurisdiction_id:int,page:int=Query(1),page_size:int=Query(25),search:Optional[str]=None,db:Session=Depends(get_db)):
    _require_admin_record(db,Jurisdiction,jurisdiction_id,"Jurisdiction");items=EcologicalStatusReadService(db).invasive_species(jurisdiction_id)
    if search:items=[item for item in items if search.casefold() in f"{item.get('scientific_name') or ''} {item.get('common_name') or ''}".casefold()]
    return _paginate_public(items,page,page_size)

@app.get("/jurisdictions/{jurisdiction_id}/species/{taxon_id}")
def public_jurisdiction_species(jurisdiction_id:int,taxon_id:int,db:Session=Depends(get_db)):
    _require_admin_record(db,Jurisdiction,jurisdiction_id,"Jurisdiction");_require_admin_record(db,Species,taxon_id,"Taxon");return EcologicalStatusReadService(db).species(jurisdiction_id,taxon_id)

@app.get("/jurisdictions/{jurisdiction_id}/species/{taxon_id}/map")
def public_jurisdiction_species_map(jurisdiction_id:int,taxon_id:int,db:Session=Depends(get_db)):
    jurisdiction=_require_admin_record(db,Jurisdiction,jurisdiction_id,"Jurisdiction");_require_admin_record(db,Species,taxon_id,"Taxon");detail=EcologicalStatusReadService(db).species(jurisdiction_id,taxon_id);boundary=db.query(JurisdictionBoundary).filter_by(jurisdiction_id=jurisdiction_id,boundary_type="MARINE_MONITORING",status="ACTIVE").order_by(JurisdictionBoundary.id.desc()).first()
    return {"jurisdiction":{"id":jurisdiction.id,"name":jurisdiction.name,"slug":jurisdiction.slug,"region_slug":jurisdiction.region.slug,"center_latitude":jurisdiction.center_latitude,"center_longitude":jurisdiction.center_longitude,"default_zoom":jurisdiction.default_zoom},"taxon_id":taxon_id,"boundary":{"type":"Feature","geometry":json.loads(boundary.geometry_json),"properties":{"label":"Marine monitoring boundary","source":boundary.source,"source_reference":boundary.source_reference,"notice":"Operational monitoring boundary; not an independent legal determination."}} if boundary else None,"occurrence_points":detail["occurrence_points"],"verified_observations":detail["verified_observations"],"suitability":detail["suitability"],"excluded_evidence":"Candidate, rejected, duplicate, and legacy-unverified records are excluded."}

@app.get("/jurisdictions/{jurisdiction_id}/species/{taxon_id}/suitability-grid")
def public_species_suitability_grid(jurisdiction_id:int,taxon_id:int,db:Session=Depends(get_db)):
    program=db.query(SpeciesProgram).filter_by(jurisdiction_id=jurisdiction_id,species_id=taxon_id,status="ACTIVE").one_or_none()
    if not program:return {"available":False,"cells":[],"disclaimer":"Environmental suitability does not confirm species presence."}
    deployment=db.query(SuitabilityDeployment).filter_by(species_program_id=program.id,status="ACTIVE").order_by(SuitabilityDeployment.id.desc()).first()
    if not deployment or deployment.public_display_status!="PUBLIC_APPROVED":return {"available":False,"authorization_state":"NOT_PUBLICLY_APPROVED","cells":[],"disclaimer":"Environmental suitability is not authorized for public display."}
    cells=db.query(HabitatSuitabilityV3GridCell).filter_by(suitability_deployment_id=deployment.id,prediction_status="SCORED").all()
    return {"available":bool(cells),"model_version":deployment.model_version,"cells":[{"latitude":row.latitude,"longitude":row.longitude,"grid_size":row.grid_size,"suitability_score":row.suitability_score,"suitability_band":row.suitability_band} for row in cells],"disclaimer":"Environmental suitability model — this does not confirm species presence or absence."}

@app.get("/admin/suitability-deployments/{deployment_id}/public-display")
def admin_suitability_display(deployment_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,SuitabilityDeployment,deployment_id,"Suitability deployment");return {"deployment_id":row.id,"model_version":row.model_version,"scientific_status":row.status,"public_display_status":row.public_display_status,"approval_reference":row.public_display_approval_reference,"approved_at":row.public_display_approved_at,"revoked_at":row.public_display_revoked_at,"limitations":json.loads(row.public_display_limitations_json)}

@app.post("/admin/suitability-deployments/{deployment_id}/public-display/approve")
def admin_approve_suitability_display(deployment_id:int,payload:AdminEcologicalSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,SuitabilityDeployment,deployment_id,"Suitability deployment");row.public_display_status="PUBLIC_APPROVED";row.public_display_approval_reference=payload.review_reference;row.public_display_approved_by_user_id=current_user.id;row.public_display_approved_at=datetime.now(timezone.utc);row.public_display_revoked_at=None;db.commit();return admin_suitability_display(deployment_id,db,current_user)

@app.post("/admin/suitability-deployments/{deployment_id}/public-display/revoke")
def admin_revoke_suitability_display(deployment_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,SuitabilityDeployment,deployment_id,"Suitability deployment");row.public_display_status="REVOKED";row.public_display_revoked_at=datetime.now(timezone.utc);db.commit();return admin_suitability_display(deployment_id,db,current_user)

@app.post("/admin/suitability-deployments/{deployment_id}/activate")
def admin_activate_scientific_deployment(deployment_id:int,payload:AdminEcologicalSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row,changed=SuitabilityDeploymentGovernance(db).activate(deployment_id,payload.review_reference);db.commit();return {"deployment_id":row.id,"status":row.status,"changed":changed,"scientific_event_emitted":changed}
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.post("/admin/suitability-deployments/{deployment_id}/deactivate")
def admin_deactivate_scientific_deployment(deployment_id:int,payload:AdminEcologicalSourceReviewRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row,changed=SuitabilityDeploymentGovernance(db).deactivate(deployment_id,payload.review_reference);db.commit();return {"deployment_id":row.id,"status":row.status,"changed":changed,"scientific_event_emitted":changed}
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.get("/species/{taxon_id}/public-media")
def public_taxon_media(taxon_id:int,db:Session=Depends(get_db)):
    service=PublicMediaService(db);items=[service.safe(row) for row in service.public_for_taxon(taxon_id)];return {"primary_image":next((item for item in items if item["is_primary"]),None),"gallery":items}

@app.get("/admin/observations/queue")
def admin_observation_queue(jurisdiction_id:Optional[int]=None,workflow_state:Optional[str]=None,priority:Optional[str]=None,assigned_reviewer_id:Optional[int]=None,identity_state:Optional[str]=None,duplicate_state:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    allowed=reviewer_jurisdiction_ids(db,current_user)
    if jurisdiction_id is not None:require_review_jurisdiction(db,current_user,jurisdiction_id)
    observations=db.query(Observation).order_by(Observation.created_at.desc()).all();service=ObservationOperationsService(db);items=[]
    for observation in observations:
        if not current_user.is_platform_admin and observation.jurisdiction_id not in allowed:continue
        if jurisdiction_id is not None and observation.jurisdiction_id!=jurisdiction_id:continue
        case=db.query(ObservationOperationalCase).filter_by(observation_id=observation.id).one_or_none();item=service.payload(observation,case)
        if workflow_state and item["workflow_state"]!=workflow_state:continue
        if priority and item["operational_priority"]!=priority:continue
        if assigned_reviewer_id is not None and item["assigned_reviewer_user_id"]!=assigned_reviewer_id:continue
        if identity_state and item["resolved_identity"]["state"]!=identity_state:continue
        if duplicate_state and item["duplicate"]["disposition"]!=duplicate_state:continue
        items.append(item)
    return {"count":len(items),"items":items,"semantics":"Operational queue priority and routing are not ecological severity or anomaly confidence."}

@app.get("/admin/observations/metrics")
def admin_observation_metrics(jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    result=admin_observation_queue(jurisdiction_id,None,None,None,None,None,db,current_user)["items"];return {"total":len(result),"pending_review":sum(i["workflow_state"] not in {"CLOSED","VERIFIED","CORRECTED","REJECTED","DUPLICATE"} for i in result),"verified":sum(i["workflow_state"] in {"VERIFIED","CORRECTED"} for i in result),"unresolved":sum(i["resolved_identity"]["state"]=="UNRESOLVED" for i in result),"duplicate":sum(i["duplicate"]["disposition"]=="CONFIRMED_DUPLICATE" for i in result)}

@app.get("/admin/observations/{observation_id}/operations")
def admin_observation_operations(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,case=service.case(observation_id,create=False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);responses=db.query(ReporterAdditionalInformation).filter_by(observation_id=observation_id).order_by(ReporterAdditionalInformation.created_at).all();return {"case":service.payload(observation,case),"audit_history":service.history(observation_id),"reporter_responses":[{"response_text":r.response_text,"has_additional_image":bool(r.image_filename),"created_at":r.created_at} for r in responses]}

@app.get("/admin/observations/{observation_id}/image")
def protected_observation_image(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    observation=_require_admin_record(db,Observation,observation_id,"Observation");require_review_jurisdiction(db,current_user,observation.jurisdiction_id);path=UPLOAD_DIRECTORY/observation.image_filename
    if not path.is_file():raise HTTPException(404,"Observation image not found")
    return FileResponse(path)

@app.post("/admin/observations/{observation_id}/triage")
def admin_triage_observation(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);return service.triage(observation_id,current_user.id)

@app.post("/admin/observations/{observation_id}/assign")
def admin_assign_observation(observation_id:int,payload:ObservationOperationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id)
    return service.assign(observation_id,payload.reviewer_user_id,current_user.id,payload.reason,payload.expected_reviewer_user_id)

@app.post("/admin/observations/{observation_id}/claim")
def claim_observation(observation_id:int,payload:ObservationOperationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id)
    try:return service.claim(observation_id,current_user.id,payload.reason)
    except ValueError as exc:raise HTTPException(409,str(exc))

@app.post("/admin/observations/{observation_id}/priority")
def admin_priority_observation(observation_id:int,payload:ObservationOperationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);return service.priority(observation_id,payload.priority,current_user.id,payload.reason)

@app.post("/admin/observations/{observation_id}/disposition")
def admin_disposition_observation(observation_id:int,payload:ObservationOperationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);return service.disposition(observation_id,payload.disposition,current_user.id,payload.species,payload.reason)

@app.post("/admin/observations/{observation_id}/close")
def admin_close_observation(observation_id:int,payload:ObservationOperationRequest,reopen:bool=False,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);return service.close(observation_id,current_user.id,payload.reason,reopen)

@app.post("/admin/observations/{observation_id}/request-information")
def request_observation_information(observation_id:int,payload:ObservationOperationRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,_=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id);result=service.request_information(observation_id,current_user.id,payload.reason);raw=result.pop("reporter_response_token");result["reporter_response_url"]=f"/reporter/status/{raw}";return result

@app.post("/admin/observations/{observation_id}/manual-reporter-link")
def rotate_manual_reporter_link(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    service=ObservationOperationsService(db);observation,case=service.case(observation_id,False);require_review_jurisdiction(db,current_user,observation.jurisdiction_id)
    if not case or case.workflow_state!="AWAITING_REPORTER_INFORMATION":raise HTTPException(409,"The case is not awaiting reporter information.")
    now=datetime.now(timezone.utc)
    for token in db.query(ReporterAccessToken).filter_by(observation_id=observation_id,purpose="RESPONSE").filter(ReporterAccessToken.revoked_at.is_(None)).all():token.revoked_at=now
    token,raw=ReporterAccessService(db).issue(observation_id,"RESPONSE",case.id);db.add(ObservationOperationalEvent(case_id=case.id,observation_id=observation_id,actor_user_id=current_user.id,event_type="REPORTER_LINK_ROTATED",previous_state=case.workflow_state,current_state=case.workflow_state,reason_reference="Private reporter link prepared for manual delivery",identity_state_json="{}",provenance_version="observation-operations-v1"));db.commit();return {"public_reference":token.public_reference,"reporter_response_url":f"/reporter/status/{raw}","message":"Additional information was requested for this marine sighting. Use the private link to respond. Do not forward it to anyone else.","delivery_state":"MANUAL_DELIVERY_REQUIRED"}

@app.get("/admin/observation-reviewers")
def list_observation_reviewers(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    rows=db.query(ObservationReviewerGrant).order_by(ObservationReviewerGrant.user_id,ObservationReviewerGrant.jurisdiction_id).all();return {"items":[{"id":r.id,"user_id":r.user_id,"user_name":db.get(User,r.user_id).display_name,"jurisdiction_id":r.jurisdiction_id,"jurisdiction_name":db.get(Jurisdiction,r.jurisdiction_id).name,"role":r.role,"status":r.status,"grant_reference":r.grant_reference,"granted_at":r.granted_at,"revoked_at":r.revoked_at} for r in rows]}

@app.get("/admin/observation-reviewers/eligible")
def eligible_observation_reviewers(jurisdiction_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    require_review_jurisdiction(db,current_user,jurisdiction_id);rows=db.query(ObservationReviewerGrant).join(User,User.id==ObservationReviewerGrant.user_id).filter(ObservationReviewerGrant.jurisdiction_id==jurisdiction_id,ObservationReviewerGrant.status=="ACTIVE",User.status=="ACTIVE").all();return {"items":[{"user_id":r.user_id,"display_name":db.get(User,r.user_id).display_name,"role":r.role} for r in rows]}

@app.post("/admin/observation-reviewers/grants")
def grant_observation_reviewer(payload:ReviewerGrantRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    _require_admin_record(db,User,payload.user_id,"User");_require_admin_record(db,Jurisdiction,payload.jurisdiction_id,"Jurisdiction");row=db.query(ObservationReviewerGrant).filter_by(user_id=payload.user_id,jurisdiction_id=payload.jurisdiction_id).one_or_none()
    if row:row.status="ACTIVE";row.granted_by_user_id=current_user.id;row.grant_reference=payload.grant_reference;row.granted_at=datetime.now(timezone.utc);row.revoked_by_user_id=None;row.revoked_at=None
    else:row=ObservationReviewerGrant(user_id=payload.user_id,jurisdiction_id=payload.jurisdiction_id,role="JURISDICTION_REVIEWER",status="ACTIVE",granted_by_user_id=current_user.id,grant_reference=payload.grant_reference);db.add(row)
    db.commit();return {"id":row.id,"status":row.status}

@app.post("/admin/observation-reviewers/grants/{grant_id}/revoke")
def revoke_observation_reviewer(grant_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,ObservationReviewerGrant,grant_id,"Reviewer grant");row.status="REVOKED";row.revoked_by_user_id=current_user.id;row.revoked_at=datetime.now(timezone.utc);db.commit();return {"id":row.id,"status":row.status}

@app.get("/reviewer/home")
def reviewer_home(db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    items=admin_observation_queue(None,None,None,None,None,None,db,current_user)["items"];open_items=[i for i in items if i["workflow_state"] not in {"CLOSED","VERIFIED","CORRECTED","REJECTED","DUPLICATE"}];jurisdictions=reviewer_jurisdiction_ids(db,current_user);return {"jurisdictions":[{"id":j.id,"name":j.name,"slug":j.slug,"region":j.region.slug} for j in db.query(Jurisdiction).filter(Jurisdiction.id.in_(jurisdictions)).all()],"metrics":{"awaiting_review":len(open_items),"unassigned":sum(not i["assigned_reviewer_user_id"] for i in open_items),"my_cases":sum(i["assigned_reviewer_user_id"]==current_user.id for i in open_items),"verified_corrected":sum(i["workflow_state"] in {"VERIFIED","CORRECTED"} for i in items),"unresolved":sum(i["resolved_identity"]["state"]=="UNRESOLVED" for i in items),"confirmed_duplicates":sum(i["duplicate"]["disposition"]=="CONFIRMED_DUPLICATE" for i in items),"oldest_open_submitted_at":min((i["submitted_at"] for i in open_items),default=None)},"orientation":{"does":["Receives and organizes jurisdiction marine sightings","Assists identification and supports expert review","Preserves evidence and operational audit history"],"does_not":["AI suggestions are not expert verification","Occurrence does not equal invasive status","Suitability does not confirm presence","Operational priority is not ecological severity","Verification does not automatically create governed evidence","Unusual reports are not automatically anomalies"]}}

@app.post("/pilot/feedback")
def submit_pilot_feedback(payload:PilotFeedbackRequest,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    categories={"OPERATIONAL_FIT","MISSING_FEATURE","CONFUSING","BUG","USEFUL","GENERAL"};require_review_jurisdiction(db,current_user,payload.jurisdiction_id)
    if payload.category not in categories or not payload.feedback_text.strip():raise HTTPException(422,"Valid category and feedback text are required")
    row=PilotFeedback(category=payload.category,feedback_text=payload.feedback_text.strip(),page_context=payload.page_context,jurisdiction_id=payload.jurisdiction_id,user_id=current_user.id);db.add(row);db.commit();return {"id":row.id,"submitted":True}

@app.get("/admin/pilot/feedback")
def admin_pilot_feedback(category:Optional[str]=None,jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    query=db.query(PilotFeedback)
    if category:query=query.filter_by(category=category)
    if jurisdiction_id:query=query.filter_by(jurisdiction_id=jurisdiction_id)
    return {"items":[{"id":r.id,"category":r.category,"feedback_text":r.feedback_text,"page_context":r.page_context,"jurisdiction_id":r.jurisdiction_id,"user_id":r.user_id,"state":r.state,"admin_disposition":r.admin_disposition,"created_at":r.created_at,"reviewed_at":r.reviewed_at} for r in query.order_by(PilotFeedback.created_at.desc()).all()]}

@app.patch("/admin/pilot/feedback/{feedback_id}")
def admin_update_pilot_feedback(feedback_id:int,payload:PilotFeedbackUpdateRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,PilotFeedback,feedback_id,"Pilot feedback");state=payload.state.upper()
    if state not in {"OPEN","REVIEWED","CLOSED"}:raise HTTPException(400,"Feedback state must be OPEN, REVIEWED, or CLOSED.")
    row.state=state;row.admin_disposition=payload.admin_disposition.strip() if payload.admin_disposition else None;row.reviewed_by_user_id=current_user.id;row.reviewed_at=datetime.now(timezone.utc);audit(db,"PILOT_FEEDBACK_UPDATED",current_user.id,"PilotFeedback",row.id,row.jurisdiction_id,{"state":state});db.commit();return {"id":row.id,"state":row.state,"admin_disposition":row.admin_disposition}

@app.get("/admin/pilot/activity")
def admin_pilot_activity(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    grants=db.query(ObservationReviewerGrant).filter_by(status="ACTIVE").all();return {"active_pilot_reviewers":len({r.user_id for r in grants}),"jurisdictions_represented":len({r.jurisdiction_id for r in grants}),"cases_reviewed":db.query(ObservationOperationalEvent).filter(ObservationOperationalEvent.event_type=="EXPERT_DISPOSITION").count(),"cases_closed":db.query(ObservationOperationalCase).filter_by(workflow_state="CLOSED").count(),"feedback_entries":db.query(PilotFeedback).count(),"last_reviewer_activity":db.query(func.max(ObservationOperationalEvent.created_at)).scalar()}

@app.get("/admin/pilot/readiness")
def admin_pilot_readiness(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"database_reachable":True,"public_submission_available":True,"reviewer_authorization_configured":db.query(ObservationReviewerGrant).filter_by(status="ACTIVE").count()>0,"observation_review_available":True,"configured_jurisdictions":db.query(Jurisdiction).filter_by(status="ACTIVE").count(),"notification_delivery":"DISABLED_MANUAL_INSPECTION","feedback_system_available":True,"scientific_directory_state":"GOVERNED_ASSERTIONS_ONLY"}

@app.get("/admin/notifications")
def admin_notifications(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"items":[{"id":r.id,"event_type":r.event_type,"delivery_state":r.delivery_state,"attempts":r.delivery_attempts,"last_error":r.last_delivery_error,"created_at":r.created_at} for r in db.query(ObservationNotificationEvent).order_by(ObservationNotificationEvent.id.desc()).all()]}

@app.post("/admin/notifications/{event_id}/retry")
def retry_notification(event_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=NotificationDeliveryService(db).attempt(event_id);return {"id":row.id,"delivery_state":row.delivery_state,"attempts":row.delivery_attempts,"last_error":row.last_delivery_error}

@app.get("/reporter/status/{token}")
def reporter_status(token:str,db:Session=Depends(get_db)):
    try:return ReporterAccessService(db).safe_status(token)
    except ValueError as exc:raise HTTPException(410,str(exc))

@app.post("/reporter/respond/{token}")
def reporter_respond(token:str,payload:ReporterResponseRequest,db:Session=Depends(get_db)):
    if not payload.response_text.strip():raise HTTPException(422,"Response text is required")
    try:ReporterAccessService(db).respond(token,payload.response_text);return {"received":True,"message":"Your additional information was securely added to the report."}
    except ValueError as exc:raise HTTPException(410,str(exc))

@app.get("/admin/public-media")
def admin_public_media(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"items":[{"id":row.id,"taxon_id":row.taxon_id,"observation_id":row.observation_id,"media_type":row.media_type,"source_provider":row.source_provider,"creator":row.creator,"source_reference":row.source_reference,"license":row.license,"attribution_text":row.attribution_text,"remote_url":row.remote_url,"lifecycle_state":row.lifecycle_state,"public_visibility":row.public_visibility,"is_primary":row.is_primary} for row in db.query(GovernedPublicMedia).order_by(GovernedPublicMedia.id).all()]}

@app.post("/admin/public-media")
def admin_create_public_media(payload:AdminPublicMediaRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:return {"id":PublicMediaService(db).create(payload.model_dump()).id,"status":"READY_FOR_REVIEW"}
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.post("/admin/public-media/{media_id}/{action}")
def admin_review_public_media(media_id:int,action:str,primary:bool=False,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,GovernedPublicMedia,media_id,"Public media");service=PublicMediaService(db)
    try:
        if action=="approve":service.review(row,current_user.id,"APPROVED")
        elif action=="reject":service.review(row,current_user.id,"REJECTED")
        elif action=="publish":service.publish(row,primary)
        else:raise ValueError("Unknown media action")
        return service.safe(row)|{"lifecycle_state":row.lifecycle_state,"public_visibility":row.public_visibility}
    except Exception as exc:db.rollback();raise HTTPException(409,str(exc))

@app.get("/jurisdictions/{jurisdiction_identifier}")
def public_jurisdiction_detail(jurisdiction_identifier:str,db:Session=Depends(get_db)):
    query=db.query(Jurisdiction);jurisdiction=query.filter_by(id=int(jurisdiction_identifier)).one_or_none() if jurisdiction_identifier.isdigit() else query.filter(func.lower(Jurisdiction.slug)==jurisdiction_identifier.lower()).one_or_none()
    if not jurisdiction:raise HTTPException(404,"Jurisdiction not found")
    boundary=db.query(JurisdictionBoundary).filter_by(jurisdiction_id=jurisdiction.id,boundary_type="MARINE_MONITORING",status="ACTIVE").first();directory=EcologicalStatusReadService(db).marine_species(jurisdiction.id)
    return {"id":jurisdiction.id,"name":jurisdiction.name,"slug":jurisdiction.slug,"canonical_identifier":jurisdiction.canonical_identifier,"canonical_identifier_scheme":jurisdiction.canonical_identifier_scheme,"jurisdiction_type":jurisdiction.jurisdiction_type,"region":{"id":jurisdiction.region.id,"name":jurisdiction.region.name,"slug":jurisdiction.region.slug},"geographic_configuration_state":"CONFIGURED" if boundary else "NOT_CONFIGURED","governed_species_directory_state":"AVAILABLE" if directory else "EMPTY","governed_marine_species_count":len(directory),"governed_invasive_species_count":len([item for item in directory if "INVASIVE" in item["current_reviewed_status"]["statuses"]]),"report_sighting_url":f"/region/{jurisdiction.region.slug}/{jurisdiction.slug}/submit"}

@app.get("/admin/taxonomy/preparations/{preparation_id}")
def admin_taxonomy_preparation(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return _taxonomy_preparation_payload(_require_admin_record(db,TaxonomyPreparation,preparation_id,"Taxonomy preparation"))

@app.post("/admin/taxonomy/preparations/{preparation_id}/approve")
def admin_approve_taxonomy(preparation_id:int,payload:AdminTaxonomyApprovalRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,TaxonomyPreparation,preparation_id,"Taxonomy preparation")
    try: TaxonomyPreparationService(db).approve(row,user_id=current_user.id,approval_reference=payload.approval_reference,expected_fingerprint=payload.expected_preparation_fingerprint); db.commit(); db.refresh(row); return _taxonomy_preparation_payload(row)
    except Exception as exc: db.rollback(); raise HTTPException(status_code=409,detail=str(exc))

@app.post("/admin/taxonomy/preparations/{preparation_id}/apply")
def admin_apply_taxonomy(preparation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,TaxonomyPreparation,preparation_id,"Taxonomy preparation")
    try: return TaxonomyPreparationService(db).apply(row)
    except Exception as exc: db.rollback(); raise HTTPException(status_code=409,detail=str(exc))

@app.get("/admin/taxa/{taxon_id}/taxonomy-history")
def admin_taxonomy_history(taxon_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    taxon=_require_admin_record(db,Species,taxon_id,"Taxon"); rows=db.query(TaxonomyPreparation).filter_by(taxon_id=taxon.id).order_by(TaxonomyPreparation.id.desc()).all(); return {"taxon":_admin_taxon_payload(taxon),"count":len(rows),"history":[_taxonomy_preparation_payload(row) for row in rows]}

@app.get("/admin/taxa")
def admin_taxa(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    rows=db.query(Species).order_by(Species.scientific_name).all(); return {"count":len(rows),"taxa":[_admin_taxon_payload(row) for row in rows]}


@app.get("/admin/regions/{region_id}/taxa")
def admin_region_taxa(region_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    region = _require_admin_record(db, Region, region_id, "Region")
    entries = db.query(RegionalTaxonRegistry).filter_by(region_id=region.id).order_by(RegionalTaxonRegistry.id).all()
    return {"region": {"id": region.id, "name": region.name, "slug": region.slug}, "count": len(entries), "taxa": [{**_admin_taxon_payload(entry.taxon), "registry": {"id": entry.id, "registry_version": entry.registry_version, "inclusion_basis": entry.inclusion_basis, "review_status": entry.review_status, "reviewed_by": entry.reviewed_by, "reviewed_at": entry.reviewed_at, "approved_by": entry.approved_by, "approved_at": entry.approved_at, "provenance_fingerprint": entry.provenance_fingerprint, "superseded_at": entry.superseded_at}} for entry in entries]}


@app.get("/admin/taxa/{taxon_id}")
def admin_taxon_detail(taxon_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    taxon = _require_admin_record(db, Species, taxon_id, "Taxon")
    entries = db.query(RegionalTaxonRegistry).filter_by(taxon_id=taxon.id).order_by(RegionalTaxonRegistry.id).all()
    return {**_admin_taxon_payload(taxon), "regional_registry": [{"id": row.id, "region_id": row.region_id, "registry_version": row.registry_version, "review_status": row.review_status, "inclusion_basis": row.inclusion_basis, "provenance_fingerprint": row.provenance_fingerprint} for row in entries]}


@app.get("/admin/jurisdictions/{jurisdiction_id}/taxa/{taxon_id}/readiness")
def admin_jurisdiction_taxon_readiness(jurisdiction_id: int, taxon_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    jurisdiction = _require_admin_record(db, Jurisdiction, jurisdiction_id, "Jurisdiction")
    taxon = _require_admin_record(db, Species, taxon_id, "Taxon")
    return {"jurisdiction": {"id": jurisdiction.id, "name": jurisdiction.name, "region_id": jurisdiction.region_id}, "taxon": _admin_taxon_payload(taxon), **JurisdictionTaxonReadinessService(db).evaluate(jurisdiction, taxon).as_dict()}


@app.get("/admin/jurisdictions/{jurisdiction_id}/scientific-readiness")
def admin_jurisdiction_scientific_readiness(jurisdiction_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    jurisdiction = _require_admin_record(db, Jurisdiction, jurisdiction_id, "Jurisdiction")
    entries = db.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id).order_by(RegionalTaxonRegistry.id).all()
    service = JurisdictionTaxonReadinessService(db)
    return {"jurisdiction": {"id": jurisdiction.id, "name": jurisdiction.name, "region_id": jurisdiction.region_id}, "count": len(entries), "taxa": [{"taxon": _admin_taxon_payload(entry.taxon), "registry_status": entry.review_status, "readiness": service.evaluate(jurisdiction, entry.taxon).as_dict()} for entry in entries], "semantics": "Dimensional readiness only; no score and no scientific state mutation."}


def _scaling_service(db):
    return RegionalScientificScalingService(db)


@app.get("/admin/regions/{region_id}/scientific-scaling/summary")
def admin_scientific_scaling_summary(region_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: return _scaling_service(db).summary(region_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/regions/{region_id}/scientific-scaling/inventory")
def admin_scientific_scaling_inventory(region_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: return _scaling_service(db).inventory(region_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/regions/{region_id}/scientific-scaling/matrix")
def admin_scientific_scaling_matrix(region_id: int, jurisdiction_id: Optional[int] = None, taxon_id: Optional[int] = None,
                                    taxon_group: Optional[str] = None, dimension: Optional[str] = None, readiness_state: Optional[str] = None, search: Optional[str] = None,
                                    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                                    db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: return _scaling_service(db).matrix(region_id, jurisdiction_id=jurisdiction_id, taxon_id=taxon_id, taxon_group=taxon_group, dimension=dimension, readiness_state=readiness_state, search=search, page=page, page_size=page_size)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/regions/{region_id}/scientific-scaling/preflight")
def admin_scientific_scaling_preflight(region_id: int, jurisdiction_id: Optional[int] = None, taxon_id: Optional[int] = None,
                                       db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: return _scaling_service(db).preflight(region_id, jurisdiction_id=jurisdiction_id, taxon_id=taxon_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/regions/{region_id}/scientific-scaling/work-queue")
def admin_scientific_scaling_work_queue(region_id: int, jurisdiction_id: Optional[int] = None, taxon_id: Optional[int] = None,
                                        category: Optional[str] = None, state: Optional[str] = None,
                                        db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: payload = _scaling_service(db).preflight(region_id, jurisdiction_id=jurisdiction_id, taxon_id=taxon_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload["items"] = [item for item in payload["items"] if (not category or item["category"] == category) and (not state or item["state"] == state)]
    payload["count"] = len(payload["items"])
    payload["categories"] = {key: sum(item["category"] == key for item in payload["items"]) for key in sorted({item["category"] for item in payload["items"]})}
    return payload


@app.get("/admin/regions/{region_id}/scientific-scaling/jurisdictions/{jurisdiction_id}/taxa/{taxon_id}")
def admin_scientific_scaling_detail(region_id: int, jurisdiction_id: int, taxon_id: int,
                                    db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    try: return _scaling_service(db).detail(region_id, jurisdiction_id, taxon_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/early-warning/readiness/{observation_id}")
def admin_early_warning_readiness(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        result=EarlyWarningService(db).readiness(observation_id)
        return {"eligible":result["eligible"],"handoff":result["handoff"],"reasons":result["reasons"],"observation_id":observation_id}
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@app.post("/admin/early-warning/evaluate/{observation_id}")
def admin_evaluate_early_warning(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:
        row=EarlyWarningService(db).evaluate(observation_id);db.commit();return EarlyWarningService(db).payload(row)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.get("/admin/early-warning/queue")
def admin_early_warning_queue(jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    items=EarlyWarningService(db).queue(jurisdiction_id);return {"count":len(items),"items":items,"semantics":"Scientific review signals, not threats or ecological conclusions."}

@app.get("/admin/early-warning/summary")
def admin_early_warning_summary(jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    return {"counts":EarlyWarningService(db).summary(jurisdiction_id),"semantics":"Workflow counts are not ecosystem-health metrics."}

@app.get("/admin/early-warning/assessments/{assessment_id}")
def admin_early_warning_detail(assessment_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=db.get(AnomalyAssessment,assessment_id)
    if not row:raise HTTPException(status_code=404,detail="Assessment not found")
    return EarlyWarningService(db).payload(row)

@app.post("/admin/early-warning/assessments/{assessment_id}/disposition")
def admin_early_warning_disposition(assessment_id:int,payload:AnomalyDispositionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row=EarlyWarningService(db).disposition(assessment_id,current_user.id,payload.state,payload.reason);db.commit();return {"id":row.id,"assessment_id":row.anomaly_assessment_id,"from_state":row.from_state,"to_state":row.to_state,"reason":row.reason,"created_at":row.created_at}
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc

@app.get("/reviewer/early-warning")
def reviewer_early_warning(jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_operational_reviewer)):
    allowed=reviewer_jurisdiction_ids(db,current_user)
    if not current_user.is_platform_admin and jurisdiction_id and jurisdiction_id not in allowed:raise HTTPException(status_code=403,detail="Jurisdiction access required")
    items=[]
    for jid in ([jurisdiction_id] if jurisdiction_id else sorted(allowed)):
        items.extend(EarlyWarningService(db).queue(jid))
    return {"count":len(items),"items":items,"capabilities":{"view":True,"scientific_disposition":bool(current_user.is_platform_admin)},"semantics":"Operational reviewer access is view-only; anomaly disposition remains separate scientific authority."}

@app.get("/scientific-review/early-warning")
def scientific_early_warning(jurisdiction_id:Optional[int]=None,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    allowed=scientific_reviewer_jurisdiction_ids(db,current_user)
    if jurisdiction_id:require_scientific_jurisdiction(db,current_user,jurisdiction_id)
    items=[]
    for jid in ([jurisdiction_id] if jurisdiction_id else sorted(allowed)):items.extend(EarlyWarningService(db).queue(jid))
    return {"count":len(items),"items":items,"capabilities":{"scientific_disposition":True,"configuration_admin":bool(current_user.is_platform_admin)}}

@app.get("/scientific-review/early-warning/{assessment_id}")
def scientific_early_warning_detail(assessment_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    assessment=_require_admin_record(db,AnomalyAssessment,assessment_id,"Assessment");require_scientific_jurisdiction(db,current_user,assessment.jurisdiction_id);return EarlyWarningService(db).payload(assessment)

@app.post("/scientific-review/observations/{observation_id}/evaluate")
def scientific_evaluate_observation(observation_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    observation=_require_admin_record(db,Observation,observation_id,"Observation")
    if observation.jurisdiction_id is None:raise HTTPException(status_code=409,detail="Observation has no jurisdiction")
    require_scientific_jurisdiction(db,current_user,observation.jurisdiction_id)
    try:assessment=EarlyWarningService(db).evaluate(observation_id);db.commit();return EarlyWarningService(db).payload(assessment)
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.post("/scientific-review/early-warning/{assessment_id}/claim")
def scientific_claim(assessment_id:int,payload:AnomalyClaimRequest,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    assessment=_require_admin_record(db,AnomalyAssessment,assessment_id,"Assessment");require_scientific_jurisdiction(db,current_user,assessment.jurisdiction_id);reviewer_id=payload.reviewer_user_id or current_user.id
    grants=scientific_reviewer_jurisdiction_ids(db,current_user) if reviewer_id==current_user.id else scientific_reviewer_jurisdiction_ids(db,_require_admin_record(db,User,reviewer_id,"Reviewer"))
    if not current_user.is_platform_admin and reviewer_id!=current_user.id:raise HTTPException(status_code=403,detail="Only platform administrators may assign another reviewer")
    if assessment.jurisdiction_id not in grants:raise HTTPException(status_code=409,detail="Reviewer lacks scientific jurisdiction authority")
    try:
        operations=EarlyWarningOperations(db);row=operations.reassign(assessment,reviewer_id,current_user.id,payload.reason) if current_user.is_platform_admin and reviewer_id!=current_user.id else operations.claim(assessment,reviewer_id,current_user.id,payload.reason);db.commit();return {"id":row.id,"reviewer_user_id":row.reviewer_user_id,"status":row.status,"assigned_at":row.assigned_at}
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.post("/scientific-review/early-warning/{assessment_id}/disposition")
def scientific_disposition(assessment_id:int,payload:AnomalyDispositionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    assessment=_require_admin_record(db,AnomalyAssessment,assessment_id,"Assessment");require_scientific_jurisdiction(db,current_user,assessment.jurisdiction_id);row=EarlyWarningService(db).disposition(assessment_id,current_user.id,payload.state,payload.reason);db.commit();return {"id":row.id,"to_state":row.to_state,"reason":row.reason,"created_at":row.created_at}

@app.get("/scientific-review/early-warning/{assessment_id}/history")
def scientific_history(assessment_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_scientific_reviewer)):
    assessment=_require_admin_record(db,AnomalyAssessment,assessment_id,"Assessment");require_scientific_jurisdiction(db,current_user,assessment.jurisdiction_id);events=db.query(AnomalyReviewEvent).filter_by(anomaly_assessment_id=assessment_id).order_by(AnomalyReviewEvent.id).all();assignments=db.query(AnomalyReviewAssignment).filter_by(anomaly_assessment_id=assessment_id).order_by(AnomalyReviewAssignment.id).all();return {"review_events":[{"id":x.id,"from_state":x.from_state,"to_state":x.to_state,"reviewer_user_id":x.reviewer_user_id,"reason":x.reason,"created_at":x.created_at} for x in events],"assignments":[{"id":x.id,"reviewer_user_id":x.reviewer_user_id,"status":x.status,"assigned_at":x.assigned_at,"unassigned_at":x.unassigned_at,"reason":x.reason} for x in assignments]}

@app.get("/admin/scientific-reviewers")
def admin_scientific_reviewers(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    rows=db.query(ScientificReviewerGrant).order_by(ScientificReviewerGrant.id).all();return {"items":[{"id":x.id,"user_id":x.user_id,"user_display_name":db.get(User,x.user_id).display_name,"user_email":db.get(User,x.user_id).email,"jurisdiction_id":x.jurisdiction_id,"jurisdiction_name":db.get(Jurisdiction,x.jurisdiction_id).name,"role":x.role,"status":x.status,"grant_reference":x.grant_reference,"granted_at":x.granted_at,"revoked_at":x.revoked_at} for x in rows]}
@app.post("/admin/scientific-reviewers")
def admin_grant_scientific_reviewer(payload:ScientificReviewerGrantRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=EarlyWarningOperations(db).grant(payload.user_id,payload.jurisdiction_id,current_user.id,payload.reference);db.commit();return {"id":row.id,"status":row.status}
@app.post("/admin/scientific-reviewers/{grant_id}/revoke")
def admin_revoke_scientific_reviewer(grant_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=EarlyWarningOperations(db).revoke(_require_admin_record(db,ScientificReviewerGrant,grant_id,"Grant"),current_user.id);db.commit();return {"id":row.id,"status":row.status}

def _config_payload(x):return {"id":x.id,"jurisdiction_id":x.jurisdiction_id,"taxon_id":x.taxon_id,"version":x.configuration_version,"algorithm_version":x.algorithm_version,"mode":x.mode,"status":x.review_status,"enabled_signal_types":json.loads(x.enabled_signal_types_json),"spatial_rule":json.loads(x.spatial_rule_json) if x.spatial_rule_json else None,"temporal_rule":json.loads(x.temporal_rule_json) if x.temporal_rule_json else None,"minimum_evidence":json.loads(x.minimum_evidence_json),"environmental_context":json.loads(x.environmental_context_json),"automatic_evaluation_enabled":x.automatic_evaluation_enabled,"provenance":json.loads(x.provenance_json),"limitations":json.loads(x.limitations_json),"fingerprint":x.dependency_fingerprint,"review_reference":x.review_reference,"activated_at":x.activated_at,"deactivated_at":x.deactivated_at,"supersedes_configuration_id":x.supersedes_configuration_id}
def _config_values(payload):
    values=payload.model_dump();spatial=values.pop("spatial_rule");temporal=values.pop("temporal_rule")
    values.update(enabled_signal_types_json=canonical_json(values.pop("enabled_signal_types")),spatial_rule_json=canonical_json(spatial) if spatial is not None else None,temporal_rule_json=canonical_json(temporal) if temporal is not None else None,minimum_evidence_json=canonical_json(values.pop("minimum_evidence")),environmental_context_json=canonical_json(values.pop("environmental_context")),provenance_json=canonical_json(values.pop("provenance")),limitations_json=canonical_json(values.pop("limitations")))
    return values
@app.get("/admin/early-warning/configurations")
def admin_configs(jurisdiction_id:Optional[int]=None,taxon_id:Optional[int]=None,status:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    query=db.query(AnomalyConfiguration);query=query.filter_by(jurisdiction_id=jurisdiction_id) if jurisdiction_id else query;query=query.filter_by(taxon_id=taxon_id) if taxon_id else query;query=query.filter_by(review_status=status) if status else query
    return {"items":[_config_payload(x) for x in query.order_by(AnomalyConfiguration.jurisdiction_id,AnomalyConfiguration.taxon_id,AnomalyConfiguration.id.desc()).all()]}
@app.post("/admin/early-warning/configurations")
def admin_config_draft(payload:AnomalyConfigRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=EarlyWarningOperations(db).config_draft(_config_values(payload));db.commit();return _config_payload(row)
@app.put("/admin/early-warning/configurations/{config_id}")
def admin_config_update(config_id:int,payload:AnomalyConfigRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row=EarlyWarningOperations(db).update_draft(_require_admin_record(db,AnomalyConfiguration,config_id,"Configuration"),_config_values(payload));db.commit();return _config_payload(row)
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc
@app.post("/admin/early-warning/configurations/{config_id}/transition")
def admin_config_transition(config_id:int,payload:AnomalyConfigTransitionRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row=EarlyWarningOperations(db).transition_config(_require_admin_record(db,AnomalyConfiguration,config_id,"Configuration"),payload.target_state,current_user.id,payload.reference);db.commit();return _config_payload(row)
    except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

@app.get("/admin/early-warning/events")
def admin_events(state:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    q=db.query(ScientificDomainEvent);q=q.filter_by(processing_state=state) if state else q;rows=q.order_by(ScientificDomainEvent.created_at.desc()).all();return {"items":[{"id":x.id,"event_type":x.event_type,"jurisdiction_id":x.jurisdiction_id,"taxon_id":x.taxon_id,"observation_id":x.observation_id,"processing_state":x.processing_state,"attempts":x.attempts,"last_error":x.last_error,"created_at":x.created_at} for x in rows]}
@app.get("/admin/early-warning/events/summary")
def admin_event_summary(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    rows=db.query(ScientificDomainEvent.processing_state,func.count(ScientificDomainEvent.id)).group_by(ScientificDomainEvent.processing_state).all();return {"counts":dict(rows),"automatic_evaluation_enabled":db.query(AnomalyConfiguration).filter_by(review_status="ACTIVE",automatic_evaluation_enabled=True).count()>0}
@app.post("/admin/early-warning/events")
def admin_emit_event(payload:ScientificEventRequest,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    try:row=EarlyWarningOperations(db).emit(**payload.model_dump());db.commit();return {"id":row.id,"processing_state":row.processing_state}
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
@app.post("/admin/early-warning/events/{event_id}/process")
def admin_process_event(event_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=EarlyWarningOperations(db).process(_require_admin_record(db,ScientificDomainEvent,event_id,"Event"));db.commit();return {"id":row.id,"processing_state":row.processing_state,"attempts":row.attempts,"last_error":row.last_error}


def _validate_jurisdiction_values(db, values, item_id=None):
    region = _require_admin_record(db, Region, values["region_id"], "Region")
    slug = _admin_slug(values["slug"]); country_code = values["country_code"].strip().upper()
    if len(country_code) != 2: raise HTTPException(status_code=400, detail="Country code must contain two characters.")
    if not -90 <= values["center_latitude"] <= 90 or not -180 <= values["center_longitude"] <= 180: raise HTTPException(status_code=400, detail="Invalid map center coordinates.")
    if values["default_zoom"] < 0 or values["default_zoom"] > 22: raise HTTPException(status_code=400, detail="Default zoom must be between 0 and 22.")
    duplicate = db.query(Jurisdiction).filter(Jurisdiction.region_id == region.id, func.lower(Jurisdiction.slug) == slug)
    if item_id is not None: duplicate = duplicate.filter(Jurisdiction.id != item_id)
    if duplicate.first(): raise HTTPException(status_code=409, detail="Jurisdiction slug already exists in this region.")
    return region, slug, country_code


@app.post("/admin/jurisdictions")
def admin_create_jurisdiction(payload: AdminJurisdictionRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    values = payload.model_dump(); _, values["slug"], values["country_code"] = _validate_jurisdiction_values(db, values)
    values["status"] = _admin_status(values["status"]); values["name"] = values["name"].strip()
    if not values["name"]: raise HTTPException(status_code=400, detail="Jurisdiction name is required.")
    item = Jurisdiction(**values); db.add(item); db.commit(); db.refresh(item); return _admin_jurisdiction_payload(item)


@app.patch("/admin/jurisdictions/{jurisdiction_id}")
def admin_update_jurisdiction(jurisdiction_id: int, payload: AdminJurisdictionUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, Jurisdiction, jurisdiction_id, "Jurisdiction"); values = {"region_id": item.region_id, "name": item.name, "slug": item.slug, "country_code": item.country_code, "status": item.status, "center_latitude": item.center_latitude, "center_longitude": item.center_longitude, "default_zoom": item.default_zoom, **payload.model_dump(exclude_unset=True)}
    _, values["slug"], values["country_code"] = _validate_jurisdiction_values(db, values, item.id); values["status"] = _admin_status(values["status"]); values["name"] = values["name"].strip()
    for key, value in values.items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return _admin_jurisdiction_payload(item)


@app.get("/admin/jurisdictions/{jurisdiction_id}/boundaries")
def admin_jurisdiction_boundaries(jurisdiction_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, Jurisdiction, jurisdiction_id, "Jurisdiction"); payload = _admin_jurisdiction_payload(item); return {"count": len(payload["boundaries"]), "boundaries": payload["boundaries"], "geometry_editing_supported": False}


@app.get("/admin/organizations")
def admin_organizations(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    items = db.query(Organization).order_by(Organization.name).all(); return {"count": len(items), "organizations": [_admin_organization_payload(item) for item in items]}


@app.post("/admin/organizations")
def admin_create_organization(payload: AdminOrganizationRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    slug = _admin_slug(payload.slug); organization_type = payload.organization_type.upper()
    if organization_type not in ADMIN_ORGANIZATION_TYPES: raise HTTPException(status_code=400, detail="Invalid organization type.")
    if db.query(Organization).filter(func.lower(Organization.slug) == slug).first(): raise HTTPException(status_code=409, detail="Organization slug already exists.")
    if not payload.name.strip(): raise HTTPException(status_code=400, detail="Organization name is required.")
    item = Organization(name=payload.name.strip(), slug=slug, organization_type=organization_type, status=_admin_status(payload.status)); db.add(item); db.commit(); db.refresh(item); return _admin_organization_payload(item)


@app.patch("/admin/organizations/{organization_id}")
def admin_update_organization(organization_id: int, payload: AdminOrganizationUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, Organization, organization_id, "Organization"); values = payload.model_dump(exclude_unset=True)
    if "slug" in values:
        values["slug"] = _admin_slug(values["slug"])
        if db.query(Organization).filter(func.lower(Organization.slug) == values["slug"], Organization.id != item.id).first(): raise HTTPException(status_code=409, detail="Organization slug already exists.")
    if "organization_type" in values:
        values["organization_type"] = values["organization_type"].upper()
        if values["organization_type"] not in ADMIN_ORGANIZATION_TYPES: raise HTTPException(status_code=400, detail="Invalid organization type.")
    if "status" in values: values["status"] = _admin_status(values["status"])
    if "name" in values and not values["name"].strip(): raise HTTPException(status_code=400, detail="Organization name cannot be empty.")
    for key, value in values.items(): setattr(item, key, value.strip() if key == "name" else value)
    db.commit(); db.refresh(item); return _admin_organization_payload(item)


@app.post("/admin/organizations/{organization_id}/jurisdictions")
def admin_add_participation(organization_id: int, payload: AdminParticipationRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    organization = _require_admin_record(db, Organization, organization_id, "Organization"); _require_admin_record(db, Jurisdiction, payload.jurisdiction_id, "Jurisdiction")
    if db.query(OrganizationJurisdiction).filter_by(organization_id=organization.id, jurisdiction_id=payload.jurisdiction_id).first(): raise HTTPException(status_code=409, detail="Organization already has a relationship with this jurisdiction.")
    item = OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=payload.jurisdiction_id, status=_admin_status(payload.status)); db.add(item); db.commit(); db.refresh(organization); return _admin_organization_payload(organization)


@app.patch("/admin/organization-jurisdictions/{participation_id}")
def admin_update_participation(participation_id: int, payload: AdminParticipationUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, OrganizationJurisdiction, participation_id, "Organization-jurisdiction relationship"); item.status = _admin_status(payload.status); db.commit(); db.refresh(item.organization); return _admin_organization_payload(item.organization)


@app.post("/admin/users")
def admin_create_user(payload: AdminUserRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    email = payload.email.strip().lower()
    if not email or "@" not in email: raise HTTPException(status_code=400, detail="A valid email address is required.")
    if db.query(User).filter(func.lower(User.email) == email).first(): raise HTTPException(status_code=409, detail="User email already exists.")
    if not payload.display_name.strip(): raise HTTPException(status_code=400, detail="Display name is required.")
    try: password_hash = hash_password(payload.initial_password)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = User(email=email, display_name=payload.display_name.strip(), password_hash=password_hash, status=_admin_status(payload.status), is_platform_admin=False, organization_name=payload.organization_name.strip() if payload.organization_name else None, job_title=payload.job_title.strip() if payload.job_title else None); db.add(item); db.flush(); audit(db,"PILOT_USER_CREATED",current_user.id,"User",item.id,summary={"status":item.status}); db.commit(); db.refresh(item); return user_payload(db, item)


@app.patch("/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: AdminUserUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, User, user_id, "User"); values = payload.model_dump(exclude_unset=True)
    if "email" in values:
        values["email"] = values["email"].strip().lower()
        if db.query(User).filter(func.lower(User.email) == values["email"], User.id != item.id).first(): raise HTTPException(status_code=409, detail="User email already exists.")
    if "display_name" in values and not values["display_name"].strip(): raise HTTPException(status_code=400, detail="Display name cannot be empty.")
    if "status" in values:
        values["status"] = _admin_status(values["status"])
        if item.id == current_user.id and values["status"] == "INACTIVE": raise HTTPException(status_code=400, detail="You cannot deactivate your own active administrator account.")
    for key, value in values.items(): setattr(item, key, value.strip() if isinstance(value, str) and key == "display_name" else value)
    if values.get("status") == "INACTIVE":
        now = datetime.now(timezone.utc)
        for session in item.sessions:
            if session.revoked_at is None: session.revoked_at = now
    audit(db,"PILOT_USER_UPDATED",current_user.id,"User",item.id,summary={"changed_fields":sorted(values)})
    db.commit(); db.refresh(item); return user_payload(db, item)


@app.post("/admin/users/{user_id}/memberships")
def admin_add_membership(user_id: int, payload: AdminMembershipRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    user = _require_admin_record(db, User, user_id, "User"); _require_admin_record(db, Organization, payload.organization_id, "Organization"); role = payload.role.upper()
    if role not in ADMIN_ROLES: raise HTTPException(status_code=400, detail="Role must be VIEWER, REVIEWER, or MANAGER.")
    if db.query(OrganizationMembership).filter_by(user_id=user.id, organization_id=payload.organization_id).first(): raise HTTPException(status_code=409, detail="User already has a membership in this organization.")
    item = OrganizationMembership(user_id=user.id, organization_id=payload.organization_id, role=role, status=_admin_status(payload.status)); db.add(item); db.commit(); db.refresh(user); return user_payload(db, user)


@app.patch("/admin/memberships/{membership_id}")
def admin_update_membership(membership_id: int, payload: AdminMembershipUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    item = _require_admin_record(db, OrganizationMembership, membership_id, "Membership"); values = payload.model_dump(exclude_unset=True)
    if "role" in values:
        values["role"] = values["role"].upper()
        if values["role"] not in ADMIN_ROLES: raise HTTPException(status_code=400, detail="Role must be VIEWER, REVIEWER, or MANAGER.")
    if "status" in values: values["status"] = _admin_status(values["status"])
    for key, value in values.items(): setattr(item, key, value)
    db.commit(); db.refresh(item.user); return user_payload(db, item.user)


def _jurisdiction_query(db: Session, region_slug: str, jurisdiction_slug: str):
    return (
        db.query(Jurisdiction)
        .join(Region)
        .filter(
            func.lower(Region.slug) == region_slug.lower(),
            func.lower(Jurisdiction.slug) == jurisdiction_slug.lower(),
        )
    )


def _require_jurisdiction(db: Session, region_slug: str, jurisdiction_slug: str):
    jurisdiction = _jurisdiction_query(db, region_slug, jurisdiction_slug).first()
    if jurisdiction is None:
        raise HTTPException(status_code=404, detail="Jurisdiction not found.")
    return jurisdiction


def _geography_payload(jurisdiction: Jurisdiction):
    return {
        "region": {
            "id": jurisdiction.region.id,
            "name": jurisdiction.region.name,
            "slug": jurisdiction.region.slug,
            "status": jurisdiction.region.status,
        },
        "jurisdiction": {
            "id": jurisdiction.id,
            "name": jurisdiction.name,
            "slug": jurisdiction.slug,
            "country_code": jurisdiction.country_code,
            "status": jurisdiction.status,
        },
    }


def _scope_observation_query(query, db, region_slug=None, jurisdiction_slug=None):
    if jurisdiction_slug and not region_slug:
        raise HTTPException(status_code=400, detail="region_slug is required with jurisdiction_slug.")
    if region_slug and jurisdiction_slug:
        jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
        return query.filter(Observation.jurisdiction_id == jurisdiction.id)
    if region_slug:
        region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
        if region is None:
            raise HTTPException(status_code=404, detail="Region not found.")
        return query.join(Jurisdiction).filter(Jurisdiction.region_id == region.id)
    return query


@app.get("/regions")
def get_regions(db: Session = Depends(get_db)):
    regions = db.query(Region).order_by(Region.name).all()
    return {"count": len(regions), "regions": [{"id": item.id, "name": item.name, "slug": item.slug, "status": item.status,"jurisdiction_count":len(item.jurisdictions)} for item in regions]}


@app.get("/regions/{region_slug}")
def get_region(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    service=EcologicalStatusReadService(db);jurisdictions=[]
    for item in sorted(region.jurisdictions,key=lambda row:row.name):
        boundary=next((row for row in item.boundaries if row.status=="ACTIVE" and row.boundary_type=="MARINE_MONITORING"),None);directory=service.marine_species(item.id);jurisdictions.append({"id":item.id,"name":item.name,"slug":item.slug,"canonical_identifier":item.canonical_identifier,"jurisdiction_type":item.jurisdiction_type,"geographic_configuration_state":"CONFIGURED" if boundary else "NOT_CONFIGURED","governed_species_directory_state":"AVAILABLE" if directory else "EMPTY","marine_species_count":len(directory)})
    return {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status,"jurisdictions":jurisdictions}


@app.get("/regions/{region_slug}/jurisdictions")
def get_region_jurisdictions(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    jurisdictions = db.query(Jurisdiction).filter(Jurisdiction.region_id == region.id).order_by(Jurisdiction.name).all()
    return {"region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status}, "count": len(jurisdictions), "jurisdictions": [_jurisdiction_payload(item) for item in jurisdictions]}


def _regional_jurisdiction_summary(db, region):
    summaries = []
    jurisdiction_ids = [item.id for item in region.jurisdictions]
    if not jurisdiction_ids:
        return summaries

    boundary_by_jurisdiction = {}
    for boundary in db.query(JurisdictionBoundary).filter(
        JurisdictionBoundary.jurisdiction_id.in_(jurisdiction_ids),
        JurisdictionBoundary.status == "ACTIVE",
        JurisdictionBoundary.boundary_type == "MARINE_MONITORING",
    ).all():
        boundary_by_jurisdiction[boundary.jurisdiction_id] = boundary

    observation_counts_rows = db.query(
        Observation.jurisdiction_id,
        Observation.verification_status,
        func.count(Observation.id),
    ).filter(Observation.jurisdiction_id.in_(jurisdiction_ids)).group_by(
        Observation.jurisdiction_id, Observation.verification_status,
    ).all()
    observation_counts = {}
    for jurisdiction_id, verification_status, count in observation_counts_rows:
        observation_counts.setdefault(jurisdiction_id, {"total": 0, "confirmed": 0, "corrected": 0, "pending": 0, "needs_more_review": 0})
        observation_counts[jurisdiction_id]["total"] += count
        if verification_status == "CONFIRMED":
            observation_counts[jurisdiction_id]["confirmed"] += count
        elif verification_status == "CORRECTED":
            observation_counts[jurisdiction_id]["corrected"] += count
        elif verification_status == "PENDING":
            observation_counts[jurisdiction_id]["pending"] += count
        elif verification_status == "NEEDS_MORE_REVIEW":
            observation_counts[jurisdiction_id]["needs_more_review"] += count

    investigation_counts_rows = db.query(
        Investigation.jurisdiction_id,
        Investigation.status,
        func.count(Investigation.id),
    ).filter(Investigation.jurisdiction_id.in_(jurisdiction_ids)).group_by(
        Investigation.jurisdiction_id, Investigation.status,
    ).all()
    investigation_counts = {}
    for jurisdiction_id, status, count in investigation_counts_rows:
        bucket = investigation_counts.setdefault(jurisdiction_id, {"total": 0, "active": 0})
        bucket["total"] += count
        if status in {"PLANNED", "IN_PROGRESS"}:
            bucket["active"] += count

    field_visit_counts_rows = db.query(
        FieldVisit.jurisdiction_id,
        func.count(FieldVisit.id),
    ).filter(FieldVisit.jurisdiction_id.in_(jurisdiction_ids)).group_by(
        FieldVisit.jurisdiction_id,
    ).all()
    field_visit_counts = {jurisdiction_id: count for jurisdiction_id, count in field_visit_counts_rows}

    org_counts_rows = db.query(
        OrganizationJurisdiction.jurisdiction_id,
        func.count(func.distinct(OrganizationJurisdiction.organization_id)),
    ).filter(
        OrganizationJurisdiction.jurisdiction_id.in_(jurisdiction_ids),
        OrganizationJurisdiction.status == "ACTIVE",
        OrganizationJurisdiction.organization.has(status="ACTIVE"),
    ).group_by(OrganizationJurisdiction.jurisdiction_id).all()
    org_counts = {jurisdiction_id: count for jurisdiction_id, count in org_counts_rows}

    program_counts_rows = db.query(
        SpeciesProgram.jurisdiction_id,
        func.count(SpeciesProgram.id),
    ).filter(
        SpeciesProgram.jurisdiction_id.in_(jurisdiction_ids),
        SpeciesProgram.status == "ACTIVE",
    ).group_by(SpeciesProgram.jurisdiction_id).all()
    program_counts = {jurisdiction_id: count for jurisdiction_id, count in program_counts_rows}

    summaries_by_jurisdiction = {}
    for jurisdiction in region.jurisdictions:
        capabilities = _jurisdiction_capabilities(jurisdiction)
        observation_breakdown = observation_counts.get(jurisdiction.id, {"total": 0, "confirmed": 0, "corrected": 0, "pending": 0, "needs_more_review": 0})
        pending_review = observation_breakdown["pending"] + observation_breakdown["needs_more_review"]
        investigation_breakdown = investigation_counts.get(jurisdiction.id, {"total": 0, "active": 0})
        field_visits_total = field_visit_counts.get(jurisdiction.id, 0)
        participating_orgs = org_counts.get(jurisdiction.id, 0)
        programs_total = program_counts.get(jurisdiction.id, 0)
        boundary = boundary_by_jurisdiction.get(jurisdiction.id)
        payload = {
            "id": jurisdiction.id,
            "name": jurisdiction.name,
            "slug": jurisdiction.slug,
            "country_code": jurisdiction.country_code,
            "status": jurisdiction.status,
            "region": {"id": jurisdiction.region.id, "name": jurisdiction.region.name, "slug": jurisdiction.region.slug},
            "operational_boundary_configured": boundary is not None,
            "boundary_source": None if boundary is None else {
                "source": boundary.source,
                "version": boundary.source_version,
                "source_reference": boundary.source_reference,
            },
            "observations": {
                "total": observation_breakdown["total"],
                "confirmed": observation_breakdown["confirmed"],
                "corrected": observation_breakdown["corrected"],
                "pending_review": pending_review,
                "needs_more_review": observation_breakdown["needs_more_review"],
            },
            "investigations": {
                "total": investigation_breakdown["total"],
                "active": investigation_breakdown["active"],
            },
            "field_visits_total": field_visits_total,
            "participating_organizations": participating_orgs,
            "scientific_programs_total": programs_total,
            "capabilities": capabilities,
            "scientific_deployment": {
                "habitat_suitability": "Available" if capabilities["habitat_suitability"] else "Not configured",
                "monitoring_priority": "Available" if capabilities["monitoring_priority"] else "Not configured",
            },
        }
        summaries_by_jurisdiction[jurisdiction.id] = payload

    for jurisdiction_id, payload in summaries_by_jurisdiction.items():
        summaries.append(payload)
    summaries.sort(key=lambda item: item["name"])
    return summaries


def _regional_overview_payload(db, region):
    jurisdiction_summaries = _regional_jurisdiction_summary(db, region)
    jurisdiction_ids = [item["id"] for item in jurisdiction_summaries]

    jurisdictions_total = len(jurisdiction_summaries)
    active_jurisdictions = sum(1 for item in jurisdiction_summaries if item["status"] == "ACTIVE")
    boundary_configured = sum(1 for item in jurisdiction_summaries if item["operational_boundary_configured"])
    participating_jurisdictions = sum(1 for item in jurisdiction_summaries if item["participating_organizations"] > 0)

    observation_total = sum(item["observations"]["total"] for item in jurisdiction_summaries)
    observation_confirmed = sum(item["observations"]["confirmed"] for item in jurisdiction_summaries)
    observation_corrected = sum(item["observations"]["corrected"] for item in jurisdiction_summaries)
    observation_pending_review = sum(item["observations"]["pending_review"] for item in jurisdiction_summaries)
    observation_needs_more_review = sum(item["observations"]["needs_more_review"] for item in jurisdiction_summaries)

    investigations_total = sum(item["investigations"]["total"] for item in jurisdiction_summaries)
    investigations_active = sum(item["investigations"]["active"] for item in jurisdiction_summaries)
    field_visits_total = sum(item["field_visits_total"] for item in jurisdiction_summaries)

    jurisdictions_with_species_programs = sum(1 for item in jurisdiction_summaries if item["scientific_programs_total"] > 0)
    jurisdictions_with_suitability = sum(1 for item in jurisdiction_summaries if item["capabilities"]["habitat_suitability"])
    jurisdictions_with_monitoring_priority = sum(1 for item in jurisdiction_summaries if item["capabilities"]["monitoring_priority"])

    return {
        "region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status},
        "jurisdictions": {
            "total": jurisdictions_total,
            "active": active_jurisdictions,
            "boundary_configured": boundary_configured,
            "with_participating_organizations": participating_jurisdictions,
        },
        "observations": {
            "total": observation_total,
            "confirmed": observation_confirmed,
            "corrected": observation_corrected,
            "pending_review": observation_pending_review,
            "needs_more_review": observation_needs_more_review,
        },
        "operational_activity": {
            "investigations_total": investigations_total,
            "investigations_active": investigations_active,
            "field_visits_total": field_visits_total,
        },
        "scientific_deployments": {
            "jurisdictions_with_species_programs": jurisdictions_with_species_programs,
            "jurisdictions_with_suitability": jurisdictions_with_suitability,
            "jurisdictions_with_monitoring_priority": jurisdictions_with_monitoring_priority,
        },
        "jurisdiction_summaries": jurisdiction_summaries,
    }


@app.get("/regions/{region_slug}/overview")
def get_region_overview(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    if region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region is not active.")
    return _regional_overview_payload(db, region)


@app.get("/regions/{region_slug}/species-evidence")
def get_region_species_evidence(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    if region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region is not active.")

    jurisdiction_ids = [item.id for item in region.jurisdictions]
    if not jurisdiction_ids:
        return {"region": {"id": region.id, "name": region.name, "slug": region.slug}, "count": 0, "species_evidence": [], "note": "No jurisdictions configured for this region."}

    observation_rows = db.query(Observation).filter(
        Observation.jurisdiction_id.in_(jurisdiction_ids),
    ).all()

    by_species = {}
    canonical_species_by_name = {}
    species_program_rows = db.query(
        SpeciesProgram.id,
        SpeciesProgram.jurisdiction_id,
        SpeciesProgram.scientific_name,
        SpeciesProgram.common_name,
        SpeciesProgram.status,
    ).filter(
        SpeciesProgram.jurisdiction_id.in_(jurisdiction_ids),
        SpeciesProgram.status == "ACTIVE",
    ).all()
    canonical_species_lookup = {}
    try:
        canonical_species_lookup = {
            row.scientific_name: row.id
            for row in db.query(Species).all()
        }
    except Exception:
        canonical_species_lookup = {}
    for species_row in species_program_rows:
        if species_row.scientific_name not in canonical_species_by_name:
            canonical_species_by_name[species_row.scientific_name] = {
                "common_name": species_row.common_name,
                "species_id": canonical_species_lookup.get(species_row.scientific_name),
            }

    for observation in observation_rows:
        display_species = observation.verified_species if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species else observation.species
        if not display_species:
            continue
        bucket = by_species.setdefault(display_species, {
            "scientific_name": display_species,
            "common_name": None,
            "jurisdictions": {},
            "total_observations": 0,
            "verified_or_corrected": 0,
            "ai_supported": 0,
        })
        bucket["total_observations"] += 1
        if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
            bucket["verified_or_corrected"] += 1
        elif observation.verification_status == "PENDING" and observation.identification_status == "accepted":
            bucket["ai_supported"] += 1
        jurisdiction_slug = observation.jurisdiction.slug if observation.jurisdiction else None
        jurisdiction_name = observation.jurisdiction.name if observation.jurisdiction else None
        if jurisdiction_slug is not None:
            jurisdiction_bucket = bucket["jurisdictions"].setdefault(jurisdiction_slug, {
                "slug": jurisdiction_slug,
                "name": jurisdiction_name,
                "total": 0,
                "verified_or_corrected": 0,
            })
            jurisdiction_bucket["total"] += 1
            if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
                jurisdiction_bucket["verified_or_corrected"] += 1

    species_evidence = []
    for scientific_name, bucket in by_species.items():
        canonical = canonical_species_by_name.get(scientific_name)
        bucket["common_name"] = canonical["common_name"] if canonical else None
        bucket["canonical_species_id"] = canonical["species_id"] if canonical else None
        bucket["jurisdictions"] = [
            {"slug": slug, "name": info["name"], "total": info["total"], "verified_or_corrected": info["verified_or_corrected"]}
            for slug, info in bucket["jurisdictions"].items()
        ]
        bucket["jurisdictions"].sort(key=lambda item: item["name"])
        species_evidence.append(bucket)

    species_evidence.sort(key=lambda item: (-item["total_observations"], item["scientific_name"]))

    return {
        "region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status},
        "count": len(species_evidence),
        "species_evidence": species_evidence,
        "note": "Aggregated from operational observation evidence across the region's jurisdictions. Not a regional abundance estimate.",
    }


def _build_species_intelligence(db, region_jurisdictions, scope_jurisdictions=None):
    """Build regional or per-jurisdiction species intelligence.

    Canonical identity is anchored on the Species table. Observation
    scientific_names and SpeciesProgram scientific_names are matched to
    canonical rows. Scientific names that do not match a canonical Species
    record are returned as ``unresolved_evidence`` rather than being silently
    remapped.

    Aggregation is server-side and designed to scale to substantially more
    observations and species than currently exist.

    ``region_jurisdictions`` provides the full set of jurisdictions for the
    region (used for canonical species presence detection). When provided,
    ``scope_jurisdictions`` restricts the per-jurisdiction output to a
    single jurisdiction while still computing region-wide representation so
    canonical species that are absent in the scope jurisdiction are still
    surfaced as canonical identities with "no platform evidence recorded".
    """
    region_jurisdiction_ids = [item.id for item in region_jurisdictions]
    if not region_jurisdiction_ids:
        return {
            "canonical_species": [],
            "unresolved_evidence": [],
            "jurisdictions": [],
        }
    if scope_jurisdictions is None:
        scope_jurisdictions = region_jurisdictions

    canonical_species_rows = db.query(
        Species.id,
        Species.scientific_name,
        Species.common_name,
        Species.status,
    ).filter(
        Species.status == "ACTIVE",
    ).all()
    canonical_by_id = {row.id: row for row in canonical_species_rows}
    canonical_by_name = {row.scientific_name: row for row in canonical_species_rows}

    species_program_rows = db.query(
        SpeciesProgram.id,
        SpeciesProgram.jurisdiction_id,
        SpeciesProgram.species_id,
        SpeciesProgram.scientific_name,
        SpeciesProgram.common_name,
        SpeciesProgram.status,
    ).filter(
        SpeciesProgram.jurisdiction_id.in_(region_jurisdiction_ids),
        SpeciesProgram.status == "ACTIVE",
    ).all()
    species_program_ids = [row.id for row in species_program_rows]

    deployment_rows = []
    if species_program_ids:
        deployment_rows = db.query(
            SuitabilityDeployment.id,
            SuitabilityDeployment.species_program_id,
            SuitabilityDeployment.model_version,
            SuitabilityDeployment.status,
            SpeciesProgram.jurisdiction_id,
        ).join(
            SpeciesProgram, SpeciesProgram.id == SuitabilityDeployment.species_program_id
        ).filter(
            SuitabilityDeployment.species_program_id.in_(species_program_ids),
            SuitabilityDeployment.status == "ACTIVE",
        ).all()

    priority_generation_rows = []
    if species_program_ids:
        priority_generation_rows = db.query(
            NextAreaSnapshotGeneration.id,
            NextAreaSnapshotGeneration.species_program_id,
            NextAreaSnapshotGeneration.status,
            NextAreaSnapshotGeneration.is_active,
            SpeciesProgram.jurisdiction_id,
        ).join(
            SpeciesProgram, SpeciesProgram.id == NextAreaSnapshotGeneration.species_program_id
        ).filter(
            NextAreaSnapshotGeneration.species_program_id.in_(species_program_ids),
            NextAreaSnapshotGeneration.status == "ACTIVE",
            NextAreaSnapshotGeneration.is_active.is_(True),
        ).all()

    observation_rows = db.query(
        Observation.id,
        Observation.jurisdiction_id,
        Observation.species,
        Observation.verified_species,
        Observation.verification_status,
        Observation.identification_status,
    ).filter(
        Observation.jurisdiction_id.in_(region_jurisdiction_ids),
    ).all()

    jurisdiction_meta = {
        item.id: {
            "id": item.id,
            "name": item.name,
            "slug": item.slug,
            "country_code": item.country_code,
        }
        for item in region_jurisdictions
    }

    canonical_states = {
        canonical_id: {
            "evidence": {"total": 0, "verified_or_corrected": 0, "ai_supported": 0, "pending_review": 0, "unresolved_observations": 0},
            "jurisdictions": {},
        }
        for canonical_id in canonical_by_id
    }

    program_by_id = {row.id: row for row in species_program_rows}
    canonical_states_with_programs = set()
    for program in species_program_rows:
        if program.species_id and program.species_id in canonical_states:
            canonical_states[program.species_id]["scientific_program"] = {
                "id": program.id,
                "jurisdiction_id": program.jurisdiction_id,
                "common_name": program.common_name,
            }
            canonical_states_with_programs.add(program.species_id)

    for deployment in deployment_rows:
        program = program_by_id.get(deployment.species_program_id)
        if not program or not program.species_id or program.species_id not in canonical_states:
            continue
        canonical_states[program.species_id].setdefault("suitability_deployments", []).append({
            "id": deployment.id,
            "species_program_id": deployment.species_program_id,
            "model_version": deployment.model_version,
            "jurisdiction_id": program.jurisdiction_id,
        })

    for generation in priority_generation_rows:
        program = program_by_id.get(generation.species_program_id)
        if not program or not program.species_id or program.species_id not in canonical_states:
            continue
        canonical_states[program.species_id].setdefault("monitoring_priority_generations", []).append({
            "id": generation.id,
            "species_program_id": generation.species_program_id,
            "jurisdiction_id": program.jurisdiction_id,
        })

    canonical_observation_counts = {}
    for observation in observation_rows:
        canonical_id = None
        if observation.verified_species and observation.verification_status in {"CONFIRMED", "CORRECTED"}:
            canonical_row = canonical_by_name.get(observation.verified_species)
            if canonical_row:
                canonical_id = canonical_row.id
        if canonical_id is None and observation.species:
            canonical_row = canonical_by_name.get(observation.species)
            if canonical_row:
                canonical_id = canonical_row.id
        if canonical_id is None or canonical_id not in canonical_states:
            continue
        evidence = canonical_states[canonical_id]["evidence"]
        evidence["total"] += 1
        if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
            evidence["verified_or_corrected"] += 1
        elif observation.verification_status == "PENDING" and observation.identification_status == "accepted":
            evidence["ai_supported"] += 1
        elif observation.verification_status in {"PENDING", "NEEDS_MORE_REVIEW"}:
            evidence["pending_review"] += 1
        else:
            evidence["unresolved_observations"] += 1
        per_jurisdiction = canonical_states[canonical_id]["jurisdictions"].setdefault(
            observation.jurisdiction_id,
            {
                "jurisdiction_id": observation.jurisdiction_id,
                "evidence": {"total": 0, "verified_or_corrected": 0, "ai_supported": 0, "pending_review": 0, "unresolved_observations": 0},
                "scientific_program": False,
                "suitability": "Not configured",
                "monitoring_priority": "Not configured",
            },
        )
        per_jurisdiction["evidence"]["total"] += 1
        if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
            per_jurisdiction["evidence"]["verified_or_corrected"] += 1
        elif observation.verification_status == "PENDING" and observation.identification_status == "accepted":
            per_jurisdiction["evidence"]["ai_supported"] += 1
        elif observation.verification_status in {"PENDING", "NEEDS_MORE_REVIEW"}:
            per_jurisdiction["evidence"]["pending_review"] += 1
        else:
            per_jurisdiction["evidence"]["unresolved_observations"] += 1

    program_to_canonical = {}
    for program in species_program_rows:
        if program.species_id and program.species_id in canonical_states:
            program_to_canonical[program.id] = program.species_id

    scope_jurisdiction_ids = {item.id for item in scope_jurisdictions}
    for canonical_id, payload in canonical_states.items():
        per_jurisdictions = payload["jurisdictions"]
        for jurisdiction_id in scope_jurisdiction_ids:
            if jurisdiction_id in per_jurisdictions:
                continue
            per_jurisdictions[jurisdiction_id] = {
                "jurisdiction_id": jurisdiction_id,
                "evidence": {"total": 0, "verified_or_corrected": 0, "ai_supported": 0, "pending_review": 0, "unresolved_observations": 0},
                "scientific_program": False,
                "suitability": "Not configured",
                "monitoring_priority": "Not configured",
            }
        for per_jurisdiction in per_jurisdictions.values():
            has_program = any(
                program.jurisdiction_id == per_jurisdiction["jurisdiction_id"]
                for program in species_program_rows
                if program.species_id == canonical_id
            )
            per_jurisdiction["scientific_program"] = has_program
            has_suitability = any(
                dep["jurisdiction_id"] == per_jurisdiction["jurisdiction_id"]
                for dep in payload.get("suitability_deployments", [])
            )
            per_jurisdiction["suitability"] = "Available" if has_suitability else "Not configured"
            has_priority = any(
                gen["jurisdiction_id"] == per_jurisdiction["jurisdiction_id"]
                for gen in payload.get("monitoring_priority_generations", [])
            )
            per_jurisdiction["monitoring_priority"] = "Available" if has_priority else "Not configured"
            per_jurisdiction["jurisdiction"] = jurisdiction_meta.get(per_jurisdiction["jurisdiction_id"])

    canonical_list = []
    for canonical_id, canonical_row in canonical_by_id.items():
        region_representation = (
            canonical_states[canonical_id]["evidence"]["total"] > 0
            or any(
                program.species_id == canonical_id
                for program in species_program_rows
            )
        )
        if not region_representation:
            continue
        per_jurisdictions = sorted(
            (
                item for item in canonical_states[canonical_id]["jurisdictions"].values()
                if item["jurisdiction_id"] in scope_jurisdiction_ids
            ),
            key=lambda item: item["jurisdiction"].get("name", "") if item.get("jurisdiction") else "",
        )
        if not per_jurisdictions:
            continue
        jurisdictions_with_evidence = sum(1 for item in per_jurisdictions if item["evidence"]["total"] > 0)
        canonical_list.append({
            "id": canonical_row.id,
            "scientific_name": canonical_row.scientific_name,
            "common_name": canonical_row.common_name,
            "status": canonical_row.status,
            "evidence": canonical_states[canonical_id]["evidence"],
            "jurisdictions_with_evidence": jurisdictions_with_evidence,
            "scientific_programs": [
                {
                    "id": program["id"],
                    "jurisdiction_id": program["jurisdiction_id"],
                    "jurisdiction": jurisdiction_meta.get(program["jurisdiction_id"]),
                    "common_name": program.get("common_name"),
                }
                for program in [
                    {"id": sp.id, "jurisdiction_id": sp.jurisdiction_id, "common_name": sp.common_name}
                    for sp in species_program_rows
                    if sp.species_id == canonical_id
                ]
            ],
            "suitability_deployments": [
                {"id": dep["id"], "jurisdiction_id": dep["jurisdiction_id"], "model_version": dep["model_version"]}
                for dep in canonical_states[canonical_id].get("suitability_deployments", [])
                if dep["jurisdiction_id"] in scope_jurisdiction_ids
            ],
            "monitoring_priority_generations": [
                {"id": gen["id"], "jurisdiction_id": gen["jurisdiction_id"]}
                for gen in canonical_states[canonical_id].get("monitoring_priority_generations", [])
                if gen["jurisdiction_id"] in scope_jurisdiction_ids
            ],
            "per_jurisdiction": per_jurisdictions,
        })

    canonical_list.sort(key=lambda item: (-item["evidence"]["total"], item["scientific_name"]))

    unresolved_evidence_rows = {}
    for observation in observation_rows:
        canonical_id = None
        if observation.verified_species and observation.verification_status in {"CONFIRMED", "CORRECTED"}:
            canonical_row = canonical_by_name.get(observation.verified_species)
            if canonical_row:
                canonical_id = canonical_row.id
        if canonical_id is None and observation.species:
            canonical_row = canonical_by_name.get(observation.species)
            if canonical_row:
                canonical_id = canonical_row.id
        display_name = None
        if observation.verified_species and observation.verification_status in {"CONFIRMED", "CORRECTED"}:
            display_name = observation.verified_species
        elif observation.species:
            display_name = observation.species
        if canonical_id is not None or not display_name:
            continue
        if observation.jurisdiction_id not in scope_jurisdiction_ids:
            continue
        bucket = unresolved_evidence_rows.setdefault(display_name, {
            "scientific_name": display_name,
            "evidence": {"total": 0, "verified_or_corrected": 0, "ai_supported": 0, "pending_review": 0, "unresolved_observations": 0},
            "jurisdictions": {},
        })
        bucket["evidence"]["total"] += 1
        if observation.verification_status in {"CONFIRMED", "CORRECTED"} and observation.verified_species:
            bucket["evidence"]["verified_or_corrected"] += 1
        elif observation.verification_status == "PENDING" and observation.identification_status == "accepted":
            bucket["evidence"]["ai_supported"] += 1
        elif observation.verification_status in {"PENDING", "NEEDS_MORE_REVIEW"}:
            bucket["evidence"]["pending_review"] += 1
        else:
            bucket["evidence"]["unresolved_observations"] += 1
        per_jurisdiction = bucket["jurisdictions"].setdefault(
            observation.jurisdiction_id,
            {
                "jurisdiction_id": observation.jurisdiction_id,
                "name": jurisdiction_meta[observation.jurisdiction_id]["name"],
                "total": 0,
            },
        )
        per_jurisdiction["total"] += 1

    unresolved_evidence = []
    for name, bucket in unresolved_evidence_rows.items():
        bucket["jurisdictions"] = sorted(
            bucket["jurisdictions"].values(),
            key=lambda item: item["name"],
        )
        unresolved_evidence.append(bucket)
    unresolved_evidence.sort(key=lambda item: (-item["evidence"]["total"], item["scientific_name"]))

    return {
        "canonical_species": canonical_list,
        "unresolved_evidence": unresolved_evidence,
    }


@app.get("/regions/{region_slug}/species")
def get_region_species_intelligence(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    if region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region is not active.")
    payload = _build_species_intelligence(db, region.jurisdictions)
    return {
        "region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status},
        "count": len(payload["canonical_species"]),
        "species": payload["canonical_species"],
        "unresolved_evidence_count": len(payload["unresolved_evidence"]),
        "unresolved_evidence": payload["unresolved_evidence"],
        "note": "Canonical species identity is anchored on the Species table. Operational evidence is aggregated regionally; predictive scientific deployments remain jurisdiction-specific.",
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/species")
def get_jurisdiction_species_intelligence(region_slug: str, jurisdiction_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    if region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region is not active.")
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    payload = _build_species_intelligence(db, region.jurisdictions, scope_jurisdictions=[jurisdiction])
    return {
        "region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status},
        "jurisdiction": {
            "id": jurisdiction.id,
            "name": jurisdiction.name,
            "slug": jurisdiction.slug,
            "country_code": jurisdiction.country_code,
            "status": jurisdiction.status,
        },
        "count": len(payload["canonical_species"]),
        "species": payload["canonical_species"],
        "unresolved_evidence_count": len(payload["unresolved_evidence"]),
        "unresolved_evidence": payload["unresolved_evidence"],
        "note": "Jurisdiction-scoped canonical species intelligence. Predictive deployments are per-jurisdiction and are not combined across jurisdictions.",
    }


def _utc_date(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_regional_activity_buckets(db, region_jurisdictions, jurisdiction_meta_by_id):
    """Build operational reporting-activity buckets over time.

    Bucket strategy:
    - daily when the data spans <= 31 days
    - monthly when the data spans > 31 days (still produces compact buckets)

    Returns a list of buckets with ISO timestamps, totals, and
    verification-state breakdowns. Empty buckets between observations are
    NOT emitted to avoid dozens of zero rows.
    """
    jurisdiction_ids = [item.id for item in region_jurisdictions]
    if not jurisdiction_ids:
        return {
            "strategy": "daily",
            "bucket_count": 0,
            "earliest": None,
            "latest": None,
            "buckets": [],
        }
    rows = db.query(
        Observation.created_at,
        Observation.verification_status,
    ).filter(
        Observation.jurisdiction_id.in_(jurisdiction_ids),
    ).all()
    if not rows:
        return {
            "strategy": "daily",
            "bucket_count": 0,
            "earliest": None,
            "latest": None,
            "buckets": [],
        }

    timestamps = [row.created_at for row in rows if row.created_at is not None]
    if not timestamps:
        return {
            "strategy": "daily",
            "bucket_count": 0,
            "earliest": None,
            "latest": None,
            "buckets": [],
        }

    earliest_utc = _utc_date(min(timestamps))
    latest_utc = _utc_date(max(timestamps))
    span_days = (latest_utc.date() - earliest_utc.date()).days + 1

    if span_days > 31:
        strategy = "monthly"
        bucket_key = lambda ts: _utc_date(ts).strftime("%Y-%m")
        bucket_start = lambda key: _parse_month_start(key)
    else:
        strategy = "daily"
        bucket_key = lambda ts: _utc_date(ts).date().isoformat()
        bucket_start = lambda key: _parse_day_start(key)

    aggregate = {}
    for row in rows:
        if row.created_at is None:
            continue
        key = bucket_key(row.created_at)
        bucket = aggregate.setdefault(key, {
            "total": 0,
            "verified_or_corrected": 0,
            "pending_or_needs_review": 0,
            "ai_supported_only": 0,
            "other": 0,
        })
        bucket["total"] += 1
        if row.verification_status in {"CONFIRMED", "CORRECTED"}:
            bucket["verified_or_corrected"] += 1
        elif row.verification_status in {"PENDING", "NEEDS_MORE_REVIEW"}:
            bucket["pending_or_needs_review"] += 1
        else:
            bucket["other"] += 1

    ai_only_counts = db.query(
        Observation.created_at,
    ).filter(
        Observation.jurisdiction_id.in_(jurisdiction_ids),
        Observation.verification_status == "PENDING",
        Observation.identification_status == "accepted",
    ).all()
    for row in ai_only_counts:
        if row.created_at is None:
            continue
        key = bucket_key(row.created_at)
        bucket = aggregate.setdefault(key, {
            "total": 0,
            "verified_or_corrected": 0,
            "pending_or_needs_review": 0,
            "ai_supported_only": 0,
            "other": 0,
        })
        bucket["ai_supported_only"] += 1

    bucket_keys_sorted = sorted(aggregate.keys())
    buckets = []
    for key in bucket_keys_sorted:
        payload = aggregate[key]
        buckets.append({
            "bucket": key,
            "start": bucket_start(key).isoformat(),
            "total": payload["total"],
            "verified_or_corrected": payload["verified_or_corrected"],
            "pending_or_needs_review": payload["pending_or_needs_review"],
            "ai_supported_only": payload["ai_supported_only"],
            "other": payload["other"],
        })

    return {
        "strategy": strategy,
        "bucket_count": len(buckets),
        "earliest": earliest_utc.isoformat(),
        "latest": latest_utc.isoformat(),
        "buckets": buckets,
    }


def _parse_day_start(value):
    from datetime import date, datetime, time
    parsed = date.fromisoformat(value)
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def _parse_month_start(value):
    from datetime import datetime
    return datetime.strptime(f"{value}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _build_regional_analytics_payload(db, region):
    """Build a comprehensive operational analytics payload for the region.

    Aggregates operational evidence only. No suitability scores, no
    Monitoring Priority scores, and no jurisdictional predictive values are
    combined across jurisdictions.
    """
    region_jurisdictions = list(region.jurisdictions)
    jurisdiction_ids = [item.id for item in region_jurisdictions]
    jurisdiction_meta_by_id = {
        item.id: {
            "id": item.id,
            "name": item.name,
            "slug": item.slug,
            "country_code": item.country_code,
            "status": item.status,
        }
        for item in region_jurisdictions
    }

    observations_by_verification = {}
    observation_total = 0
    if jurisdiction_ids:
        rows = db.query(
            Observation.jurisdiction_id,
            Observation.verification_status,
            func.count(Observation.id),
        ).filter(
            Observation.jurisdiction_id.in_(jurisdiction_ids),
        ).group_by(
            Observation.jurisdiction_id, Observation.verification_status,
        ).all()
        for jurisdiction_id, verification_status, count in rows:
            observation_total += count
            bucket = observations_by_verification.setdefault(jurisdiction_id, {
                "total": 0,
                "confirmed": 0,
                "corrected": 0,
                "pending": 0,
                "needs_more_review": 0,
            })
            bucket["total"] += count
            if verification_status == "CONFIRMED":
                bucket["confirmed"] += count
            elif verification_status == "CORRECTED":
                bucket["corrected"] += count
            elif verification_status == "PENDING":
                bucket["pending"] += count
            elif verification_status == "NEEDS_MORE_REVIEW":
                bucket["needs_more_review"] += count

    regional_verification = {
        "total": observation_total,
        "confirmed": sum(item["confirmed"] for item in observations_by_verification.values()),
        "corrected": sum(item["corrected"] for item in observations_by_verification.values()),
        "pending": sum(item["pending"] for item in observations_by_verification.values()),
        "needs_more_review": sum(item["needs_more_review"] for item in observations_by_verification.values()),
    }
    regional_verification["pending_review"] = regional_verification["pending"] + regional_verification["needs_more_review"]

    investigation_states = {
        "total": 0,
        "planned": 0,
        "in_progress": 0,
        "completed": 0,
        "cancelled": 0,
        "active": 0,
    }
    investigations_by_jurisdiction = {}
    if jurisdiction_ids:
        rows = db.query(
            Investigation.jurisdiction_id,
            Investigation.status,
            func.count(Investigation.id),
        ).filter(
            Investigation.jurisdiction_id.in_(jurisdiction_ids),
        ).group_by(
            Investigation.jurisdiction_id, Investigation.status,
        ).all()
        for jurisdiction_id, status, count in rows:
            investigations_by_jurisdiction.setdefault(jurisdiction_id, {
                "total": 0, "planned": 0, "in_progress": 0, "completed": 0, "cancelled": 0, "active": 0,
            })
            investigations_by_jurisdiction[jurisdiction_id]["total"] += count
            key = (status or "").lower()
            if key in investigations_by_jurisdiction[jurisdiction_id]:
                investigations_by_jurisdiction[jurisdiction_id][key] += count
            if key in {"planned", "in_progress"}:
                investigations_by_jurisdiction[jurisdiction_id]["active"] += count
            if key in investigation_states:
                investigation_states[key] += count
            investigation_states["total"] += count
            if key in {"planned", "in_progress"}:
                investigation_states["active"] += count

    field_visit_states = {
        "total": 0,
        "draft": 0,
        "submitted": 0,
    }
    field_detection_states = {
        "total": 0,
        "detected": 0,
        "not_detected": 0,
        "inconclusive": 0,
    }
    field_visits_by_jurisdiction = {}
    if jurisdiction_ids:
        status_rows = db.query(
            FieldVisit.jurisdiction_id,
            FieldVisit.status,
            func.count(FieldVisit.id),
        ).filter(
            FieldVisit.jurisdiction_id.in_(jurisdiction_ids),
        ).group_by(
            FieldVisit.jurisdiction_id, FieldVisit.status,
        ).all()
        for jurisdiction_id, status, count in status_rows:
            bucket = field_visits_by_jurisdiction.setdefault(jurisdiction_id, {
                "total": 0,
                "draft": 0,
                "submitted": 0,
                "detected": 0,
                "not_detected": 0,
                "inconclusive": 0,
            })
            bucket["total"] += count
            field_visit_states["total"] += count
            key = (status or "").lower()
            if key in bucket:
                bucket[key] += count
            if key in field_visit_states:
                field_visit_states[key] += count

        detection_rows = db.query(
            FieldVisit.jurisdiction_id,
            FieldVisit.target_detection_status,
            func.count(FieldVisit.id),
        ).filter(
            FieldVisit.jurisdiction_id.in_(jurisdiction_ids),
        ).group_by(
            FieldVisit.jurisdiction_id, FieldVisit.target_detection_status,
        ).all()
        for jurisdiction_id, detection_status, count in detection_rows:
            bucket = field_visits_by_jurisdiction.setdefault(jurisdiction_id, {
                "total": 0,
                "draft": 0,
                "submitted": 0,
                "detected": 0,
                "not_detected": 0,
                "inconclusive": 0,
            })
            key = (detection_status or "").lower()
            if key in bucket:
                bucket[key] += count
            if key in field_detection_states:
                field_detection_states[key] += count
            if key != "":
                field_detection_states["total"] += count

    boundary_by_jurisdiction = {}
    if jurisdiction_ids:
        boundary_rows = db.query(
            JurisdictionBoundary.jurisdiction_id,
        ).filter(
            JurisdictionBoundary.jurisdiction_id.in_(jurisdiction_ids),
            JurisdictionBoundary.status == "ACTIVE",
            JurisdictionBoundary.boundary_type == "MARINE_MONITORING",
        ).distinct().all()
        for (jurisdiction_id,) in boundary_rows:
            boundary_by_jurisdiction[jurisdiction_id] = True

    program_by_jurisdiction = {}
    if jurisdiction_ids:
        program_rows = db.query(
            SpeciesProgram.jurisdiction_id,
        ).filter(
            SpeciesProgram.jurisdiction_id.in_(jurisdiction_ids),
            SpeciesProgram.status == "ACTIVE",
        ).distinct().all()
        for (jurisdiction_id,) in program_rows:
            program_by_jurisdiction[jurisdiction_id] = True

    suitability_jurisdiction_ids = set()
    monitoring_priority_jurisdiction_ids = set()
    if jurisdiction_ids:
        deployment_rows = db.query(
            SuitabilityDeployment.id,
            SpeciesProgram.jurisdiction_id,
        ).join(
            SpeciesProgram, SpeciesProgram.id == SuitabilityDeployment.species_program_id
        ).filter(
            SuitabilityDeployment.status == "ACTIVE",
            SpeciesProgram.jurisdiction_id.in_(jurisdiction_ids),
        ).all()
        deployment_ids = [row[0] for row in deployment_rows]
        suitability_jurisdiction_ids = {row[1] for row in deployment_rows}
        if deployment_ids:
            priority_rows = db.query(
                NextAreaSnapshotGeneration.suitability_deployment_id,
                SpeciesProgram.jurisdiction_id,
            ).join(
                SpeciesProgram, SpeciesProgram.id == NextAreaSnapshotGeneration.species_program_id
            ).filter(
                NextAreaSnapshotGeneration.id.in_(
                    db.query(NextAreaSnapshotGeneration.id).filter(
                        NextAreaSnapshotGeneration.suitability_deployment_id.in_(deployment_ids),
                        NextAreaSnapshotGeneration.status == "ACTIVE",
                        NextAreaSnapshotGeneration.is_active.is_(True),
                    )
                ),
            ).all()
            for _, jurisdiction_id in priority_rows:
                monitoring_priority_jurisdiction_ids.add(jurisdiction_id)

    organization_jurisdiction_ids = set()
    manager_jurisdiction_ids = set()
    if jurisdiction_ids:
        org_rows = db.query(
            OrganizationJurisdiction.jurisdiction_id,
        ).filter(
            OrganizationJurisdiction.jurisdiction_id.in_(jurisdiction_ids),
            OrganizationJurisdiction.status == "ACTIVE",
            OrganizationJurisdiction.organization.has(status="ACTIVE"),
        ).distinct().all()
        organization_jurisdiction_ids = {row[0] for row in org_rows}
        if organization_jurisdiction_ids:
            manager_rows = db.query(
                OrganizationJurisdiction.jurisdiction_id,
            ).join(
                OrganizationMembership, OrganizationMembership.organization_id == OrganizationJurisdiction.organization_id,
            ).filter(
                OrganizationJurisdiction.jurisdiction_id.in_(organization_jurisdiction_ids),
                OrganizationJurisdiction.status == "ACTIVE",
                OrganizationMembership.status == "ACTIVE",
                OrganizationMembership.role == "MANAGER",
                OrganizationMembership.user.has(status="ACTIVE"),
            ).distinct().all()
            manager_jurisdiction_ids = {row[0] for row in manager_rows}

    operational_coverage = {
        "configured_jurisdictions": len(jurisdiction_ids),
        "jurisdictions_with_boundaries": len(boundary_by_jurisdiction),
        "jurisdictions_with_organizations": len(organization_jurisdiction_ids),
        "jurisdictions_with_managers": len(manager_jurisdiction_ids),
        "jurisdictions_with_species_programs": len(program_by_jurisdiction),
        "jurisdictions_with_suitability": len(suitability_jurisdiction_ids),
        "jurisdictions_with_monitoring_priority": len(monitoring_priority_jurisdiction_ids),
    }

    species_payload = _build_species_intelligence(db, region_jurisdictions)
    canonical_species = species_payload["canonical_species"]
    unresolved_evidence = species_payload["unresolved_evidence"]

    regional_species_list = sorted(
        (
            {
                "scientific_name": item["scientific_name"],
                "common_name": item["common_name"],
                "total_observations": item["evidence"]["total"],
                "verified_or_corrected": item["evidence"]["verified_or_corrected"],
                "ai_supported": item["evidence"]["ai_supported"],
                "jurisdictions_with_evidence": item["jurisdictions_with_evidence"],
            }
            for item in canonical_species
        ),
        key=lambda item: (-item["total_observations"], item["scientific_name"]),
    )

    jurisdictions_payload = []
    for jurisdiction in region_jurisdictions:
        jurisdiction_id = jurisdiction.id
        observations_breakdown = observations_by_verification.get(jurisdiction_id, {
            "total": 0, "confirmed": 0, "corrected": 0, "pending": 0, "needs_more_review": 0,
        })
        review_workload = {
            "pending": observations_breakdown["pending"],
            "needs_more_review": observations_breakdown["needs_more_review"],
            "total": observations_breakdown["pending"] + observations_breakdown["needs_more_review"],
        }
        jurisdiction_species_payload = _build_species_intelligence(db, [jurisdiction])
        jurisdiction_canonical = jurisdiction_species_payload["canonical_species"]
        jurisdiction_unresolved = jurisdiction_species_payload["unresolved_evidence"]
        jurisdiction_species_list = sorted(
            (
                {
                    "scientific_name": item["scientific_name"],
                    "common_name": item["common_name"],
                    "total_observations": item["evidence"]["total"],
                    "verified_or_corrected": item["evidence"]["verified_or_corrected"],
                    "ai_supported": item["evidence"]["ai_supported"],
                }
                for item in jurisdiction_canonical
            ),
            key=lambda item: (-item["total_observations"], item["scientific_name"]),
        )
        jurisdictions_payload.append({
            "jurisdiction": jurisdiction_meta_by_id[jurisdiction_id],
            "operational_boundary_configured": boundary_by_jurisdiction.get(jurisdiction_id, False),
            "participating_organizations": organization_jurisdiction_ids.__contains__(jurisdiction_id),
            "jurisdiction_managers": manager_jurisdiction_ids.__contains__(jurisdiction_id),
            "scientific_programs_configured": program_by_jurisdiction.get(jurisdiction_id, False),
            "habitat_suitability": "Available" if jurisdiction_id in suitability_jurisdiction_ids else "Not configured",
            "monitoring_priority": "Available" if jurisdiction_id in monitoring_priority_jurisdiction_ids else "Not configured",
            "observations": observations_breakdown,
            "review_queue": review_workload,
            "investigations": investigations_by_jurisdiction.get(jurisdiction_id, {
                "total": 0, "planned": 0, "in_progress": 0, "completed": 0, "cancelled": 0, "active": 0,
            }),
            "field_visits": field_visits_by_jurisdiction.get(jurisdiction_id, {
                "total": 0, "draft": 0, "submitted": 0,
                "detected": 0, "not_detected": 0, "inconclusive": 0,
            }),
            "species_evidence": {
                "count": len(jurisdiction_species_list),
                "species": jurisdiction_species_list,
                "unresolved_evidence_count": len(jurisdiction_unresolved),
                "unresolved_evidence": jurisdiction_unresolved,
            },
        })

    activity_payload = _build_regional_activity_buckets(db, region_jurisdictions, jurisdiction_meta_by_id)

    return {
        "region": {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status},
        "observations": regional_verification,
        "activity": {
            "observation_buckets": activity_payload,
            "note": "Platform reporting activity over time. Not a species population trend.",
        },
        "species_evidence": {
            "count": len(regional_species_list),
            "species": regional_species_list,
            "unresolved_evidence_count": len(unresolved_evidence),
            "unresolved_evidence": unresolved_evidence,
            "note": "Canonical species identities anchored on the Species table. Not an abundance estimate.",
        },
        "jurisdictions": jurisdictions_payload,
        "investigations": investigation_states,
        "field_activity": {
            **field_visit_states,
            "detection_outcomes": {
                "total": field_detection_states["total"],
                "detected": field_detection_states["detected"],
                "not_detected": field_detection_states["not_detected"],
                "inconclusive": field_detection_states["inconclusive"],
            },
            "non_detection_interpretation": "A non-detection records the result of this survey effort and must not be interpreted as confirmed species absence.",
        },
        "operational_coverage": operational_coverage,
        "review_workload": {
            "pending": regional_verification["pending"],
            "needs_more_review": regional_verification["needs_more_review"],
            "total": regional_verification["pending_review"],
            "by_jurisdiction": [
                {
                    "jurisdiction": jurisdiction_meta_by_id[item["jurisdiction_id"]]["slug"],
                    "jurisdiction_name": jurisdiction_meta_by_id[item["jurisdiction_id"]]["name"],
                    "pending": item["pending"],
                    "needs_more_review": item["needs_more_review"],
                    "total": item["pending"] + item["needs_more_review"],
                }
                for item in [
                    {
                        "jurisdiction_id": jurisdiction["jurisdiction"]["id"],
                        "pending": jurisdiction["review_queue"]["pending"],
                        "needs_more_review": jurisdiction["review_queue"]["needs_more_review"],
                    }
                    for jurisdiction in jurisdictions_payload
                ]
            ],
        },
        "note": "Operational evidence aggregated regionally. Predictive scientific values (suitability, Monitoring Priority) are not combined across jurisdictions.",
    }


@app.get("/regions/{region_slug}/analytics")
def get_region_analytics(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    if region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region is not active.")
    return _build_regional_analytics_payload(db, region)


def _jurisdiction_capabilities(item: Jurisdiction):
    boundary_ready = any(
        boundary.status == "ACTIVE" and boundary.boundary_type == "MARINE_MONITORING"
        for boundary in item.boundaries
    )
    operational = item.status == "ACTIVE" and item.region.status == "ACTIVE" and boundary_ready
    active_programs = [program for program in item.species_programs if program.status == "ACTIVE"]
    active_deployments = [deployment for program in active_programs for deployment in program.suitability_deployments if deployment.status == "ACTIVE"]
    active_priority = any(
        generation.status == "ACTIVE" and generation.is_active
        for deployment in active_deployments
        for generation in deployment.priority_generations
    )
    return {
        "operational_boundary": boundary_ready,
        "public_submissions": operational,
        "observations": operational,
        "review": operational,
        "investigations": operational,
        "field_visits": operational,
        "habitat_suitability": bool(active_deployments),
        "monitoring_priority": active_priority,
    }


def _jurisdiction_payload(item: Jurisdiction):
    monitoring_boundary = next((boundary for boundary in item.boundaries if boundary.status == "ACTIVE" and boundary.boundary_type == "MARINE_MONITORING"), None)
    return {
        "id": item.id, "name": item.name, "slug": item.slug,
        "country_code": item.country_code, "status": item.status,
        "center_latitude": item.center_latitude,
        "center_longitude": item.center_longitude,
        "default_zoom": item.default_zoom,
        "operational_boundary_configured": monitoring_boundary is not None,
        "capabilities": _jurisdiction_capabilities(item),
        "monitoring_boundary": None if monitoring_boundary is None else {
            "source": monitoring_boundary.source,
            "version": monitoring_boundary.source_version,
            "source_reference": monitoring_boundary.source_reference,
        },
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}")
def get_jurisdiction(region_slug: str, jurisdiction_slug: str, db: Session = Depends(get_db)):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    return {**_jurisdiction_payload(jurisdiction), "region": {"id": jurisdiction.region.id, "name": jurisdiction.region.name, "slug": jurisdiction.region.slug, "status": jurisdiction.region.status}}


def _species_program_payload(program):
    deployments = []
    for deployment in program.suitability_deployments:
        generations = sorted(deployment.priority_generations, key=lambda item: item.id)
        active_generation = next((item for item in generations if item.status == "ACTIVE" and item.is_active), None)
        deployments.append({
            "id": deployment.id,
            "model_version": deployment.model_version,
            "status": deployment.status,
            "artifact_hash": deployment.artifact_hash,
            "generated_at": deployment.generated_at,
            "activated_at": deployment.activated_at,
            "monitoring_priority": {
                "status": "AVAILABLE" if active_generation else "NOT_CONFIGURED",
                "prediction_version": active_generation.prediction_version if active_generation else None,
                "active_generation_id": active_generation.id if active_generation else None,
                "generation_count": len(generations),
            },
        })
    species = program.species
    return {
        "id": program.id,
        "jurisdiction": {"id": program.jurisdiction.id, "name": program.jurisdiction.name, "slug": program.jurisdiction.slug, "region": program.jurisdiction.region.slug},
        "scientific_name": program.scientific_name,
        "common_name": program.common_name,
        "species": {"id": species.id, "scientific_name": species.scientific_name, "common_name": species.common_name, "status": species.status} if species else None,
        "program_label": f"{program.jurisdiction.name} · {program.scientific_name} monitoring program",
        "status": program.status,
        "suitability": {"status": "AVAILABLE" if any(item["status"] == "ACTIVE" for item in deployments) else "NOT_CONFIGURED", "deployments": deployments},
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/species-programs")
def get_species_programs(region_slug: str, jurisdiction_slug: str, db: Session = Depends(get_db)):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    programs = db.query(SpeciesProgram).filter(SpeciesProgram.jurisdiction_id == jurisdiction.id).order_by(SpeciesProgram.scientific_name).all()
    return {"region": region_slug, "jurisdiction": jurisdiction_slug, "count": len(programs), "species_programs": [_species_program_payload(item) for item in programs]}


@app.get("/admin/species-programs")
def admin_species_programs(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    programs = db.query(SpeciesProgram).join(Jurisdiction).order_by(Jurisdiction.name, SpeciesProgram.scientific_name).all()
    return {"count": len(programs), "species_programs": [_species_program_payload(item) for item in programs], "editing_supported": False}


def _species_jurisdiction_status_payload(record: SpeciesJurisdictionStatus):
    return {
        "id": record.id,
        "species": {
            "id": record.species.id,
            "scientific_name": record.species.scientific_name,
            "common_name": record.species.common_name,
            "aphia_id": record.species.aphia_id,
        },
        "jurisdiction": {
            "id": record.jurisdiction.id,
            "name": record.jurisdiction.name,
            "slug": record.jurisdiction.slug,
            "country_code": record.jurisdiction.country_code,
        },
        "ecological_status": record.ecological_status,
        "source": record.source,
        "source_url": record.source_url,
        "last_reviewed_at": record.last_reviewed_at.isoformat() if record.last_reviewed_at else None,
        "notes": record.notes,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


@app.get("/admin/species-ecology")
def admin_species_ecology(db: Session = Depends(get_db), current_user: User = Depends(require_platform_admin)):
    records = (
        db.query(SpeciesJurisdictionStatus)
        .join(Species, Species.id == SpeciesJurisdictionStatus.species_id)
        .join(Jurisdiction, Jurisdiction.id == SpeciesJurisdictionStatus.jurisdiction_id)
        .order_by(Jurisdiction.name, Species.scientific_name)
        .all()
    )
    return {
        "count": len(records),
        "species_ecology": [_species_jurisdiction_status_payload(item) for item in records],
        "editing_supported": False,
    }


@app.get("/regions/{region_slug}/species-ecology")
def get_region_species_index(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None or region.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Region not found.")
    records = (
        db.query(SpeciesJurisdictionStatus)
        .join(Species, Species.id == SpeciesJurisdictionStatus.species_id)
        .join(Jurisdiction, Jurisdiction.id == SpeciesJurisdictionStatus.jurisdiction_id)
        .filter(Jurisdiction.region_id == region.id)
        .order_by(Jurisdiction.name, Species.scientific_name)
        .all()
    )
    return {
        "region": region_slug,
        "count": len(records),
        "species_ecology": [_species_jurisdiction_status_payload(item) for item in records],
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/species-ecology")
def get_jurisdiction_species_ecology(
    region_slug: str, jurisdiction_slug: str, db: Session = Depends(get_db)
):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    records = (
        db.query(SpeciesJurisdictionStatus)
        .join(Species, Species.id == SpeciesJurisdictionStatus.species_id)
        .filter(SpeciesJurisdictionStatus.jurisdiction_id == jurisdiction.id)
        .order_by(Species.scientific_name)
        .all()
    )
    return {
        "region": region_slug,
        "jurisdiction": jurisdiction_slug,
        "count": len(records),
        "species_ecology": [_species_jurisdiction_status_payload(item) for item in records],
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/boundary")
def get_jurisdiction_boundary(region_slug: str, jurisdiction_slug: str, db: Session = Depends(get_db)):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    boundary = next((item for item in jurisdiction.boundaries if item.status == "ACTIVE" and item.boundary_type == "MARINE_MONITORING"), None)
    if boundary is None:
        raise HTTPException(status_code=404, detail="Operational monitoring assignment boundary not configured.")
    return {
        "type": "Feature",
        "geometry": json.loads(boundary.geometry_json),
        "properties": {
            "label": "Operational monitoring assignment boundary",
            "region": jurisdiction.region.slug,
            "jurisdiction": jurisdiction.slug,
            "source": boundary.source,
            "source_version": boundary.source_version,
            "source_reference": boundary.source_reference,
            "geometry_hash": boundary.geometry_hash,
            "notice": "Used for platform monitoring assignment; not an independent legal determination of maritime limits.",
        },
    }


def _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, product, model_version=None, prediction_version=None):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="Both region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    programs = db.query(SpeciesProgram).filter(
        SpeciesProgram.jurisdiction_id == jurisdiction.id,
        SpeciesProgram.scientific_name == scientific_name,
        SpeciesProgram.status == "ACTIVE",
    ).all()
    deployments = [
        deployment for program in programs for deployment in program.suitability_deployments
        if deployment.status == "ACTIVE" and (model_version is None or deployment.model_version == model_version)
    ]
    if product == "habitat suitability":
        if len(deployments) != 1:
            raise HTTPException(status_code=404, detail=f"Habitat Suitability deployment is not configured for {jurisdiction.name}.")
        return programs[0], deployments[0], None
    generations = [
        generation for deployment in deployments for generation in deployment.priority_generations
        if generation.status == "ACTIVE" and generation.is_active
        and (prediction_version is None or generation.prediction_version == prediction_version)
    ]
    if len(generations) != 1:
        raise HTTPException(status_code=404, detail=f"Monitoring Priority deployment is not configured for {jurisdiction.name}.")
    return generations[0].species_program, generations[0].suitability_deployment, generations[0]


def _organization_payload(organization: Organization, include_jurisdictions=True):
    payload = {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "organization_type": organization.organization_type,
        "status": organization.status,
    }
    if include_jurisdictions:
        payload["jurisdictions"] = [
            {
                "relationship_id": link.id,
                "id": link.jurisdiction.id,
                "name": link.jurisdiction.name,
                "slug": link.jurisdiction.slug,
                "country_code": link.jurisdiction.country_code,
                "region": link.jurisdiction.region.slug,
                "relationship_status": link.status,
            }
            for link in organization.jurisdiction_links
        ]
    return payload


@app.get("/organizations")
def get_organizations(db: Session = Depends(get_db)):
    organizations = db.query(Organization).order_by(Organization.name).all()
    return {
        "count": len(organizations),
        "organizations": [_organization_payload(item) for item in organizations],
    }


@app.get("/organizations/{organization_slug}")
def get_organization(organization_slug: str, db: Session = Depends(get_db)):
    organization = db.query(Organization).filter(
        func.lower(Organization.slug) == organization_slug.lower()
    ).first()
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return _organization_payload(organization)


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/organizations")
def get_jurisdiction_organizations(
    region_slug: str,
    jurisdiction_slug: str,
    db: Session = Depends(get_db),
):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    organizations = (
        db.query(Organization)
        .join(OrganizationJurisdiction)
        .filter(OrganizationJurisdiction.jurisdiction_id == jurisdiction.id)
        .order_by(Organization.name)
        .all()
    )
    return {
        "region": jurisdiction.region.slug,
        "jurisdiction": jurisdiction.slug,
        "count": len(organizations),
        "organizations": [_organization_payload(item) for item in organizations],
    }


INVESTIGATION_STATUSES = {"PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
INVESTIGATION_PRIORITIES = {"LOW", "MODERATE", "HIGH", "URGENT"}
INVESTIGATION_SOURCES = {"MONITORING_PRIORITY", "OBSERVATION", "MANUAL"}
INVESTIGATION_TRANSITIONS = {
    "PLANNED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def _participating_organization(db, organization_id, jurisdiction_id):
    organization = (
        db.query(Organization)
        .join(OrganizationJurisdiction)
        .filter(
            Organization.id == organization_id,
            Organization.status == "ACTIVE",
            OrganizationJurisdiction.jurisdiction_id == jurisdiction_id,
            OrganizationJurisdiction.status == "ACTIVE",
        )
        .first()
    )
    if organization is None:
        raise HTTPException(status_code=400, detail="Assigned organization does not participate in this jurisdiction.")
    return organization


def _investigation_payload(item):
    observation = item.source_observation
    return {
        "id": item.id,
        "title": item.title,
        "objective": item.objective,
        "status": item.status,
        "priority": item.priority,
        "latitude": item.latitude,
        "longitude": item.longitude,
        "outcome_summary": item.outcome_summary,
        "jurisdiction": {
            "id": item.jurisdiction.id, "name": item.jurisdiction.name,
            "slug": item.jurisdiction.slug, "region": item.jurisdiction.region.slug,
        },
        "assigned_organization": {
            "id": item.assigned_organization.id,
            "name": item.assigned_organization.name,
            "slug": item.assigned_organization.slug,
        },
        "created_by": {
            "id": item.created_by_user.id,
            "display_name": item.created_by_user.display_name,
        },
        "source": {
            "type": item.source_type,
            "observation_id": item.source_observation_id,
            "observation_at_creation": None if item.source_observation_id is None else {
                "species": item.source_observation_species,
                "verification_status": item.source_observation_verification_status,
                "submitted_at": item.source_observation_created_at,
            },
            "observation": None if observation is None else {
                "id": observation.id,
                "species": observation.verified_species or observation.species,
                "verification_status": observation.verification_status,
                "created_at": observation.created_at,
                "latitude": observation.latitude,
                "longitude": observation.longitude,
            },
            "generation_id": item.source_prediction_generation_id,
            "prediction_version": item.source_prediction_version,
            "cell_id": item.source_prediction_cell_id,
            "priority_score": item.source_priority_score,
            "priority_band": item.source_priority_band,
            "generated_at": item.source_generated_at,
        },
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "cancelled_at": item.cancelled_at,
    }


@app.get("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/investigations")
def list_investigations(
    region_slug: str,
    jurisdiction_slug: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    organization_id: Optional[int] = None,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    require_roles(db, current_user, jurisdiction.id, {"VIEWER", "REVIEWER", "MANAGER"})
    query = db.query(Investigation).filter(Investigation.jurisdiction_id == jurisdiction.id)
    if status:
        query = query.filter(Investigation.status == status.upper())
    if priority:
        query = query.filter(Investigation.priority == priority.upper())
    if organization_id:
        query = query.filter(Investigation.assigned_organization_id == organization_id)
    if source_type:
        query = query.filter(Investigation.source_type == source_type.upper())
    items = query.order_by(Investigation.created_at.desc(), Investigation.id.desc()).all()
    return {"count": len(items), "investigations": [_investigation_payload(item) for item in items]}


@app.post("/regions/{region_slug}/jurisdictions/{jurisdiction_slug}/investigations")
def create_investigation(
    region_slug: str,
    jurisdiction_slug: str,
    payload: InvestigationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
    require_roles(db, current_user, jurisdiction.id, {"MANAGER"})
    source_type, priority = payload.source_type.upper(), payload.priority.upper()
    if source_type not in INVESTIGATION_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid investigation source type.")
    if priority not in INVESTIGATION_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid investigation priority.")
    if not payload.title.strip() or not payload.objective.strip():
        raise HTTPException(status_code=400, detail="Title and objective are required.")
    _participating_organization(db, payload.assigned_organization_id, jurisdiction.id)

    latitude, longitude = payload.latitude, payload.longitude
    source_values = {}
    if source_type == "OBSERVATION":
        observation = db.query(Observation).filter(Observation.id == payload.source_observation_id).first()
        if observation is None or observation.jurisdiction_id != jurisdiction.id:
            raise HTTPException(status_code=400, detail="Source observation does not belong to this jurisdiction.")
        latitude, longitude = observation.latitude, observation.longitude
        source_values.update({
            "source_observation_id": observation.id,
            "source_observation_species": observation.verified_species or observation.species,
            "source_observation_verification_status": observation.verification_status,
            "source_observation_created_at": observation.created_at,
        })
    elif source_type == "MONITORING_PRIORITY":
        program_query = db.query(SpeciesProgram).filter(
            SpeciesProgram.jurisdiction_id == jurisdiction.id,
            SpeciesProgram.status == "ACTIVE",
        )
        program_for_generation = None
        if payload.source_prediction_generation_id is not None:
            generation_match = db.query(NextAreaSnapshotGeneration).filter(
                NextAreaSnapshotGeneration.id == payload.source_prediction_generation_id,
            ).first()
            if generation_match is not None:
                candidate = (
                    db.query(SpeciesProgram)
                    .filter(SpeciesProgram.id == generation_match.species_program_id)
                    .first()
                )
                if candidate is not None and candidate.jurisdiction_id == jurisdiction.id:
                    program_for_generation = candidate
                    generation = generation_match
                else:
                    generation = None
            else:
                generation = None
        else:
            generation = None
        cell = None if generation is None else db.query(NextAreaSnapshotCell).filter(
            NextAreaSnapshotCell.generation_id == generation.id,
            NextAreaSnapshotCell.grid_cell_id == payload.source_prediction_cell_id,
        ).first()
        if program_for_generation is None or generation is None or cell is None or not generation.is_active or generation.status != "ACTIVE":
            raise HTTPException(status_code=400, detail=f"Monitoring Priority deployment is not configured for {jurisdiction.name}.")
        _ = program_query
        latitude, longitude = cell.latitude, cell.longitude
        source_values.update({
            "source_prediction_generation_id": generation.id,
            "source_prediction_cell_id": cell.grid_cell_id,
            "source_prediction_version": generation.prediction_version,
            "source_priority_score": cell.monitoring_priority_score,
            "source_priority_band": cell.priority_band,
            "source_generated_at": generation.generated_at,
        })
    elif any((payload.source_observation_id, payload.source_prediction_generation_id, payload.source_prediction_cell_id)):
        raise HTTPException(status_code=400, detail="Manual investigations cannot reference observation or prediction sources.")

    if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise HTTPException(status_code=400, detail="Valid target latitude and longitude are required.")
    item = Investigation(
        jurisdiction_id=jurisdiction.id,
        title=payload.title.strip(), objective=payload.objective.strip(),
        status="PLANNED", priority=priority,
        assigned_organization_id=payload.assigned_organization_id,
        created_by_user_id=current_user.id,
        latitude=latitude, longitude=longitude,
        source_type=source_type, **source_values,
    )
    db.add(item); db.commit(); db.refresh(item)
    return _investigation_payload(item)


def _authorized_investigation(db, investigation_id, current_user, manage=False):
    item = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    require_roles(db, current_user, item.jurisdiction_id, {"MANAGER"} if manage else {"VIEWER", "REVIEWER", "MANAGER"})
    return item


@app.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    return _investigation_payload(_authorized_investigation(db, investigation_id, current_user))


@app.patch("/investigations/{investigation_id}")
def update_investigation(investigation_id: int, payload: InvestigationUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    item = _authorized_investigation(db, investigation_id, current_user, manage=True)
    if payload.priority is not None:
        priority = payload.priority.upper()
        if priority not in INVESTIGATION_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid investigation priority.")
        item.priority = priority
    if payload.assigned_organization_id is not None:
        _participating_organization(db, payload.assigned_organization_id, item.jurisdiction_id)
        item.assigned_organization_id = payload.assigned_organization_id
    if payload.title is not None:
        if not payload.title.strip(): raise HTTPException(status_code=400, detail="Title cannot be empty.")
        item.title = payload.title.strip()
    if payload.objective is not None:
        if not payload.objective.strip(): raise HTTPException(status_code=400, detail="Objective cannot be empty.")
        item.objective = payload.objective.strip()
    if payload.outcome_summary is not None:
        item.outcome_summary = payload.outcome_summary.strip() or None
    db.commit(); db.refresh(item)
    return _investigation_payload(item)


@app.post("/investigations/{investigation_id}/status")
def change_investigation_status(investigation_id: int, payload: InvestigationStatusRequest, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    item = _authorized_investigation(db, investigation_id, current_user, manage=True)
    target = payload.status.upper()
    if target not in INVESTIGATION_STATUSES or target not in INVESTIGATION_TRANSITIONS[item.status]:
        raise HTTPException(status_code=400, detail=f"Invalid investigation transition: {item.status} to {target}.")
    now = datetime.now(timezone.utc)
    item.status = target
    if target == "IN_PROGRESS": item.started_at = now
    elif target == "COMPLETED":
        item.completed_at = now
        if payload.outcome_summary is not None: item.outcome_summary = payload.outcome_summary.strip() or None
    elif target == "CANCELLED": item.cancelled_at = now
    db.commit(); db.refresh(item)
    return _investigation_payload(item)


FIELD_VISIT_STATUSES = {"DRAFT", "SUBMITTED"}
FIELD_DETECTION_STATUSES = {"DETECTED", "NOT_DETECTED", "INCONCLUSIVE"}
FIELD_SURVEY_METHODS = {"VISUAL_SURVEY", "DIVE_SURVEY", "SNORKEL_SURVEY", "SHORE_OBSERVATION", "TRAP_OR_CAPTURE", "OTHER"}


def _field_observation_payload(item):
    return {
        "id": item.id, "field_visit_id": item.field_visit_id,
        "scientific_name": item.scientific_name, "count_observed": item.count_observed,
        "latitude": item.latitude, "longitude": item.longitude,
        "notes": item.notes, "created_at": item.created_at,
    }


def _field_visit_payload(item):
    return {
        "id": item.id, "investigation_id": item.investigation_id,
        "status": item.status, "visited_at": item.visited_at,
        "latitude": item.latitude, "longitude": item.longitude,
        "survey_method": item.survey_method,
        "effort_duration_minutes": item.effort_duration_minutes,
        "area_description": item.area_description,
        "conditions_notes": item.conditions_notes,
        "target_detection_status": item.target_detection_status,
        "notes": item.notes, "submitted_at": item.submitted_at,
        "created_at": item.created_at, "updated_at": item.updated_at,
        "organization": {"id": item.organization.id, "name": item.organization.name, "slug": item.organization.slug},
        "recorded_by": {"id": item.recorded_by_user.id, "display_name": item.recorded_by_user.display_name},
        "observation_count": len(item.observations),
        "observations": [_field_observation_payload(observation) for observation in item.observations],
        "non_detection_interpretation": "A non-detection records the result of this survey effort and should not be interpreted as confirmed species absence." if item.target_detection_status == "NOT_DETECTED" else None,
    }


def _validate_field_location(db, jurisdiction_id, latitude, longitude):
    try:
        resolution = jurisdiction_resolution_service.resolve(db, latitude, longitude)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if resolution.get("status") != "RESOLVED" or resolution.get("jurisdiction_id") != jurisdiction_id:
        raise HTTPException(status_code=400, detail="Field location is outside the investigation jurisdiction's configured monitoring boundary.")


def _validate_field_values(detection_status, survey_method, effort_minutes):
    if detection_status not in FIELD_DETECTION_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid target detection status. Use DETECTED, NOT_DETECTED, or INCONCLUSIVE.")
    if survey_method not in FIELD_SURVEY_METHODS:
        raise HTTPException(status_code=400, detail="Invalid survey method.")
    if effort_minutes is None or effort_minutes < 0:
        raise HTTPException(status_code=400, detail="Effort duration must be zero or greater.")


def _authorized_field_visit(db, field_visit_id, current_user, manage=False):
    item = db.query(FieldVisit).filter(FieldVisit.id == field_visit_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Field visit not found.")
    require_roles(db, current_user, item.jurisdiction_id, {"MANAGER"} if manage else {"VIEWER", "REVIEWER", "MANAGER"})
    return item


@app.get("/investigations/{investigation_id}/field-visits")
def list_field_visits(investigation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    investigation = _authorized_investigation(db, investigation_id, current_user)
    items = db.query(FieldVisit).filter(FieldVisit.investigation_id == investigation.id).order_by(FieldVisit.visited_at.desc(), FieldVisit.id.desc()).all()
    return {"count": len(items), "field_visits": [_field_visit_payload(item) for item in items]}


@app.post("/investigations/{investigation_id}/field-visits")
def create_field_visit(investigation_id: int, payload: FieldVisitWriteRequest, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    investigation = _authorized_investigation(db, investigation_id, current_user, manage=True)
    if investigation.status not in {"PLANNED", "IN_PROGRESS"}:
        raise HTTPException(status_code=400, detail="New field visits are allowed only for planned or in-progress investigations.")
    status = payload.status.upper()
    if status not in FIELD_VISIT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid field visit status.")
    organization_id = payload.organization_id or investigation.assigned_organization_id
    _participating_organization(db, organization_id, investigation.jurisdiction_id)
    detection, method = payload.target_detection_status.upper(), payload.survey_method.upper()
    _validate_field_values(detection, method, payload.effort_duration_minutes)
    _validate_field_location(db, investigation.jurisdiction_id, payload.latitude, payload.longitude)
    now = datetime.now(timezone.utc)
    item = FieldVisit(
        investigation_id=investigation.id, jurisdiction_id=investigation.jurisdiction_id,
        organization_id=organization_id, recorded_by_user_id=current_user.id,
        status=status, submitted_at=now if status == "SUBMITTED" else None,
        visited_at=payload.visited_at, latitude=payload.latitude, longitude=payload.longitude,
        survey_method=method, effort_duration_minutes=payload.effort_duration_minutes,
        area_description=payload.area_description, conditions_notes=payload.conditions_notes,
        target_detection_status=detection, notes=payload.notes,
    )
    db.add(item); db.commit(); db.refresh(item)
    return _field_visit_payload(item)


@app.get("/field-visits/{field_visit_id}")
def get_field_visit(field_visit_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    return _field_visit_payload(_authorized_field_visit(db, field_visit_id, current_user))


@app.patch("/field-visits/{field_visit_id}")
def update_field_visit(field_visit_id: int, payload: FieldVisitUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    item = _authorized_field_visit(db, field_visit_id, current_user, manage=True)
    if item.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Submitted field visits are read-only.")
    values = payload.model_dump(exclude_unset=True)
    if "organization_id" in values:
        _participating_organization(db, values["organization_id"], item.jurisdiction_id)
    latitude, longitude = values.get("latitude", item.latitude), values.get("longitude", item.longitude)
    _validate_field_location(db, item.jurisdiction_id, latitude, longitude)
    detection = values.get("target_detection_status", item.target_detection_status).upper()
    method = values.get("survey_method", item.survey_method).upper()
    effort = values.get("effort_duration_minutes", item.effort_duration_minutes)
    _validate_field_values(detection, method, effort)
    values.update({"target_detection_status": detection, "survey_method": method})
    for key, value in values.items(): setattr(item, key, value)
    db.commit(); db.refresh(item)
    return _field_visit_payload(item)


@app.post("/field-visits/{field_visit_id}/submit")
def submit_field_visit(field_visit_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    item = _authorized_field_visit(db, field_visit_id, current_user, manage=True)
    if item.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Only draft field visits can be submitted.")
    item.status, item.submitted_at = "SUBMITTED", datetime.now(timezone.utc)
    db.commit(); db.refresh(item)
    return _field_visit_payload(item)


@app.get("/field-visits/{field_visit_id}/observations")
def list_field_observations(field_visit_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    item = _authorized_field_visit(db, field_visit_id, current_user)
    return {"count": len(item.observations), "field_observations": [_field_observation_payload(observation) for observation in item.observations]}


@app.post("/field-visits/{field_visit_id}/observations")
def create_field_observation(field_visit_id: int, payload: FieldObservationRequest, db: Session = Depends(get_db), current_user: User = Depends(require_authenticated_user)):
    visit = _authorized_field_visit(db, field_visit_id, current_user, manage=True)
    if visit.status != "DRAFT":
        raise HTTPException(status_code=400, detail="Field observations can be added only while the visit is a draft.")
    if not payload.scientific_name.strip():
        raise HTTPException(status_code=400, detail="Scientific name is required.")
    if payload.count_observed is not None and payload.count_observed < 1:
        raise HTTPException(status_code=400, detail="Count observed must be positive when supplied.")
    if (payload.latitude is None) != (payload.longitude is None):
        raise HTTPException(status_code=400, detail="Observation latitude and longitude must be supplied together.")
    if payload.latitude is not None:
        _validate_field_location(db, visit.jurisdiction_id, payload.latitude, payload.longitude)
    item = FieldObservation(field_visit_id=visit.id, scientific_name=payload.scientific_name.strip(), count_observed=payload.count_observed, latitude=payload.latitude, longitude=payload.longitude, notes=payload.notes)
    db.add(item); db.commit(); db.refresh(item)
    return _field_observation_payload(item)


@app.get(
    "/predictions/training/species/{scientific_name}/summary"
)
def get_prediction_training_summary(
    scientific_name: str,
    db: Session = Depends(get_db),
):
    species_filter = (
        func.lower(PredictionTrainingOccurrence.scientific_name)
        == scientific_name.lower()
    )
    occurrences = db.query(PredictionTrainingOccurrence).filter(
        species_filter
    ).all()
    total = len(occurrences)
    dates = sorted(
        occurrence.event_date for occurrence in occurrences
        if occurrence.event_date is not None
    )
    locations = {
        (round(occurrence.latitude, 6), round(occurrence.longitude, 6))
        for occurrence in occurrences
    }
    from math import floor
    from collections import Counter
    from statistics import median
    cells = Counter(
        (
            floor(occurrence.latitude / TRAINING_GRID_SIZE) * TRAINING_GRID_SIZE,
            floor(occurrence.longitude / TRAINING_GRID_SIZE) * TRAINING_GRID_SIZE,
        )
        for occurrence in occurrences
    )
    strongest_cell, strongest_count = (
        cells.most_common(1)[0] if cells else (None, 0)
    )
    features = db.query(PredictionTrainingEnvironmentalFeature).join(
        PredictionTrainingOccurrence,
        PredictionTrainingOccurrence.id
        == PredictionTrainingEnvironmentalFeature.prediction_training_occurrence_id,
    ).filter(species_filter).all()

    def coverage(field):
        available = sum(getattr(feature, field) is not None for feature in features)
        return {
            "available": available,
            "percent": round(available * 100 / total, 2) if total else 0.0,
        }

    complete = sum(
        feature.sst is not None
        and feature.salinity is not None
        and feature.depth is not None
        for feature in features
    )
    return {
        "species": scientific_name,
        "training_region": TRAINING_REGION_NAME,
        "prediction_region": "Jamaica",
        "total_occurrences": total,
        "dated_occurrences": len(dates),
        "unique_locations": len(locations),
        "occupied_grid_cells": len(cells),
        "median_records_per_occupied_cell": median(cells.values()) if cells else 0,
        "strongest_cell": {
            "latitude": strongest_cell[0] if strongest_cell else None,
            "longitude": strongest_cell[1] if strongest_cell else None,
            "records": strongest_count,
        },
        "environmental_coverage": {
            "sst": coverage("sst"),
            "salinity": coverage("salinity"),
            "depth": coverage("depth"),
            "complete": {
                "available": complete,
                "percent": round(complete * 100 / total, 2) if total else 0.0,
            },
        },
        "date_range": {
            "earliest": dates[0].isoformat() if dates else None,
            "latest": dates[-1].isoformat() if dates else None,
        },
    }


@app.get(
    "/predictions/training/species/{scientific_name}/model-dataset/summary"
)
def get_prediction_model_dataset_summary(
    scientific_name: str,
    db: Session = Depends(get_db),
):
    return prediction_model_dataset_service.summary(db, scientific_name)


@app.get(
    "/predictions/species/{scientific_name}/suitability/summary"
)
def get_habitat_suitability_summary(
    scientific_name: str,
    model_version: Optional[str] = None,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    _, deployment, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "habitat suitability", model_version=model_version)
    summary = habitat_suitability_service.summary(db, scientific_name, model_version or deployment.model_version, deployment.id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Suitability model not found.")
    return summary


@app.get(
    "/predictions/species/{scientific_name}/suitability/grid"
)
def get_habitat_suitability_grid(
    scientific_name: str,
    model_version: Optional[str] = None,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    _, deployment, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "habitat suitability", model_version=model_version)
    grid = habitat_suitability_service.grid(db, scientific_name, model_version or deployment.model_version, deployment.id)
    if grid is None:
        raise HTTPException(status_code=404, detail="Suitability model not found.")
    return grid


@app.get("/predictions/species/{scientific_name}/next-areas")
def get_next_area_predictions(
    scientific_name: str,
    limit: int = Query(default=20, ge=1, le=391),
    prediction_version: str = NEXT_AREA_PREDICTION_VERSION,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    program, _, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "monitoring priority", prediction_version=prediction_version)
    result = NextAreaPredictionService().recommendations(
        db, scientific_name, prediction_version, limit, species_program_id=program.id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Monitoring Priority deployment is not configured for this jurisdiction.")
    return result


@app.get("/predictions/species/{scientific_name}/next-areas/summary")
def get_next_area_prediction_summary(
    scientific_name: str,
    prediction_version: str = NEXT_AREA_PREDICTION_VERSION,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    program, _, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "monitoring priority", prediction_version=prediction_version)
    result = NextAreaPredictionService().summary(
        db, scientific_name, prediction_version, species_program_id=program.id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Monitoring Priority deployment is not configured for this jurisdiction.")
    return result


@app.get("/predictions/species/{scientific_name}/next-areas/freshness")
def get_next_area_prediction_freshness(
    scientific_name: str,
    prediction_version: str = NEXT_AREA_PREDICTION_VERSION,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required to identify the jurisdiction-specific scientific deployment.")
    program, _, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "monitoring priority", prediction_version=prediction_version)
    result = NextAreaPredictionService().freshness(
        db, scientific_name, prediction_version,
        jurisdiction_id=program.jurisdiction_id,
        species_program_id=program.id,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Monitoring-priority snapshot not found.",
        )
    return result


@app.post("/predictions/species/{scientific_name}/next-areas/regenerate")
def regenerate_next_area_predictions(
    scientific_name: str,
    prediction_version: str = NEXT_AREA_PREDICTION_VERSION,
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    if not region_slug or not jurisdiction_slug:
        raise HTTPException(status_code=400, detail="region_slug and jurisdiction_slug are required for monitoring-priority regeneration.")
    program, deployment, _ = _resolve_scientific_context(db, region_slug, jurisdiction_slug, scientific_name, "monitoring priority", prediction_version=prediction_version)
    require_roles(db, current_user, program.jurisdiction_id, {"MANAGER"})
    try:
        result = NextAreaPredictionService().regenerate(
            db, scientific_name, prediction_version,
            species_program_id=program.id,
            suitability_deployment_id=deployment.id,
            jurisdiction_id=program.jurisdiction_id,
        )
    except RegenerationInProgressError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Monitoring-priority refresh failed. "
                "The previous snapshot remains active."
            ),
        ) from error
    return {
        "message": "Monitoring priorities refreshed.",
        "generation": result,
    }

def build_image_url(filename):
    if not filename:
        return None

    return None


def _sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as image_file:
        for chunk in iter(
            lambda: image_file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _distance_meters(
    latitude_a,
    longitude_a,
    latitude_b,
    longitude_b,
):
    latitude_delta = radians(
        latitude_b - latitude_a
    )
    longitude_delta = radians(
        longitude_b - longitude_a
    )
    latitude_a = radians(latitude_a)
    latitude_b = radians(latitude_b)

    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_a)
        * cos(latitude_b)
        * sin(longitude_delta / 2) ** 2
    )

    return 6371000 * 2 * asin(
        sqrt(haversine)
    )


def _find_possible_duplicate(
    db,
    image_hash,
    species,
    latitude,
    longitude,
    submitted_at,
):
    # Prototype duplicate logic only; this is not
    # production-grade sighting identity resolution.
    identical_image = (
        db.query(Observation)
        .filter(
            Observation.image_hash == image_hash
        )
        .order_by(Observation.created_at.desc())
        .first()
    )

    if identical_image is not None:
        return identical_image

    if not species:
        return None

    recent_candidates = (
        db.query(Observation)
        .filter(
            Observation.created_at
            >= submitted_at - timedelta(hours=24)
        )
        .order_by(Observation.created_at.desc())
        .all()
    )

    for candidate in recent_candidates:
        displayed_species = (
            candidate.verified_species
            if (
                candidate.verification_status
                in {"CONFIRMED", "CORRECTED"}
                and candidate.verified_species
            )
            else candidate.species
        )

        if species not in {
            displayed_species,
            candidate.species,
        }:
            continue

        if _distance_meters(
            latitude,
            longitude,
            candidate.latitude,
            candidate.longitude,
        ) <= 250:
            return candidate

    return None
# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {"status":"alive","environment":settings.environment,"demo":settings.demo}

@app.get("/health/live")
def health_live():return {"status":"alive"}

@app.get("/health/ready")
def health_ready():
    result=readiness_report()
    if result["status"]!="ready":return JSONResponse(status_code=503,content=result)
    return result

@app.get("/admin/system/status")
def admin_system_status(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    health=readiness_report();states=dict(db.query(ScientificDomainEvent.processing_state,func.count(ScientificDomainEvent.id)).group_by(ScientificDomainEvent.processing_state).all())
    last=db.query(BackupRecord).filter_by(status="VALID").order_by(BackupRecord.created_at.desc()).first()
    return {"environment":settings.environment,"demo":settings.demo,"health":health,"migration_versions":current_versions(),"scientific_event_queue":states,"worker":{"enabled":settings.event_worker_enabled,"max_attempts":settings.max_event_attempts},"automatic_scientific_evaluation_global_gate":settings.automatic_scientific_evaluation_enabled,"model_inference":{"available":service is not None},"last_successful_backup":({"backup_identity":last.backup_identity,"created_at":last.created_at,"sha256":last.sha256,"byte_size":last.byte_size} if last else None)}

@app.post("/admin/system/events/{event_id}/process")
def admin_process_event(event_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=EventWorker(db,"manual-admin").process_one(event_id,current_user.id)
    if not row:raise HTTPException(409,"Event is not eligible for processing.")
    return {"id":row.id,"state":row.processing_state,"attempts":row.attempts,"error_category":row.error_category,"failure_reason":row.last_error}

@app.post("/admin/system/events/{event_id}/retry")
def admin_retry_event(event_id:int,db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):
    row=_require_admin_record(db,ScientificDomainEvent,event_id,"Scientific event")
    if row.processing_state not in {"RETRYABLE","FAILED"} or row.attempts>=settings.max_event_attempts:raise HTTPException(409,"Event is not eligible for retry.")
    row.processing_state="RETRYABLE";row.next_attempt_at=None;row.last_error=None;row.error_category=None;audit(db,"SCIENTIFIC_EVENT_RETRY_REQUESTED",current_user.id,"ScientificDomainEvent",row.id,row.jurisdiction_id);db.commit();return {"id":row.id,"state":row.processing_state,"attempts":row.attempts}

@app.post("/admin/system/backups")
def admin_create_backup(db:Session=Depends(get_db),current_user:User=Depends(require_platform_admin)):return create_backup(db,current_user.id)

def build_map_observations(
    db: Session,
    exclude_possible_duplicates=False,
    include_regional_evidence=False,
    region_slug=None,
    jurisdiction_slug=None,
):
    query = _scope_observation_query(
        db.query(Observation), db, region_slug, jurisdiction_slug
    )

    if exclude_possible_duplicates:
        query = query.filter(
            Observation.is_possible_duplicate.is_(False)
        )

    observations = (
        query
        .order_by(
            Observation.created_at.desc()
        )
        .all()
    )

    markers = []

    for observation in observations:

        display_species = (
            observation.verified_species
            if (
                observation.verification_status
                in {
                    "CONFIRMED",
                    "CORRECTED",
                }
                and observation.verified_species
            )
            else observation.species
        )

        marker = {
            "id":
                observation.id,

            "image_url":
                build_image_url(
                    observation.image_filename
                ),

            "latitude":
                observation.latitude,

            "longitude":
                observation.longitude,

            "location_accuracy_m": observation.location_accuracy_m,
            "location_captured_at": observation.location_captured_at,
            "location_source": observation.location_source,

            "species":
                display_species,

            "ai_species":
                observation.species,

            "identification_status":
                observation.identification_status,

            "decision":
                observation.decision,

            "priority":
                observation.priority,

            "ecological_status":
                observation.ecological_status,

            "verification_status":
                observation.verification_status,

            "score":
                observation.score,

            "created_at":
                observation.created_at,

            "region": observation.jurisdiction.region.slug if observation.jurisdiction else None,
            "jurisdiction": observation.jurisdiction.slug if observation.jurisdiction else None,
        }

        if include_regional_evidence:
            marker["regional_evidence"] = (
                json.loads(
                    observation.regional_evidence_json
                )
                if observation.regional_evidence_json
                else None
            )

        markers.append(marker)

    return markers
# ============================================================
# MAP OBSERVATIONS
# ============================================================

@app.get("/observations/map")
def get_map_observations(
    db: Session = Depends(get_db),
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
):

    markers = build_map_observations(
        db,
        region_slug=region_slug,
        jurisdiction_slug=jurisdiction_slug,
    )

    return {
        "count": len(markers),
        "markers": markers,
    }

@app.get("/analytics/hotspots")
def get_hotspots(
    db: Session = Depends(get_db),
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
):

    observations = (
        build_map_observations(
            db,
            exclude_possible_duplicates=True,
            include_regional_evidence=True,
            region_slug=region_slug,
            jurisdiction_slug=jurisdiction_slug,
        )
    )

    hotspots = (
        hotspot_service.aggregate(
            observations
        )
    )

    return {
        "count": len(hotspots),
        "grid_size":
            hotspot_service.grid_size,

        "hotspots":
            hotspots,
    }
# ============================================================
# REVIEW QUEUE
# ============================================================

@app.get("/analytics/summary")
def get_analytics_summary(
    db: Session = Depends(get_db),
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
):

    observations = (
        build_map_observations(
            db,
            exclude_possible_duplicates=True,
            include_regional_evidence=True,
            region_slug=region_slug,
            jurisdiction_slug=jurisdiction_slug,
        )
    )

    hotspots = (
        hotspot_service.aggregate(
            observations
        )
    )

    summary = (
        hotspot_service
        .monitoring_engine
        .build_summary(
            observations,
            hotspots,
        )
    )

    return summary


@app.get(
    "/analytics/historical/species/{scientific_name}"
)
def get_historical_species_summary(
    scientific_name: str,
    db: Session = Depends(get_db),
):
    species_filter = (
        func.lower(
            HistoricalOccurrence.scientific_name
        )
        == scientific_name.lower()
    )

    (
        total_records,
        dated_records,
        earliest_record,
        latest_record,
    ) = (
        db.query(
            func.count(HistoricalOccurrence.id),
            func.count(HistoricalOccurrence.event_date),
            func.min(HistoricalOccurrence.event_date),
            func.max(HistoricalOccurrence.event_date),
        )
        .filter(species_filter)
        .one()
    )

    unique_locations = (
        db.query(
            func.round(
                HistoricalOccurrence.latitude,
                3,
            ),
            func.round(
                HistoricalOccurrence.longitude,
                3,
            ),
        )
        .filter(species_filter)
        .distinct()
        .count()
    )

    return {
        "species": scientific_name,
        "total_records": total_records,
        "dated_records": dated_records,
        "earliest_record": (
            earliest_record.isoformat()
            if earliest_record else None
        ),
        "latest_record": (
            latest_record.isoformat()
            if latest_record else None
        ),
        "unique_locations": unique_locations,
    }


@app.get(
    "/analytics/historical/species/{scientific_name}/spatial"
)
def get_historical_species_spatial(
    scientific_name: str,
    db: Session = Depends(get_db),
):
    return historical_spatial_service.aggregate(
        db,
        scientific_name,
    )


@app.get(
    "/analytics/historical/species/{scientific_name}/context"
)
def get_historical_species_context(
    scientific_name: str,
    latitude: float,
    longitude: float,
    db: Session = Depends(get_db),
):
    try:
        return (
            historical_spatial_service
            .get_location_context(
                db,
                scientific_name,
                latitude,
                longitude,
            )
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@app.get(
    "/analytics/historical/species/{scientific_name}/environment"
)
def get_historical_species_environment(
    scientific_name: str,
    db: Session = Depends(get_db),
):
    species_filter = (
        func.lower(
            HistoricalOccurrence.scientific_name
        )
        == scientific_name.lower()
    )
    historical_records = (
        db.query(func.count(HistoricalOccurrence.id))
        .filter(species_filter)
        .scalar()
    )
    feature_query = (
        db.query(HistoricalEnvironmentalFeature)
        .join(
            HistoricalOccurrence,
            HistoricalOccurrence.id
            == HistoricalEnvironmentalFeature
            .historical_occurrence_id,
        )
        .filter(species_filter)
    )
    enriched_records = feature_query.count()

    (
        sst_available,
        salinity_available,
        depth_available,
        sst_min,
        sst_max,
        salinity_min,
        salinity_max,
        depth_min,
        depth_max,
    ) = (
        db.query(
            func.count(HistoricalEnvironmentalFeature.sst),
            func.count(
                HistoricalEnvironmentalFeature.salinity
            ),
            func.count(HistoricalEnvironmentalFeature.depth),
            func.min(HistoricalEnvironmentalFeature.sst),
            func.max(HistoricalEnvironmentalFeature.sst),
            func.min(
                HistoricalEnvironmentalFeature.salinity
            ),
            func.max(
                HistoricalEnvironmentalFeature.salinity
            ),
            func.min(HistoricalEnvironmentalFeature.depth),
            func.max(HistoricalEnvironmentalFeature.depth),
        )
        .join(
            HistoricalOccurrence,
            HistoricalOccurrence.id
            == HistoricalEnvironmentalFeature
            .historical_occurrence_id,
        )
        .filter(species_filter)
        .one()
    )
    complete_feature_records = feature_query.filter(
        HistoricalEnvironmentalFeature.sst.is_not(None),
        HistoricalEnvironmentalFeature.salinity.is_not(None),
        HistoricalEnvironmentalFeature.depth.is_not(None),
    ).count()

    def sampling_counts(field):
        sampling_column = getattr(
            HistoricalEnvironmentalFeature,
            f"{field}_sampling_method",
        )
        return {
            "exact": feature_query.filter(
                sampling_column == "EXACT"
            ).count(),
            "nearest_valid": feature_query.filter(
                sampling_column == "NEAREST_VALID"
            ).count(),
            "missing": feature_query.filter(
                sampling_column == "MISSING"
            ).count(),
        }

    def coverage_percent(available):
        return (
            round(available / historical_records * 100, 2)
            if historical_records else 0.0
        )

    return {
        "species": scientific_name,
        "historical_records": historical_records,
        "enriched_records": enriched_records,
        "sst_available": sst_available,
        "salinity_available": salinity_available,
        "depth_available": depth_available,
        "complete_feature_records": complete_feature_records,
        "incomplete_feature_records": (
            enriched_records - complete_feature_records
        ),
        "coverage": {
            "sst_percent": coverage_percent(
                sst_available
            ),
            "salinity_percent": coverage_percent(
                salinity_available
            ),
            "depth_percent": coverage_percent(
                depth_available
            ),
        },
        "sampling": {
            "sst": sampling_counts("sst"),
            "salinity": sampling_counts("salinity"),
            "depth": sampling_counts("depth"),
        },
        "sst_range": {
            "min": sst_min,
            "max": sst_max,
        },
        "salinity_range": {
            "min": salinity_min,
            "max": salinity_max,
        },
        "depth_range": {
            "min": depth_min,
            "max": depth_max,
        },
    }
@app.get("/observations/review-queue")
def get_review_queue(
    db: Session = Depends(get_db),
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
    current_user: User = Depends(require_authenticated_user),
):

    review_decisions = {
        "UNRESOLVED_IDENTIFICATION",
        "SPECIES_LEVEL_ANOMALY",
        "TAXONOMIC_ANOMALY",
        "HIGH_PRIORITY_REVIEW",
    }

    query = _scope_observation_query(
        db.query(Observation), db, region_slug, jurisdiction_slug
    )
    if not current_user.is_platform_admin:
        if region_slug and jurisdiction_slug:
            scoped_jurisdiction = _require_jurisdiction(db, region_slug, jurisdiction_slug)
            require_roles(db, current_user, scoped_jurisdiction.id, {"REVIEWER", "MANAGER"})
        authorized_ids = [
            item.id for item in db.query(Jurisdiction).all()
            if jurisdiction_roles(db, current_user, item.id).intersection({"REVIEWER", "MANAGER"})
        ]
        if not authorized_ids:
            raise HTTPException(status_code=403, detail="Reviewer access required.")
        query = query.filter(Observation.jurisdiction_id.in_(authorized_ids))

    observations = (
        query
        .filter(
            Observation.verification_status.in_(
                [
                    "PENDING",
                    "NEEDS_MORE_REVIEW",
                ]
            )
        )
        .order_by(
            Observation.created_at.asc()
        )
        .all()
    )

    queue = []

    for observation in observations:

        is_pending_invasive_pterois = (
            observation.ecological_status == "INVASIVE"
            and (observation.species or "").casefold()
            == "Pterois volitans".casefold()
        )

        should_review = (
            observation.decision
            in review_decisions
            or observation.priority == "HIGH"
            or is_pending_invasive_pterois
        )

        if not should_review:
            continue

        queue.append({
            "id":
                observation.id,
            "image": observation.image_filename,
            "image_url": build_image_url(observation.image_filename),

            "latitude":
                observation.latitude,

            "longitude":
                observation.longitude,

            "identification_status":
                observation.identification_status,

            "species":
                observation.species,

            "nearest_candidate":
                observation.nearest_candidate,

            "score":
                observation.score,

            "margin":
                observation.margin,

            "decision":
                observation.decision,

            "priority":
                observation.priority,

            "verification_status":
                observation.verification_status,

            "is_possible_duplicate":
                observation.is_possible_duplicate,

            "duplicate_of_observation_id":
                observation.duplicate_of_observation_id,

            "created_at":
                observation.created_at,

            "region": observation.jurisdiction.region.slug if observation.jurisdiction else None,
            "jurisdiction": observation.jurisdiction.slug if observation.jurisdiction else None,
        })

    return {
        "count": len(queue),
        "queue": queue,
    }
# ============================================================
# VERIFY OBSERVATION
# ============================================================

@app.patch("/observations/{observation_id}/verify")
def verify_observation(
    observation_id: int,
    payload: VerificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):

    observation = (
        db.query(Observation)
        .filter(
            Observation.id == observation_id
        )
        .first()
    )

    if observation is None:

        raise HTTPException(
            status_code=404,
            detail="Observation not found.",
        )

    if observation.jurisdiction_id is None:
        raise HTTPException(status_code=403, detail="Observation has no jurisdiction assignment.")
    require_roles(db, current_user, observation.jurisdiction_id, {"REVIEWER", "MANAGER"})


    allowed_statuses = {
        "CONFIRMED",
        "CORRECTED",
        "REJECTED",
        "NEEDS_MORE_REVIEW",
    }


    status = payload.status.upper()


    if status not in allowed_statuses:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid verification status. "
                f"Allowed: {sorted(allowed_statuses)}"
            ),
        )


    if (
        status in {
            "CONFIRMED",
            "CORRECTED",
        }
        and not payload.verified_species
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "verified_species is required "
                "for CONFIRMED or CORRECTED."
            ),
        )


    observation.verification_status = (
        status
    )

    observation.verified_species = (
        payload.verified_species
    )

    observation.verification_notes = (
        payload.notes
    )

    observation.verified_at = datetime.now(
        timezone.utc
    )
    observation.verified_by_user_id = current_user.id


    db.commit()

    db.refresh(
        observation
    )


    return {
        "id":
            observation.id,

        "ai_species":
            observation.species,

        "verification": {
            "status":
                observation.verification_status,

            "verified_species":
                observation.verified_species,

            "notes":
                observation.verification_notes,

            "verified_at":
                observation.verified_at,

            "verified_by_user_id":
                observation.verified_by_user_id,
        },
    }
# ============================================================
# GET ALL OBSERVATIONS
# ============================================================

@app.get("/observations")
def get_observations(
    db: Session = Depends(get_db),
    region_slug: Optional[str] = None,
    jurisdiction_slug: Optional[str] = None,
):

    observations = (
        _scope_observation_query(
            db.query(Observation), db, region_slug, jurisdiction_slug
        )
        .order_by(
            Observation.created_at.desc()
        )
        .all()
    )

    results = []

    for observation in observations:

        results.append({
            "id": observation.id,
            "image": observation.image_filename,
            "image_url": build_image_url(observation.image_filename),

            "latitude": observation.latitude,
            "longitude": observation.longitude,

            "identification": {
                "status":
                    observation.identification_status,

                "species":
                    observation.species,

                "nearest_candidate":
                    observation.nearest_candidate,

                "score":
                    observation.score,

                "margin":
                    observation.margin,
            },

            "ecological_status":
                observation.ecological_status,

            "decision":
                observation.decision,

            "priority":
                observation.priority,

            "verification_status":
                observation.verification_status,

            "verified_species":
                observation.verified_species,

            "created_at":
                observation.created_at,

            "region": observation.jurisdiction.region.slug if observation.jurisdiction else None,
            "jurisdiction": observation.jurisdiction.slug if observation.jurisdiction else None,
        })

    return {
        "count": len(results),
        "observations": results,
    }


# ============================================================
# GET ONE OBSERVATION
# ============================================================

@app.get("/observations/{observation_id}")
def get_observation(
    observation_id: int,
    db: Session = Depends(get_db),
):

    observation = (
        db.query(Observation)
        .filter(
            Observation.id
            == observation_id
        )
        .first()
    )

    if observation is None:

        raise HTTPException(
            status_code=404,
            detail="Observation not found.",
        )

    candidates = (
        json.loads(
            observation.candidates_json
        )
        if observation.candidates_json
        else []
    )

    regional_evidence = (
        json.loads(
            observation.regional_evidence_json
        )
        if observation.regional_evidence_json
        else None
    )

    return {
        "observation": {
            "id":
                observation.id,

            "image":
                observation.image_filename,

            "image_url":
                build_image_url(
                    observation.image_filename
                ),

            "latitude":
                observation.latitude,

            "longitude":
                observation.longitude,

            "created_at":
                observation.created_at,

            "location_accuracy_m": observation.location_accuracy_m,
            "location_captured_at": observation.location_captured_at,
            "location_source": observation.location_source,

            **(_geography_payload(observation.jurisdiction) if observation.jurisdiction else {"region": None, "jurisdiction": None}),
        },

        "identification": {
            "status":
                observation.identification_status,

            "species":
                observation.species,

            "nearest_candidate":
                observation.nearest_candidate,

            "score":
                observation.score,

            "margin":
                observation.margin,

            "candidates":
                candidates,
        },

        "regional_evidence":
            regional_evidence,

        "ecological_status":
            observation.ecological_status,

        "decision":
            observation.decision,

        "priority":
            observation.priority,

        "reason":
            observation.reason,

        "is_possible_duplicate":
            observation.is_possible_duplicate,

        "duplicate_of_observation_id":
            observation.duplicate_of_observation_id,

        "verification": {
            "status":
                observation.verification_status,

            "verified_species":
                observation.verified_species,

            "notes":
                observation.verification_notes,

            "verified_at":
                observation.verified_at,

            "verified_by_user_id":
                observation.verified_by_user_id,
        },
    }


def _resolve_observation_ecological_status(
    db: Session,
    identified_species,
    jurisdiction_id: int,
):
    """Resolve ecological status for a new observation.

    Phase 10B.1 invariant: the registry is authoritative. The legacy
    JAMAICA_ECOLOGICAL_STATUS dict MUST NOT be consulted here. There is
    no fallback to a global or cross-jurisdiction ecological
    dictionary.

    Order of preference:

    1. If the identified species is not registered as a canonical
       ``Species`` → ``"UNKNOWN"``.
    2. If the (Species, Jurisdiction) pair has no
       ``SpeciesJurisdictionStatus`` record → ``"UNKNOWN"``.
    3. Otherwise use the registry's ``ecological_status``.

    The caller MUST supply the registry-resolved ``ecological_status`` to
    ``AnomalyEngine.evaluate_observation``; this function does not pass
    a global ecological value to the decision engine.
    """
    if not identified_species:
        return "UNKNOWN"
    species_row = (
        db.query(Species)
        .filter(Species.scientific_name == identified_species)
        .one_or_none()
    )
    if species_row is None:
        return "UNKNOWN"
    record = get_ecological_status(db, species_row.id, jurisdiction_id)
    if record is None:
        return "UNKNOWN"
    return record.ecological_status


# ============================================================
# ANALYSE OBSERVATION
# ============================================================

@app.post("/observations/analyze")
def analyze_observation(
    request: Request,
    latitude: float = Form(...),
    longitude: float = Form(...),
    location_accuracy_m: Optional[float] = Form(default=None),
    location_captured_at: Optional[str] = Form(default=None),
    location_source: str = Form(default="MANUAL"),
    expected_jurisdiction_id: Optional[int] = Form(default=None),
    reporter_suggested_taxon_id: Optional[int] = Form(default=None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    client=request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"submission:{client}",settings.rate_limit_submission_per_minute):raise HTTPException(429,"Too many sighting submissions. Try again shortly.")

    # --------------------------------------------------------
    # VALIDATE COORDINATES
    # --------------------------------------------------------

    if not -90 <= latitude <= 90:

        raise HTTPException(
            status_code=400,
            detail="Latitude must be between -90 and 90.",
        )

    if not -180 <= longitude <= 180:

        raise HTTPException(
            status_code=400,
            detail="Longitude must be between -180 and 180.",
        )

    location_source = location_source.upper()
    if location_source not in {"DEVICE_GEOLOCATION", "MAP_SELECTED", "MANUAL", "IMPORTED"}:
        raise HTTPException(status_code=400, detail="Invalid location_source.")
    if location_accuracy_m is not None and location_accuracy_m < 0:
        raise HTTPException(status_code=400, detail="location_accuracy_m cannot be negative.")
    if location_source != "DEVICE_GEOLOCATION":
        location_accuracy_m = None
        location_captured_at = None
    parsed_location_captured_at = None
    if location_captured_at:
        try:
            parsed_location_captured_at = datetime.fromisoformat(location_captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid location_captured_at.") from error

    resolution = jurisdiction_resolution_service.resolve(db, latitude, longitude)
    if resolution["status"] != "RESOLVED":
        message = "This location is not currently covered by an active monitoring jurisdiction." if resolution["status"] == "NO_CONFIGURED_JURISDICTION" else "This location matches more than one active monitoring jurisdiction."
        raise HTTPException(status_code=422, detail={"status": resolution["status"], "message": message, "resolution": resolution})
    resolved_jurisdiction = db.query(Jurisdiction).filter(Jurisdiction.id == resolution["jurisdiction_id"]).one()
    if expected_jurisdiction_id is not None and resolved_jurisdiction.id != expected_jurisdiction_id:
        raise HTTPException(status_code=422,detail="Sighting coordinates do not match the suggested jurisdiction context.")
    suggested_taxon=None
    if reporter_suggested_taxon_id is not None:
        suggested_taxon=db.query(Species).filter_by(id=reporter_suggested_taxon_id).one_or_none()
        governed=suggested_taxon and db.query(RegionalTaxonRegistry).filter_by(region_id=resolved_jurisdiction.region_id,taxon_id=suggested_taxon.id,review_status="APPROVED").first()
        if not governed:raise HTTPException(status_code=422,detail="Suggested taxon is not governed for this monitoring region.")


    # --------------------------------------------------------
    # VALIDATE IMAGE TYPE
    # --------------------------------------------------------

    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if image.content_type not in allowed_types:

        raise HTTPException(
            status_code=400,
            detail=(
                "Image must be JPEG, PNG, or WEBP."
            ),
        )


    # --------------------------------------------------------
    # TEMPORARY IMAGE
    # --------------------------------------------------------

    suffix = Path(
        image.filename or "image.jpg"
    ).suffix.lower()

    if suffix not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }:
        suffix = ".jpg"


    file_id = uuid.uuid4().hex

    stored_filename = (
        f"{file_id}{suffix}"
    )

    stored_path = (
    UPLOAD_DIRECTORY
    / stored_filename
    )

    persisted=False
    try:
        
        total=0;header=b""
        with open(stored_path,"wb") as buffer:
            while chunk:=image.file.read(1024*1024):
                total+=len(chunk)
                if total>settings.max_upload_bytes:raise HTTPException(413,"Image exceeds the configured upload-size limit.")
                if len(header)<16:header=(header+chunk)[:16]
                buffer.write(chunk)
        valid_signature=(header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n") or (header.startswith(b"RIFF") and header[8:12]==b"WEBP"))
        if not valid_signature:raise HTTPException(400,"Uploaded content is not a valid JPEG, PNG, or WEBP image.")


        # ----------------------------------------------------
        # RUN EXISTING SERVICE
        # ----------------------------------------------------

        result = service.analyze(
            image_path=stored_path,
            latitude=latitude,
            longitude=longitude,
            jurisdiction_id=resolved_jurisdiction.id,
            db=db,
        )
        # ============================================================
# SAVE OBSERVATION
# ============================================================

        identification = result[
         "identification"
        ]

        regional_evidence = result.get(
         "regional_evidence"
        )

        image_hash = _sha256_file(
            stored_path
        )
        submitted_at = datetime.now(
            timezone.utc
        )
        possible_duplicate = (
            _find_possible_duplicate(
                db=db,
                image_hash=image_hash,
                species=identification.get(
                    "species"
                ),
                latitude=latitude,
                longitude=longitude,
                submitted_at=submitted_at,
            )
        )


        observation_record = Observation(
            jurisdiction_id=resolved_jurisdiction.id,
            reporter_suggested_taxon_id=suggested_taxon.id if suggested_taxon else None,
            reporter_suggested_scientific_name=suggested_taxon.scientific_name if suggested_taxon else None,
            image_filename=(
                stored_filename
            ),

        image_hash=image_hash,

        is_possible_duplicate=(
                possible_duplicate is not None
        ),

        duplicate_of_observation_id=(
                possible_duplicate.id
                if possible_duplicate is not None
                else None
        ),

        latitude=latitude,
        longitude=longitude,
        location_accuracy_m=location_accuracy_m,
        location_captured_at=parsed_location_captured_at,
        location_source=location_source,

        identification_status=(
                identification[
                        "status"
                ]
        ),

        species=(
                identification.get(
                        "species"
                )
        ),

        nearest_candidate=(
                identification.get(
                        "nearest_candidate"
                )
        ),

        score=(
                identification.get(
                        "score"
                )
        ),

        margin=(
                identification.get(
                        "margin"
                )
        ),

        candidates_json=json.dumps(
                identification.get(
                        "candidates",
                        []
                )
        ),

        regional_evidence_json=(
                json.dumps(
                        regional_evidence
                )
                if regional_evidence
                is not None
                else None
        ),

        ecological_status=_resolve_observation_ecological_status(
            db=db,
            identified_species=identification.get("species"),
            jurisdiction_id=resolved_jurisdiction.id,
        ),

        decision=(
                result[
                        "decision"
                ]
        ),

        priority=(
                result[
                        "priority"
                ]
        ),

        reason=(
                result.get(
                        "reason"
                )
        ),

        verification_status="PENDING",
        created_at=submitted_at,
        )


        db.add(
        observation_record
        )

        db.commit()

        db.refresh(
        observation_record
        )
                # Don't expose our server's temporary path.

        result["observation"]["image"] = (
                       stored_filename
                )
        result["observation"][
          "id"
        ] = observation_record.id
        result["observation"].update(_geography_payload(resolved_jurisdiction))
        result["observation"]["location_accuracy_m"] = location_accuracy_m
        result["observation"]["location_captured_at"] = parsed_location_captured_at
        result["observation"]["location_source"] = location_source
        result["observation"]["reporter_suggested_taxon_id"] = observation_record.reporter_suggested_taxon_id
        result["observation"]["reporter_suggested_scientific_name"] = observation_record.reporter_suggested_scientific_name
        result["jurisdiction_resolution"] = resolution
        result["observation"]["image"] = (
    stored_filename
    )

        result["observation"]["image_url"] = None
        status_token,raw_status_token=ReporterAccessService(db).issue(observation_record.id,"STATUS")
        db.commit()
        persisted=True
        result["submission_reference"]=status_token.public_reference
        result["reporter_status_token"]=raw_status_token
        result["reporter_status_url"]=f"/reporter/status/{raw_status_token}"
        result["submission_message"]="Report received. AI-assisted identification is preliminary and may be reviewed by an authorized jurisdiction team."
        result["is_possible_duplicate"] = (
            observation_record.is_possible_duplicate
        )
        result["duplicate_of_observation_id"] = (
            observation_record.duplicate_of_observation_id
        )
        return result


    except HTTPException:
        raise


    except Exception as error:

        print(
            "Observation analysis failed:",
            repr(error),
        )

        raise HTTPException(
            status_code=500,
            detail="Observation analysis failed.",
        )


    finally:

        image.file.close()
        if not persisted and stored_path.exists():stored_path.unlink()
        
