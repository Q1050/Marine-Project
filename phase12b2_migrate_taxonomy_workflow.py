"""Additive/idempotent taxonomy preparation migration."""
import sqlite3
SQL="""CREATE TABLE IF NOT EXISTS taxonomy_preparations(id INTEGER PRIMARY KEY,taxon_id INTEGER NOT NULL REFERENCES species(id) ON DELETE RESTRICT,region_id INTEGER NOT NULL REFERENCES regions(id) ON DELETE RESTRICT,provider VARCHAR(64) NOT NULL,authoritative_identifier_scheme VARCHAR(64) NOT NULL,authoritative_identifier VARCHAR(128) NOT NULL,raw_artifact_reference VARCHAR(512) NOT NULL,raw_artifact_sha256 VARCHAR(64) NOT NULL,proposed_scientific_name VARCHAR(256) NOT NULL,proposed_rank VARCHAR(32) NOT NULL,proposed_accepted_name_status VARCHAR(32) NOT NULL,proposed_accepted_identifier VARCHAR(128),proposed_parent_identifier VARCHAR(128),proposed_authorship VARCHAR(256),reconciliation_result VARCHAR(24) NOT NULL,limitations_json TEXT NOT NULL,manifest_json TEXT NOT NULL,preparation_fingerprint VARCHAR(64) NOT NULL UNIQUE,workflow_status VARCHAR(24) NOT NULL DEFAULT 'READY_FOR_REVIEW',prepared_by VARCHAR(256) NOT NULL,prepared_at DATETIME NOT NULL,approval_reference VARCHAR(256),approved_by_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,approved_at DATETIME,approved_dependency_fingerprint VARCHAR(64),applied_at DATETIME,registry_entry_id INTEGER REFERENCES regional_taxon_registry(id) ON DELETE RESTRICT,last_error TEXT)"""
def run_migration(connection:sqlite3.Connection):
    existed=connection.execute("select 1 from sqlite_master where type='table' and name='taxonomy_preparations'").fetchone() is not None
    with connection:
        connection.execute(SQL)
        for column in ("taxon_id","region_id","workflow_status","preparation_fingerprint"):
            connection.execute(f"create index if not exists ix_taxonomy_preparations_{column} on taxonomy_preparations({column})")
    return {"table_created":not existed}
