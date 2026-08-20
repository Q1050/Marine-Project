from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from jurisdiction_boundary_ingestion import (
    BAHAMAS_MRGID,
    activate_bahamas_boundary,
    load_bahamas_geometry,
)
from jurisdiction_resolution_service import JurisdictionResolutionService
from models import Jurisdiction, JurisdictionBoundary, Region


SOURCE = Path(__file__).parent / "data" / "jurisdiction_boundaries" / "marine-regions-v12-bahamas-wfs-source.geojson"


def environment(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bahamas.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
    db.add(region); db.flush()
    db.add_all([
        Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18.1096, center_longitude=-77.2975, default_zoom=8),
        Jurisdiction(region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS", status="ACTIVE", center_latitude=24.25, center_longitude=-76.0, default_zoom=6),
    ])
    db.commit()
    return db, engine


def test_bahamas_source_is_primary_valid_epsg4326_geometry():
    geometry, properties = load_bahamas_geometry(SOURCE)
    assert properties["mrgid"] == BAHAMAS_MRGID
    assert properties["iso_ter1"] == "BHS"
    assert properties["pol_type"] == "200NM"
    assert properties["territory2"] is None
    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid and geometry.area > 0
    assert geometry.bounds == (-81.23147808, 20.37354444, -70.51048642, 30.3723937)


def test_bahamas_activation_is_idempotent_and_resolves_coordinate(tmp_path):
    db, engine = environment(tmp_path)
    try:
        first, inserted, _ = activate_bahamas_boundary(db, SOURCE)
        second, inserted_again, _ = activate_bahamas_boundary(db, SOURCE)
        assert inserted is True
        assert inserted_again is False
        assert first.id == second.id
        assert db.query(JurisdictionBoundary).count() == 1
        result = JurisdictionResolutionService().resolve(db, 25.0, -77.0)
        assert result["status"] == "RESOLVED"
        assert result["jurisdiction"]["slug"] == "bahamas"
        assert JurisdictionResolutionService().resolve(db, 0, 0)["status"] == "NO_CONFIGURED_JURISDICTION"
    finally:
        db.close(); engine.dispose()
