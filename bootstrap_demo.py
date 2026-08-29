"""Create/reset an isolated, visibly synthetic demonstration database."""
import argparse
from pathlib import Path
from auth_service import hash_password
from database import Base, SessionLocal, engine
from models import Jurisdiction, Observation, ObservationReviewerGrant, Region, Species, User
from platform_config import settings
from sqlalchemy import text
from sqlalchemy.engine import make_url

def main():
    p=argparse.ArgumentParser();p.add_argument("--reset",action="store_true");p.add_argument("--confirm",action="store_true");p.add_argument("--password",default="Demonstration-Only-Change-Me");a=p.parse_args()
    if not settings.demo:raise SystemExit("Refused: APP_ENV must be DEMO.")
    url=make_url(settings.database_url);db_path=Path(url.database) if url.get_backend_name()=="sqlite" else None
    if db_path and db_path.resolve()==Path("marine_observations.db").resolve():raise SystemExit("Refused: DEMO may not use the production database path.")
    if url.get_backend_name()=="postgresql" and "demo" not in (url.database or "").lower():raise SystemExit("Refused: PostgreSQL demo database name must contain 'demo'.")
    if a.reset:
        if not a.confirm:raise SystemExit("Demo reset requires --confirm.")
        engine.dispose()
        if db_path:db_path.unlink(missing_ok=True)
        else:
            with engine.begin() as connection:connection.execute(text("DROP SCHEMA public CASCADE"));connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        region=db.query(Region).filter_by(slug="demonstration-region").one_or_none() or Region(name="DEMONSTRATION REGION",slug="demonstration-region",status="ACTIVE")
        db.add(region);db.flush();jurisdiction=db.query(Jurisdiction).filter_by(slug="demo-island").one_or_none() or Jurisdiction(region_id=region.id,name="DEMONSTRATION ISLAND",slug="demo-island",country_code="DX",status="ACTIVE",center_latitude=18,center_longitude=-77,default_zoom=8)
        db.add(jurisdiction);db.flush();taxon=db.query(Species).filter_by(scientific_name="Demonstration taxon").one_or_none() or Species(scientific_name="Demonstration taxon",common_name="Synthetic demo species",status="ACTIVE")
        db.add(taxon);db.flush();user=db.query(User).filter_by(email="reviewer@demo.invalid").one_or_none() or User(email="reviewer@demo.invalid",display_name="Demo Reviewer",password_hash=hash_password(a.password),status="ACTIVE",is_platform_admin=True,organization_name="DEMONSTRATION ONLY")
        db.add(user);db.flush()
        if not db.query(Observation).filter_by(jurisdiction_id=jurisdiction.id).first():db.add(Observation(jurisdiction_id=jurisdiction.id,image_filename="demo-placeholder-not-private-media.jpg",latitude=18,longitude=-77,identification_status="UNCERTAIN",species=None,candidates_json="[]",ecological_status="UNKNOWN",decision="REVIEW",priority="NORMAL",reason="DEMONSTRATION DATA",verification_status="PENDING"))
        db.commit();print({"environment":"DEMO","database_backend":url.get_backend_name(),"warning":"DEMONSTRATION DATA — NOT OFFICIAL SCIENCE"})
if __name__=="__main__":main()
