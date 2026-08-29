"""Additive/idempotent Phase 12B-1 taxonomy governance migration."""
import sqlite3

SPECIES_COLUMNS = {
    "taxonomic_rank": "VARCHAR(32)",
    "authoritative_identifier_scheme": "VARCHAR(64)",
    "authoritative_identifier": "VARCHAR(128)",
    "accepted_name_status": "VARCHAR(32)",
    "accepted_taxon_id": "INTEGER REFERENCES species(id) ON DELETE RESTRICT",
    "parent_taxon_id": "INTEGER REFERENCES species(id) ON DELETE RESTRICT",
    "authorship": "VARCHAR(256)",
    "taxonomic_provenance_json": "TEXT",
    "provenance_version": "VARCHAR(128)",
    "provenance_fingerprint": "VARCHAR(64)",
}

REGISTRY_SQL = """CREATE TABLE IF NOT EXISTS regional_taxon_registry(
id INTEGER PRIMARY KEY, region_id INTEGER NOT NULL REFERENCES regions(id) ON DELETE RESTRICT,
taxon_id INTEGER NOT NULL REFERENCES species(id) ON DELETE RESTRICT, registry_version VARCHAR(128) NOT NULL,
inclusion_basis VARCHAR(128) NOT NULL, source_references_json TEXT NOT NULL,
review_status VARCHAR(24) NOT NULL DEFAULT 'CANDIDATE', reviewed_by VARCHAR(256), reviewed_at DATETIME,
approved_by VARCHAR(256), approved_at DATETIME, provenance_json TEXT NOT NULL,
provenance_fingerprint VARCHAR(64) NOT NULL UNIQUE, created_at DATETIME NOT NULL, superseded_at DATETIME,
CONSTRAINT uq_regional_taxon_registry_version UNIQUE(region_id,taxon_id,registry_version))"""

def run_migration(connection: sqlite3.Connection):
    existing = {row[1] for row in connection.execute("PRAGMA table_info(species)")}
    added = []
    with connection:
        for name, sql_type in SPECIES_COLUMNS.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE species ADD COLUMN {name} {sql_type}")
                added.append(name)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_species_authoritative_identity ON species(authoritative_identifier_scheme,authoritative_identifier)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_species_provenance_fingerprint ON species(provenance_fingerprint)")
        connection.execute(REGISTRY_SQL)
        connection.execute("CREATE INDEX IF NOT EXISTS ix_regional_taxon_region ON regional_taxon_registry(region_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_regional_taxon_taxon ON regional_taxon_registry(taxon_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_regional_taxon_status ON regional_taxon_registry(review_status)")
    return {"species_columns_added": added, "registry_table_ready": True}
