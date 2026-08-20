import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from jurisdiction_boundary_ingestion import activate_jamaica_boundary
from jurisdiction_resolution_service import JurisdictionResolutionService
from models import Jurisdiction, JurisdictionBoundary, Observation, Region


def source_file(path):
    feature = {
        "type": "Feature", "properties": {"mrgid": 8459, "iso_ter1": "JAM", "pol_type": "200NM"},
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[-78, 17], [-76, 17], [-76, 19], [-78, 19], [-78, 17]]]]},
    }
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    return path


def test_jamaica_activation_is_valid_provenanced_and_idempotent(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
        db.add(region); db.flush()
        jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1, center_longitude=-77.3, default_zoom=8)
        db.add(jamaica); db.commit()
        before_observations = db.query(Observation).count()
        boundary, inserted, _ = activate_jamaica_boundary(db, source_file(tmp_path / "source.geojson"))
        same_boundary, inserted_again, _ = activate_jamaica_boundary(db, tmp_path / "source.geojson")
        assert inserted is True and inserted_again is False
        assert same_boundary.id == boundary.id
        assert boundary.source == "Marine Regions / VLIZ"
        assert boundary.source_version and boundary.source_reference and boundary.geometry_hash
        assert db.query(JurisdictionBoundary).filter_by(status="ACTIVE", boundary_type="MARINE_MONITORING").count() == 1
        resolver = JurisdictionResolutionService()
        assert resolver.resolve(db, 18, -77)["jurisdiction"]["slug"] == "jamaica"
        assert resolver.resolve(db, 25, -77)["status"] == "NO_CONFIGURED_JURISDICTION"
        assert db.query(Observation).count() == before_observations
    engine.dispose()
