from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from models import AuthSession, Jurisdiction, OrganizationJurisdiction, OrganizationMembership, Region, User


SESSION_LIFETIME = timedelta(hours=12)
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(derived.hex(), expected)
    except (TypeError, ValueError):
        return False


def create_session(db: Session, user: User):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
    )
    user.last_login_at = now
    db.add(session)
    db.commit()
    return token


def _token_session(db, credentials):
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None)).first()
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return session if expires_at > datetime.now(timezone.utc) else None


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
):
    session = _token_session(db, credentials)
    if session is None or session.user.status != "ACTIVE":
        raise HTTPException(status_code=401, detail="Authentication required.", headers={"WWW-Authenticate": "Bearer"})
    return session.user


def require_platform_admin(user: User = Depends(require_authenticated_user)):
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required.")
    return user


def revoke_session(db: Session, credentials: HTTPAuthorizationCredentials):
    session = _token_session(db, credentials)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()


def jurisdiction_roles(db: Session, user: User, jurisdiction_id: int):
    if user.is_platform_admin:
        return {"PLATFORM_ADMIN"}
    rows = (
        db.query(OrganizationMembership.role)
        .join(OrganizationMembership.organization)
        .join(OrganizationJurisdiction, OrganizationJurisdiction.organization_id == OrganizationMembership.organization_id)
        .join(Jurisdiction, Jurisdiction.id == OrganizationJurisdiction.jurisdiction_id)
        .join(Region, Region.id == Jurisdiction.region_id)
        .filter(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == "ACTIVE",
            OrganizationMembership.organization.has(status="ACTIVE"),
            OrganizationJurisdiction.status == "ACTIVE",
            Jurisdiction.status == "ACTIVE",
            Region.status == "ACTIVE",
            Jurisdiction.id == jurisdiction_id,
        )
        .all()
    )
    return {row[0] for row in rows}


def require_roles(db: Session, user: User, jurisdiction_id: int, allowed_roles):
    if not jurisdiction_roles(db, user, jurisdiction_id).intersection(allowed_roles | {"PLATFORM_ADMIN"}):
        raise HTTPException(status_code=403, detail="Insufficient jurisdiction access.")
    return user


def user_payload(db: Session, user: User):
    memberships = []
    authorized = {}
    for membership in user.memberships:
        organization = membership.organization
        memberships.append({
            "id": membership.id,
            "organization": {"id": organization.id, "name": organization.name, "slug": organization.slug},
            "role": membership.role,
            "status": membership.status,
        })
        if membership.status == "ACTIVE" and organization.status == "ACTIVE":
            for link in organization.jurisdiction_links:
                if link.status == "ACTIVE" and link.jurisdiction.status == "ACTIVE" and link.jurisdiction.region.status == "ACTIVE":
                    authorized[link.jurisdiction.id] = {
                        "id": link.jurisdiction.id,
                        "name": link.jurisdiction.name,
                        "slug": link.jurisdiction.slug,
                        "region": link.jurisdiction.region.slug,
                        "roles": sorted(set(authorized.get(link.jurisdiction.id, {}).get("roles", [])) | {membership.role}),
                    }
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "status": user.status,
        "is_platform_admin": user.is_platform_admin,
        "last_login_at": user.last_login_at,
        "memberships": memberships,
        "authorized_jurisdictions": list(authorized.values()),
    }
