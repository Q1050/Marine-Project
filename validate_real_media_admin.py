"""Controlled authenticated read/negative-action validation for Milestone 17B."""
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from api import app
from auth_service import create_session
from database import SessionLocal
from models import AuthSession, User

def validate():
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(is_platform_admin=True, status="ACTIVE").order_by(User.id).first()
        token = create_session(db, admin)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        sources = client.get("/admin/identification-corpus/media-sources", headers=headers)
        assets = client.get("/admin/identification-corpus/assets", headers=headers)
        items = assets.json()["items"]
        eligible = next(item for item in items if item["content_url"])
        anonymous = client.get(eligible["content_url"])
        authorized = client.get(eligible["content_url"], headers=headers)
        restrictive = next(item for item in items if item["license_classification"] == "NONCOMMERCIAL_RESTRICTION")
        blocked = client.post(
            f"/admin/identification-corpus/assets/{restrictive['id']}/review",
            headers=headers,
            json={"decision": "APPROVED", "reference": "closure-negative-test"},
        )
        return {
            "sources_status": sources.status_code,
            "assets_status": assets.status_code,
            "asset_count": len(items),
            "anonymous_thumbnail_status": anonymous.status_code,
            "authorized_thumbnail_status": authorized.status_code,
            "authorized_thumbnail_type": authorized.headers.get("content-type"),
            "authorized_thumbnail_bytes": len(authorized.content),
            "restrictive_approval_status": blocked.status_code,
            "source_fields_visible": all(
                key in sources.json()["items"][0]
                for key in ("licensing_model", "attribution_requirements", "limitations")
            ),
        }
    finally:
        session = db.query(AuthSession).filter_by(user_id=admin.id, revoked_at=None).order_by(AuthSession.id.desc()).first()
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
        db.close()

if __name__ == "__main__":
    print(validate())
