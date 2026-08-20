import hashlib
from pathlib import Path

from sqlalchemy import inspect, text

from database import Base, engine
import models


def initialize_database():

    Base.metadata.create_all(
        bind=engine
    )

    # Snapshot-history storage is additive. The legacy next-area tables are
    # intentionally retained unchanged, and their current snapshot is copied
    # once to become the first active history entry.
    with engine.begin() as connection:
        # Seed only the real operational geography. Display-only planned
        # jurisdictions remain frontend configuration until they are onboarded.
        connection.execute(text(
            "INSERT OR IGNORE INTO regions "
            "(name, slug, status, created_at, updated_at) VALUES "
            "('Caribbean', 'caribbean', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT OR IGNORE INTO jurisdictions "
            "(region_id, name, slug, country_code, status, center_latitude, "
            "center_longitude, default_zoom, created_at, updated_at) "
            "SELECT id, 'Jamaica', 'jamaica', 'JM', 'ACTIVE', 18.1096, -77.2975, 8, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM regions WHERE slug = 'caribbean'"
        ))
        connection.execute(text(
            "INSERT OR IGNORE INTO jurisdictions "
            "(region_id, name, slug, country_code, status, center_latitude, "
            "center_longitude, default_zoom, created_at, updated_at) "
            "SELECT id, 'Bahamas', 'bahamas', 'BS', 'ACTIVE', 24.25, -76.0, 6, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM regions WHERE slug = 'caribbean'"
        ))

        connection.execute(text(
            "INSERT INTO next_area_snapshot_generations ("
            "scientific_name, prediction_version, suitability_model_version, "
            "status, is_active, diagnostics_json, evidence_state_json, "
            "started_at, generated_at, completed_at) "
            "SELECT scientific_name, prediction_version, suitability_model_version, "
            "'ACTIVE', 1, diagnostics_json, NULL, "
            "generated_at, generated_at, generated_at "
            "FROM next_area_prediction_generations legacy "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM next_area_snapshot_generations history "
            "WHERE history.scientific_name = legacy.scientific_name "
            "AND history.prediction_version = legacy.prediction_version)"
        ))
        connection.execute(text(
            "INSERT INTO next_area_snapshot_cells ("
            "generation_id, scientific_name, prediction_version, grid_cell_id, "
            "latitude, longitude, suitability_score, "
            "distance_from_nearest_current_evidence_km, observation_evidence_score, "
            "recent_activity_score, current_evidence_score, monitoring_priority_score, "
            "priority_band, source_observation_ids_json, evidence_json, "
            "reason_codes_json, generated_at) "
            "SELECT history.id, legacy.scientific_name, legacy.prediction_version, "
            "legacy.grid_cell_id, legacy.latitude, legacy.longitude, "
            "legacy.suitability_score, legacy.distance_from_nearest_current_evidence_km, "
            "legacy.observation_evidence_score, legacy.recent_activity_score, "
            "legacy.current_evidence_score, legacy.monitoring_priority_score, "
            "legacy.priority_band, legacy.source_observation_ids_json, "
            "legacy.evidence_json, legacy.reason_codes_json, legacy.generated_at "
            "FROM next_area_prediction_cells legacy "
            "JOIN next_area_snapshot_generations history "
            "ON history.scientific_name = legacy.scientific_name "
            "AND history.prediction_version = legacy.prediction_version "
            "AND history.is_active = 1 "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM next_area_snapshot_cells cells "
            "WHERE cells.generation_id = history.id)"
        ))

    existing_columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "observations"
        )
    }

    # Keep existing prototype databases compatible with
    # the duplicate-detection fields added to the model.
    migrations = {
        "jurisdiction_id": (
            "ALTER TABLE observations "
            "ADD COLUMN jurisdiction_id INTEGER "
            "REFERENCES jurisdictions(id)"
        ),
        "image_hash": (
            "ALTER TABLE observations "
            "ADD COLUMN image_hash VARCHAR(64)"
        ),
        "is_possible_duplicate": (
            "ALTER TABLE observations "
            "ADD COLUMN is_possible_duplicate BOOLEAN "
            "NOT NULL DEFAULT 0"
        ),
        "duplicate_of_observation_id": (
            "ALTER TABLE observations "
            "ADD COLUMN duplicate_of_observation_id INTEGER"
        ),
        "verified_at": (
            "ALTER TABLE observations "
            "ADD COLUMN verified_at DATETIME"
        ),
        "verified_by_user_id": (
            "ALTER TABLE observations "
            "ADD COLUMN verified_by_user_id INTEGER "
            "REFERENCES users(id)"
        ),
        "location_accuracy_m": (
            "ALTER TABLE observations ADD COLUMN location_accuracy_m FLOAT"
        ),
        "location_captured_at": (
            "ALTER TABLE observations ADD COLUMN location_captured_at DATETIME"
        ),
        "location_source": (
            "ALTER TABLE observations ADD COLUMN location_source VARCHAR"
        ),
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))

        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_observations_image_hash "
            "ON observations (image_hash)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_observations_jurisdiction_id "
            "ON observations (jurisdiction_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_observations_verified_by_user_id "
            "ON observations (verified_by_user_id)"
        ))
        connection.execute(text(
            "UPDATE observations SET jurisdiction_id = ("
            "SELECT jurisdictions.id FROM jurisdictions "
            "JOIN regions ON regions.id = jurisdictions.region_id "
            "WHERE regions.slug = 'caribbean' AND jurisdictions.slug = 'jamaica'"
            ") WHERE jurisdiction_id IS NULL"
        ))

    scientific_ownership_columns = {
        "habitat_suitability_grid_cells": "suitability_deployment_id INTEGER REFERENCES suitability_deployments(id)",
        "habitat_suitability_v3_grid_cells": "suitability_deployment_id INTEGER REFERENCES suitability_deployments(id)",
        "next_area_prediction_generations": "species_program_id INTEGER REFERENCES species_programs(id)",
        "next_area_snapshot_generations": "species_program_id INTEGER REFERENCES species_programs(id)",
    }
    species_program_columns = {
        column["name"] for column in inspect(engine).get_columns("species_programs")
    } if inspect(engine).has_table("species_programs") else set()

    if "species_id" not in species_program_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE species_programs ADD COLUMN species_id INTEGER REFERENCES species(id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_species_programs_species_id ON species_programs (species_id)"
            ))

    species_columns_now = {
        column["name"] for column in inspect(engine).get_columns("species")
    } if inspect(engine).has_table("species") else set()
    if "aphia_id" not in species_columns_now:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE species ADD COLUMN aphia_id INTEGER"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_species_aphia_id ON species (aphia_id) WHERE aphia_id IS NOT NULL"
            ))

    if not inspect(engine).has_table("species_jurisdiction_status"):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE species_jurisdiction_status ("
                "id INTEGER PRIMARY KEY, "
                "species_id INTEGER NOT NULL REFERENCES species(id), "
                "jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id), "
                "ecological_status VARCHAR(16) NOT NULL, "
                "source VARCHAR(64) NOT NULL, "
                "source_url VARCHAR(512), "
                "last_reviewed_at DATETIME, "
                "notes TEXT, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "CONSTRAINT uq_species_jurisdiction_status UNIQUE (species_id, jurisdiction_id)"
                ")"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_species_jurisdiction_status_species_id ON species_jurisdiction_status (species_id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_species_jurisdiction_status_jurisdiction_id ON species_jurisdiction_status (jurisdiction_id)"
            ))

    with engine.begin() as connection:
        connection.execute(text(
            "INSERT OR IGNORE INTO species "
            "(scientific_name, common_name, status, created_at, updated_at) "
            "VALUES ('Pterois volitans', 'Lionfish', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "UPDATE species_programs SET species_id = (SELECT id FROM species WHERE species.scientific_name = species_programs.scientific_name) "
            "WHERE species_id IS NULL"
        ))

    with engine.begin() as connection:
        for table_name, definition in scientific_ownership_columns.items():
            existing = {column["name"] for column in inspect(engine).get_columns(table_name)}
            column_name = definition.split()[0]
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {definition}"))
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_{column_name} ON {table_name} ({column_name})"))
        for table_name in ("next_area_prediction_generations", "next_area_snapshot_generations"):
            existing = {column["name"] for column in inspect(engine).get_columns(table_name)}
            if "suitability_deployment_id" not in existing:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN suitability_deployment_id INTEGER REFERENCES suitability_deployments(id)"))
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_suitability_deployment_id ON {table_name} (suitability_deployment_id)"))

        connection.execute(text(
            "INSERT OR IGNORE INTO species_programs "
            "(jurisdiction_id, scientific_name, common_name, status, species_id, created_at, updated_at) "
            "SELECT jurisdictions.id, 'Pterois volitans', 'Lionfish', 'ACTIVE', "
            "(SELECT id FROM species WHERE scientific_name = 'Pterois volitans'), "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM jurisdictions JOIN regions ON regions.id = jurisdictions.region_id "
            "WHERE regions.slug = 'caribbean' AND jurisdictions.slug = 'jamaica'"
        ))

        connection.execute(text(
            "INSERT OR IGNORE INTO species_jurisdiction_status "
            "(species_id, jurisdiction_id, ecological_status, source, source_url, notes, created_at, updated_at) "
            "SELECT species.id, jurisdictions.id, 'INVASIVE', 'legacy-unverified', NULL, "
            "'Migrated from JAMAICA_ECOLOGICAL_STATUS dict in marine_observation_service.py. "
            "This record is retained for behavioral compatibility with existing Jamaica observations. "
            "To be replaced with verified provenance in a future Phase 10X registry update.', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM species, jurisdictions JOIN regions ON regions.id = jurisdictions.region_id "
            "WHERE species.scientific_name = 'Pterois volitans' "
            "AND regions.slug = 'caribbean' AND jurisdictions.slug = 'jamaica'"
        ))

    # ----------------------------------------------------------------
    # Phase 10C: Scientific dataset ownership + provenance
    # ----------------------------------------------------------------
    # Backfill only what is supportable from existing repository
    # evidence:
    #   1. Pterois volitans OBIS Jamaica historical occurrence
    #      snapshot (JAMAICA_GEOMETRY in historical_occurrence_service).
    #   2. Pterois volitans environmental feature snapshot
    #      (caribbean-grid-v2-environment-v1: WOA23 + ETOPO1 + coast).
    # The v3 deployment is then linked to both via
    # ScientificDatasetDeployment with explicit roles. No values
    # are mutated on existing scientific rows.
    with engine.begin() as connection:
        # Add dataset_id column to historical_occurrences if missing
        ho_columns = {
            column[1]
            for column in connection.execute(
                text("PRAGMA table_info('historical_occurrences')")
            ).fetchall()
        }
        if "dataset_id" not in ho_columns:
            connection.execute(text(
                "ALTER TABLE historical_occurrences "
                "ADD COLUMN dataset_id INTEGER REFERENCES scientific_datasets(id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_historical_occurrences_dataset_id "
                "ON historical_occurrences (dataset_id)"
            ))

    if not inspect(engine).has_table("scientific_datasets"):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE scientific_datasets ("
                "id INTEGER PRIMARY KEY, "
                "slug VARCHAR(128) NOT NULL, "
                "name VARCHAR(256) NOT NULL, "
                "dataset_type VARCHAR(32) NOT NULL, "
                "status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', "
                "description TEXT, "
                "species_id INTEGER REFERENCES species(id), "
                "species_program_id INTEGER REFERENCES species_programs(id), "
                "geographic_scope_type VARCHAR(16) NOT NULL DEFAULT 'JURISDICTION', "
                "region_id INTEGER REFERENCES regions(id), "
                "jurisdiction_id INTEGER REFERENCES jurisdictions(id), "
                "source_name VARCHAR(64) NOT NULL, "
                "source_type VARCHAR(32), "
                "source_reference VARCHAR(512), "
                "source_version VARCHAR(64), "
                "acquisition_manifest_json TEXT, "
                "retrieved_at DATETIME, "
                "record_count INTEGER, "
                "artifact_path VARCHAR(512), "
                "artifact_sha256 VARCHAR(64), "
                "notes TEXT, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "CONSTRAINT uq_scientific_dataset_slug UNIQUE (slug)"
                ")"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_scientific_datasets_species_id "
                "ON scientific_datasets (species_id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_scientific_datasets_geographic_scope_type "
                "ON scientific_datasets (geographic_scope_type)"
            ))

    if not inspect(engine).has_table("scientific_dataset_deployments"):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE scientific_dataset_deployments ("
                "id INTEGER PRIMARY KEY, "
                "scientific_dataset_id INTEGER NOT NULL REFERENCES scientific_datasets(id), "
                "suitability_deployment_id INTEGER NOT NULL REFERENCES suitability_deployments(id), "
                "role VARCHAR(64) NOT NULL, "
                "notes TEXT, "
                "created_at DATETIME NOT NULL, "
                "CONSTRAINT uq_scientific_dataset_deployment UNIQUE "
                "(scientific_dataset_id, suitability_deployment_id, role)"
                ")"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_scientific_dataset_deployments_dataset_id "
                "ON scientific_dataset_deployments (scientific_dataset_id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_scientific_dataset_deployments_deployment_id "
                "ON scientific_dataset_deployments (suitability_deployment_id)"
            ))

    # ----------------------------------------------------------------
    # Backfill datasets from existing repository evidence.
    # ----------------------------------------------------------------
    # 1. Pterois volitans OBIS Jamaica historical occurrence snapshot.
    with engine.begin() as connection:
        # The OBIS query used to produce historical_occurrences:
        #   provider: obis
        #   endpoint: https://api.obis.org/v3/occurrence
        #   query parameters: taxonid=<Pterois volitans AphiaID>,
        #                      geometry=<JAMAICA_GEOMETRY WKT>,
        #                      pagination=size&offset
        #   retrieved_at: imported_at of the earliest record (best
        #                  available proxy for retrieval time)
        # The taxon_id for Pterois volitans from OBIS /v3/taxon/complete/
        # is 159559. The exact retrieval timestamp is not preserved in
        # the existing schema; we record imported_at as a best-available
        # proxy and explicitly mark it as such in the manifest.
        earliest_imported_at = connection.execute(text(
            "SELECT MIN(imported_at) FROM historical_occurrences WHERE source = 'OBIS'"
        )).scalar()
        # imported_at is stored as a string in this schema. If the value
        # cannot be parsed as ISO 8601, fall back to NULL.
        earliest_iso = None
        if earliest_imported_at is not None:
            from datetime import datetime as _dt
            try:
                parsed = _dt.fromisoformat(str(earliest_imported_at))
                earliest_iso = parsed.isoformat()
            except (TypeError, ValueError):
                earliest_iso = str(earliest_imported_at)
        connection.execute(text(
            "INSERT OR IGNORE INTO scientific_datasets "
            "(slug, name, dataset_type, status, description, "
            "species_id, species_program_id, geographic_scope_type, "
            "region_id, jurisdiction_id, "
            "source_name, source_type, source_reference, source_version, "
            "acquisition_manifest_json, retrieved_at, record_count, "
            "artifact_path, artifact_sha256, notes, "
            "created_at, updated_at) "
            "VALUES ("
            ":slug, :name, :dataset_type, :status, :description, "
            "(SELECT id FROM species WHERE scientific_name = :species_name), "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = "
            "(SELECT id FROM jurisdictions WHERE slug = :jurisdiction_slug) "
            "AND scientific_name = :species_name), "
            ":geographic_scope_type, "
            "(SELECT id FROM regions WHERE slug = :region_slug), "
            "(SELECT id FROM jurisdictions WHERE slug = :jurisdiction_slug), "
            ":source_name, :source_type, :source_reference, :source_version, "
            ":acquisition_manifest_json, :retrieved_at, :record_count, "
            ":artifact_path, :artifact_sha256, :notes, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
            ")"
        ), {
            "slug": "pterois-volitans-jamaica-obis-iNaturalist-2025-08",
            "name": "Pterois volitans OBIS Jamaica historical occurrence snapshot (iNaturalist research-grade observations)",
            "dataset_type": "OCCURRENCE",
            "status": "ACTIVE",
            "description": (
                "Pterois volitans historical occurrences retrieved from OBIS v3 /occurrence for the Jamaica EEZ polygon. "
                "Backfilled into the production database in 2025-08 by backfill_historical_occurrences.py. "
                "All 54 rows in historical_occurrences were produced from this query and remain associated with it. "
                "The retrieval timestamp is not separately preserved; imported_at is the best available proxy."
            ),
            "species_name": "Pterois volitans",
            "jurisdiction_slug": "jamaica",
            "geographic_scope_type": "JURISDICTION",
            "region_slug": "caribbean",
            "source_name": "OBIS",
            "source_type": "API",
            "source_reference": "https://api.obis.org/v3/occurrence",
            "source_version": "taxonid=159559, geometry=POLYGON((-78.6 16.9, -78.6 18.7, -75.9 18.7, -75.9 16.9, -78.6 16.9))",
            "acquisition_manifest_json": (
                "Query parameters reconstructed from regional_evidence_provider.py. "
                "Public unauthenticated source request. "
                "No sensitive access material is stored."
            ),
            "retrieved_at": earliest_iso,
            "record_count": 54,
            "artifact_path": None,
            "artifact_sha256": None,
            "notes": "Migrated from the historical_occurrence_service.backfill() call.",
        })

        # Phase 10C corrective update:
        # Existing databases may already contain this dataset from an earlier
        # migration run, so INSERT OR IGNORE will not update its manifest.
        connection.execute(text(
            "UPDATE scientific_datasets "
            "SET acquisition_manifest_json = :manifest "
            "WHERE slug = :slug"
        ), {
            "slug": "pterois-volitans-jamaica-obis-iNaturalist-2025-08",
            "manifest": (
                "Query parameters reconstructed from regional_evidence_provider.py. "
                "Public unauthenticated source request. "
                "No sensitive access material is stored."
            ),
        })

        # Link all 54 existing historical occurrences to this dataset
        connection.execute(text(
            "UPDATE historical_occurrences "
            "SET dataset_id = (SELECT id FROM scientific_datasets "
            "WHERE slug = :slug) "
            "WHERE dataset_id IS NULL AND source = 'OBIS'"
        ), {
            "slug": "pterois-volitans-jamaica-obis-iNaturalist-2025-08"
        })
    # 2. Pterois volitans environmental feature snapshot (WOA23 + ETOPO1)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT OR IGNORE INTO scientific_datasets "
            "(slug, name, dataset_type, status, description, "
            "species_id, species_program_id, geographic_scope_type, "
            "region_id, jurisdiction_id, "
            "source_name, source_type, source_reference, source_version, "
            "acquisition_manifest_json, retrieved_at, record_count, "
            "artifact_path, artifact_sha256, notes, "
            "created_at, updated_at) "
            "VALUES ("
            ":slug, :name, :dataset_type, :status, :description, "
            "(SELECT id FROM species WHERE scientific_name = :species_name), "
            "(SELECT id FROM species_programs WHERE jurisdiction_id = "
            "(SELECT id FROM jurisdictions WHERE slug = :jurisdiction_slug) "
            "AND scientific_name = :species_name), "
            ":geographic_scope_type, "
            "(SELECT id FROM regions WHERE slug = :region_slug), "
            "NULL, "
            ":source_name, :source_type, :source_reference, :source_version, "
            "NULL, NULL, :record_count, NULL, NULL, :notes, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
            ")"
        ), {
            "slug": "pterois-volitans-environmental-caribbean-grid-v2-environment-v1",
            "name": "Pterois volitans Caribbean environmental feature snapshot (caribbean-grid-v2-environment-v1)",
            "dataset_type": "ENVIRONMENTAL",
            "status": "ACTIVE",
            "description": (
                "Environmental feature snapshot (bathymetry, SST climatology, salinity climatology) for the Caribbean region. "
                "Generated by enrich_prediction_training_environment.py from NOAA ETOPO1 (bathymetry) and NOAA World Ocean Atlas 2023 "
                "(SST and salinity monthly surface climatology). 2334 cells across the caribbean-grid-v2 extent. "
                "Used by pterois-volitans-suitability-v3 as the ENVIRONMENTAL_INPUT for model_d_environment_combined and model_f_nonlinear_environment. "
                "Cache files retained in data/environmental_cache/woa23_{t,s}{01..12}an01.csv.gz."
            ),
            "species_name": "Pterois volitans",
            "jurisdiction_slug": "jamaica",
            "geographic_scope_type": "REGION",
            "region_slug": "caribbean",
            "source_name": "NOAA ETOPO1 + WOA23",
            "source_type": "API+CACHED",
            "source_reference": "https://gis.ngdc.noaa.gov/arcgis/rest/services/etopo1/MapServer/identify; https://www.ncei.noaa.gov/data/oceans/woa/WOA23/DATA/{temperature,salinity}/csv/decav/1.00/woa23_decav_{t,s}{01..12}an01.csv.gz",
            "source_version": "WOA23 (1955-2022 monthly surface climatology 1-degree) + ETOPO1 (static)",
            "record_count": 2334,
            "notes": "Generated for caribbean-grid-v2 environment version. NOAA ETOPO1 is queried live per cell. WOA23 files are cached locally in data/environmental_cache/. Acquired via enrich_prediction_training_environment.py for the v3 model.",
        })

    # 3. Link the Jamaica v3 suitability deployment to both datasets.
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT OR IGNORE INTO scientific_dataset_deployments "
            "(scientific_dataset_id, suitability_deployment_id, role, created_at) "
            "SELECT "
            "(SELECT id FROM scientific_datasets WHERE slug = :slug), "
            "(SELECT id FROM suitability_deployments "
            "WHERE model_version = :deployment_model_version LIMIT 1), "
            ":role, "
            "CURRENT_TIMESTAMP "
            "WHERE EXISTS ("
            "SELECT 1 FROM scientific_datasets WHERE slug = :slug"
            ") AND EXISTS ("
            "SELECT 1 FROM suitability_deployments "
            "WHERE model_version = :deployment_model_version"
            ")"
        ), {
            "slug": "pterois-volitans-jamaica-obis-iNaturalist-2025-08",
            "deployment_model_version": "pterois-volitans-suitability-v3",
            "role": "TRAINING_OCCURRENCES",
        })
        connection.execute(text(
            "INSERT OR IGNORE INTO scientific_dataset_deployments "
            "(scientific_dataset_id, suitability_deployment_id, role, created_at) "
            "SELECT "
            "(SELECT id FROM scientific_datasets WHERE slug = :slug), "
            "(SELECT id FROM suitability_deployments "
            "WHERE model_version = :deployment_model_version LIMIT 1), "
            ":role, "
            "CURRENT_TIMESTAMP "
            "WHERE EXISTS ("
            "SELECT 1 FROM scientific_datasets WHERE slug = :slug"
            ") AND EXISTS ("
            "SELECT 1 FROM suitability_deployments "
            "WHERE model_version = :deployment_model_version"
            ")"
        ), {
            "slug": "pterois-volitans-environmental-caribbean-grid-v2-environment-v1",
            "deployment_model_version": "pterois-volitans-suitability-v3",
            "role": "ENVIRONMENTAL_INPUT",
        })

    artifact_hash = None
    with engine.begin() as connection:
        artifact_row = connection.execute(text(
            "SELECT artifact_path FROM habitat_suitability_models "
            "WHERE model_version = 'pterois-volitans-suitability-v3'"
        )).first()
    if artifact_row:
        artifact_path = Path(artifact_row[0])
        if artifact_path.exists():
            artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    with engine.begin() as connection:
        connection.execute(text(
            "INSERT OR IGNORE INTO suitability_deployments "
            "(species_program_id, habitat_suitability_model_id, model_version, status, artifact_hash, generated_at, activated_at, created_at, updated_at) "
            "SELECT programs.id, models.id, models.model_version, 'ACTIVE', :artifact_hash, "
            "(SELECT MAX(generated_at) FROM habitat_suitability_v3_grid_cells WHERE model_version = models.model_version), "
            "(SELECT MAX(generated_at) FROM habitat_suitability_v3_grid_cells WHERE model_version = models.model_version), "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM species_programs programs JOIN jurisdictions ON jurisdictions.id = programs.jurisdiction_id "
            "JOIN regions ON regions.id = jurisdictions.region_id "
            "JOIN habitat_suitability_models models ON models.scientific_name = programs.scientific_name "
            "WHERE regions.slug = 'caribbean' AND jurisdictions.slug = 'jamaica' "
            "AND models.model_version = 'pterois-volitans-suitability-v3'"
        ), {"artifact_hash": artifact_hash})
        connection.execute(text(
            "UPDATE habitat_suitability_v3_grid_cells SET suitability_deployment_id = "
            "(SELECT deployments.id FROM suitability_deployments deployments "
            "WHERE deployments.model_version = habitat_suitability_v3_grid_cells.model_version) "
            "WHERE model_version = 'pterois-volitans-suitability-v3' AND suitability_deployment_id IS NULL"
        ))
        for table_name in ("next_area_prediction_generations", "next_area_snapshot_generations"):
            connection.execute(text(
                f"UPDATE {table_name} SET species_program_id = ("
                "SELECT programs.id FROM species_programs programs JOIN jurisdictions ON jurisdictions.id = programs.jurisdiction_id "
                "JOIN regions ON regions.id = jurisdictions.region_id WHERE regions.slug = 'caribbean' AND jurisdictions.slug = 'jamaica' "
                "AND programs.scientific_name = 'Pterois volitans') "
                "WHERE scientific_name = 'Pterois volitans' AND species_program_id IS NULL"
            ))
            connection.execute(text(
                f"UPDATE {table_name} SET suitability_deployment_id = ("
                "SELECT deployments.id FROM suitability_deployments deployments JOIN species_programs programs ON programs.id = deployments.species_program_id "
                "WHERE programs.scientific_name = 'Pterois volitans' AND deployments.model_version = 'pterois-volitans-suitability-v3') "
                "WHERE scientific_name = 'Pterois volitans' AND suitability_model_version = 'pterois-volitans-suitability-v3' "
                "AND suitability_deployment_id IS NULL"
            ))
        connection.execute(text("DROP INDEX IF EXISTS uq_next_area_snapshot_active_version"))
        connection.execute(text("DROP INDEX IF EXISTS uq_next_area_snapshot_building_version"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_next_area_snapshot_active_program_version "
            "ON next_area_snapshot_generations (species_program_id, prediction_version) WHERE is_active = 1"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_next_area_snapshot_building_program_version "
            "ON next_area_snapshot_generations (species_program_id, prediction_version) WHERE status = 'BUILDING'"
        ))

    boundary_columns = {
        column["name"]
        for column in inspect(engine).get_columns("jurisdiction_boundaries")
    }
    if "source_reference" not in boundary_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE jurisdiction_boundaries "
                "ADD COLUMN source_reference VARCHAR"
            ))
    if "geometry_hash" not in boundary_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE jurisdiction_boundaries "
                "ADD COLUMN geometry_hash VARCHAR(64)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jurisdiction_boundaries_geometry_hash "
                "ON jurisdiction_boundaries (geometry_hash)"
            ))

    environmental_columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "historical_environmental_features"
        )
    }
    environmental_migrations = {
        "sst_distance_km": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN sst_distance_km FLOAT"
        ),
        "salinity_distance_km": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN salinity_distance_km FLOAT"
        ),
        "depth_distance_km": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN depth_distance_km FLOAT"
        ),
        "sst_sampling_method": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN sst_sampling_method VARCHAR "
            "NOT NULL DEFAULT 'MISSING'"
        ),
        "salinity_sampling_method": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN salinity_sampling_method VARCHAR "
            "NOT NULL DEFAULT 'MISSING'"
        ),
        "depth_sampling_method": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN depth_sampling_method VARCHAR "
            "NOT NULL DEFAULT 'MISSING'"
        ),
        "depth_quality_flag": (
            "ALTER TABLE historical_environmental_features "
            "ADD COLUMN depth_quality_flag VARCHAR "
            "NOT NULL DEFAULT 'MISSING'"
        ),
    }

    with engine.begin() as connection:
        for column_name, statement in (
            environmental_migrations.items()
        ):
            if column_name not in environmental_columns:
                connection.execute(text(statement))

    print(
        "Marine observation database initialized."
    )


if __name__ == "__main__":
    initialize_database()
