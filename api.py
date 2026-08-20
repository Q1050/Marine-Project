from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
from math import asin, cos, radians, sin, sqrt
import shutil
import tempfile
import uuid
import json
from pydantic import BaseModel
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
    require_roles,
    revoke_session,
    user_payload,
    verify_password,
)

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.staticfiles import StaticFiles

from marine_observation_service import MarineObservationService
from jurisdiction_resolution_service import JurisdictionResolutionService

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


class AdminUserUpdateRequest(BaseModel):
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
UPLOAD_DIRECTORY = Path(
    "uploads/observations"
)

UPLOAD_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
)

app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads",
)
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
def login(payload: LoginRequest, db: Session = Depends(get_db)):
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
    item = User(email=email, display_name=payload.display_name.strip(), password_hash=password_hash, status=_admin_status(payload.status), is_platform_admin=False); db.add(item); db.commit(); db.refresh(item); return user_payload(db, item)


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
    return {"count": len(regions), "regions": [{"id": item.id, "name": item.name, "slug": item.slug, "status": item.status} for item in regions]}


@app.get("/regions/{region_slug}")
def get_region(region_slug: str, db: Session = Depends(get_db)):
    region = db.query(Region).filter(func.lower(Region.slug) == region_slug.lower()).first()
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found.")
    return {"id": region.id, "name": region.name, "slug": region.slug, "status": region.status}


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

    return (
        f"/uploads/observations/{filename}"
    )


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

    return {
        "status": "ok",
        "device": str(service.device),
    }

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
    latitude: float = Form(...),
    longitude: float = Form(...),
    location_accuracy_m: Optional[float] = Form(default=None),
    location_captured_at: Optional[str] = Form(default=None),
    location_source: str = Form(default="MANUAL"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):

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

    try:
        
        with open(
            stored_path,
            "wb"
        ) as buffer:

            shutil.copyfileobj(
                image.file,
                buffer,
            )


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
        result["jurisdiction_resolution"] = resolution
        result["observation"]["image"] = (
    stored_filename
    )

        result["observation"]["image_url"] = (
    f"/uploads/observations/"
    f"{stored_filename}"
    )
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
        
