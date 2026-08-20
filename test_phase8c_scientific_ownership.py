from datetime import datetime, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import init_db
from database import Base
from models import (
    HabitatSuitabilityModel,
    HabitatSuitabilityV3GridCell,
    Jurisdiction,
    NextAreaSnapshotGeneration,
    Observation,
    Region,
    SpeciesProgram,
    SuitabilityDeployment,
)
from next_area_prediction_service import NextAreaPredictionService


def scientific_fixture(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase8c.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        region = Region(name="Caribbean", slug="caribbean", status="ACTIVE")
        db.add(region); db.flush()
        jamaica = Jurisdiction(region_id=region.id, name="Jamaica", slug="jamaica", country_code="JM", status="ACTIVE", center_latitude=18, center_longitude=-77, default_zoom=8)
        bahamas = Jurisdiction(region_id=region.id, name="Bahamas", slug="bahamas", country_code="BS", status="ACTIVE", center_latitude=24, center_longitude=-76, default_zoom=6)
        db.add_all([jamaica, bahamas]); db.flush()
        model = HabitatSuitabilityModel(model_version="pterois-volitans-suitability-v3", scientific_name="Pterois volitans", algorithm="fixture", feature_list_json="[]", training_generation_version="fixture", training_sample_count=1, eligible_presence_count=1, eligible_background_count=0, spatial_block_count=1, validation_metrics_json="{}", coefficients_json="{}", artifact_path="missing-fixture.joblib", trained_at=datetime.now(timezone.utc))
        db.add(model); db.flush()
        db.add(HabitatSuitabilityV3GridCell(scientific_name="Pterois volitans", model_version=model.model_version, grid_cell_id="180:-770", latitude=18.05, longitude=-76.95, grid_size=.1, suitability_score=.73, suitability_band="HIGH", prediction_status="SCORED", feature_values_json="{}", missing_features_json="[]", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        db.add(NextAreaSnapshotGeneration(scientific_name="Pterois volitans", prediction_version="pterois-volitans-next-area-v1", suitability_model_version=model.model_version, status="ACTIVE", is_active=True, diagnostics_json="{}", evidence_state_json="[]", started_at=datetime(2026, 1, 2, tzinfo=timezone.utc), generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc), completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
        db.commit()
    monkeypatch.setattr(init_db, "engine", engine)
    return engine, Session


def test_scientific_ownership_migration_is_idempotent(tmp_path, monkeypatch):
    engine, Session = scientific_fixture(tmp_path, monkeypatch)
    try:
        init_db.initialize_database()
        init_db.initialize_database()
        with Session() as db:
            programs = db.query(SpeciesProgram).all()
            deployments = db.query(SuitabilityDeployment).all()
            assert [(item.jurisdiction.slug, item.scientific_name) for item in programs] == [("jamaica", "Pterois volitans")]
            assert len(deployments) == 1
            assert deployments[0].model_version == "pterois-volitans-suitability-v3"
            assert db.query(HabitatSuitabilityV3GridCell).one().suitability_deployment_id == deployments[0].id
            generation = db.query(NextAreaSnapshotGeneration).one()
            assert generation.species_program_id == programs[0].id
            assert generation.suitability_deployment_id == deployments[0].id
            assert generation.status == "ACTIVE" and generation.is_active is True
            assert db.query(SpeciesProgram).join(Jurisdiction).filter(Jurisdiction.slug == "bahamas").count() == 0
    finally:
        engine.dispose()


def test_bahamas_observation_does_not_stale_jamaica_generation(tmp_path, monkeypatch):
    engine, Session = scientific_fixture(tmp_path, monkeypatch)
    try:
        init_db.initialize_database()
        with Session() as db:
            jamaica = db.query(Jurisdiction).filter_by(slug="jamaica").one()
            bahamas = db.query(Jurisdiction).filter_by(slug="bahamas").one()
            program = db.query(SpeciesProgram).filter_by(jurisdiction_id=jamaica.id).one()
            db.add(Observation(jurisdiction_id=bahamas.id, image_filename="bahamas.jpg", latitude=25, longitude=-77, identification_status="accepted", species="Pterois volitans", ecological_status="INVASIVE", decision="KNOWN_INVASIVE_RECORD", priority="HIGH", verification_status="PENDING", created_at=datetime(2026, 1, 3, tzinfo=timezone.utc)))
            db.commit()
            result = NextAreaPredictionService().freshness(db, "Pterois volitans", now=datetime(2026, 1, 3, tzinfo=timezone.utc), jurisdiction_id=jamaica.id, species_program_id=program.id)
            assert result["status"] == "FRESH"
            assert result["relevant_changes_since_generation"] == 0
    finally:
        engine.dispose()
