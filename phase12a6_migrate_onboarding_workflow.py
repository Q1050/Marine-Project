"""Additive/idempotent persisted onboarding workflow migration."""
import sqlite3
SQL="""CREATE TABLE IF NOT EXISTS jurisdiction_onboarding_preparations(id INTEGER PRIMARY KEY,region_id INTEGER NOT NULL REFERENCES regions(id) ON DELETE RESTRICT,canonical_name VARCHAR(256) NOT NULL,canonical_identifier_scheme VARCHAR(32) NOT NULL,canonical_identifier VARCHAR(64) NOT NULL,jurisdiction_type VARCHAR(48) NOT NULL,sovereign_parent_id INTEGER REFERENCES jurisdictions(id) ON DELETE RESTRICT,manifest_version VARCHAR(128) NOT NULL,manifest_path VARCHAR(512) NOT NULL,manifest_json TEXT NOT NULL,manifest_fingerprint VARCHAR(64) NOT NULL UNIQUE,boundary_artifact_path VARCHAR(512) NOT NULL,boundary_provider VARCHAR(256) NOT NULL,provider_boundary_identifier VARCHAR(128) NOT NULL,boundary_source_sha256 VARCHAR(64) NOT NULL,geometry_sha256 VARCHAR(64) NOT NULL,workflow_state VARCHAR(32) NOT NULL DEFAULT 'READY_FOR_REVIEW',approval_reference VARCHAR(256),approved_by_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,approved_at DATETIME,approved_dependency_fingerprint VARCHAR(64),applied_at DATETIME,resulting_jurisdiction_id INTEGER REFERENCES jurisdictions(id) ON DELETE RESTRICT,resulting_boundary_id INTEGER REFERENCES jurisdiction_boundaries(id) ON DELETE RESTRICT,last_error TEXT,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL)"""
def run_migration(c:sqlite3.Connection):
 existed=c.execute("select 1 from sqlite_master where type='table' and name='jurisdiction_onboarding_preparations'").fetchone() is not None
 with c:
  c.execute(SQL)
  for col in ('region_id','canonical_identifier','manifest_fingerprint','workflow_state'):
   c.execute(f"create index if not exists ix_onboarding_preparations_{col} on jurisdiction_onboarding_preparations({col})")
 return {'table_created':not existed}
