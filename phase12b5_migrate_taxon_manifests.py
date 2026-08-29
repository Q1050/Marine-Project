"""Additive/idempotent Phase 12B-5 operational manifest schema."""
import argparse
import sqlite3

RUN_SQL = """CREATE TABLE IF NOT EXISTS regional_taxon_manifest_runs(
id INTEGER PRIMARY KEY, manifest_id VARCHAR(128) NOT NULL, manifest_version VARCHAR(64) NOT NULL,
manifest_fingerprint VARCHAR(64) NOT NULL UNIQUE, region_id INTEGER NOT NULL REFERENCES regions(id),
operator_reference VARCHAR(256) NOT NULL, provenance_json TEXT NOT NULL, limitations_json TEXT NOT NULL,
canonical_manifest_json TEXT NOT NULL, execution_state VARCHAR(24) NOT NULL DEFAULT 'PREPARED',
created_by_user_id INTEGER NOT NULL REFERENCES users(id), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
completed_at DATETIME, firewall_report_json TEXT)"""
ITEM_SQL = """CREATE TABLE IF NOT EXISTS regional_taxon_manifest_items(
id INTEGER PRIMARY KEY, manifest_run_id INTEGER NOT NULL REFERENCES regional_taxon_manifest_runs(id) ON DELETE CASCADE,
item_key VARCHAR(256) NOT NULL, ordinal INTEGER NOT NULL, submitted_identity_json TEXT NOT NULL,
resolution_json TEXT, proposed_action VARCHAR(48) NOT NULL, workflow_state VARCHAR(24) NOT NULL DEFAULT 'PREPARED',
preparation_id INTEGER REFERENCES taxonomy_preparations(id), local_taxon_candidate_id INTEGER REFERENCES local_taxon_candidates(id),
species_id INTEGER REFERENCES species(id), registry_entry_id INTEGER REFERENCES regional_taxon_registry(id),
approval_reference VARCHAR(256), approved_by_user_id INTEGER REFERENCES users(id), approved_at DATETIME, applied_at DATETIME,
retry_count INTEGER NOT NULL DEFAULT 0, last_error TEXT, result_json TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
UNIQUE(manifest_run_id,item_key))"""

def run_migration(connection: sqlite3.Connection):
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    with connection:
        connection.execute(RUN_SQL)
        connection.execute(ITEM_SQL)
        for table, column in (("regional_taxon_manifest_runs", "region_id"), ("regional_taxon_manifest_runs", "execution_state"), ("regional_taxon_manifest_items", "manifest_run_id"), ("regional_taxon_manifest_items", "proposed_action"), ("regional_taxon_manifest_items", "workflow_state")):
            connection.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})")
    return {"runs_created": "regional_taxon_manifest_runs" not in existing, "items_created": "regional_taxon_manifest_items" not in existing}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="marine_observations.db")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    print(run_migration(connection))
    connection.close()
