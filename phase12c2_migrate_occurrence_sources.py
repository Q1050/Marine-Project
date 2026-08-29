"""Additive/idempotent Phase 12C-2 source registration migration."""
import argparse,sqlite3

SOURCE_SQL="""CREATE TABLE IF NOT EXISTS occurrence_source_registrations(id INTEGER PRIMARY KEY,source_registration_id VARCHAR(128) NOT NULL,source_name VARCHAR(256) NOT NULL,scientific_provider VARCHAR(256) NOT NULL,transport_interface VARCHAR(128),provider_dataset_id VARCHAR(256),provider_dataset_version VARCHAR(128),acquisition_mechanism VARCHAR(64) NOT NULL,documentation_reference VARCHAR(512) NOT NULL,license VARCHAR(256) NOT NULL,reuse_conditions TEXT NOT NULL,geographic_scope_json TEXT NOT NULL,taxonomic_scope_json TEXT NOT NULL,source_provenance_json TEXT NOT NULL,limitations_json TEXT NOT NULL,configuration_json TEXT NOT NULL,configuration_version VARCHAR(64) NOT NULL,configuration_fingerprint VARCHAR(64) NOT NULL UNIQUE,workflow_status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',created_by_user_id INTEGER NOT NULL REFERENCES users(id),created_at DATETIME NOT NULL,reviewed_by_user_id INTEGER REFERENCES users(id),reviewed_at DATETIME,approval_reference VARCHAR(256),approved_configuration_fingerprint VARCHAR(64),activated_at DATETIME,deactivated_at DATETIME,superseded_at DATETIME,predecessor_id INTEGER REFERENCES occurrence_source_registrations(id))"""

def run_migration(connection):
 tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")};columns={row[1] for row in connection.execute("PRAGMA table_info(occurrence_acquisition_preparations)")}
 with connection:
  connection.execute(SOURCE_SQL)
  if "source_registration_id" not in columns:connection.execute("ALTER TABLE occurrence_acquisition_preparations ADD COLUMN source_registration_id INTEGER REFERENCES occurrence_source_registrations(id)")
  for table,column in (("occurrence_source_registrations","source_registration_id"),("occurrence_source_registrations","workflow_status"),("occurrence_acquisition_preparations","source_registration_id")):connection.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})")
 return {"source_table_created":"occurrence_source_registrations" not in tables,"preparation_link_added":"source_registration_id" not in columns}

if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args();connection=sqlite3.connect(args.database);print(run_migration(connection));connection.close()
