"""Additive/idempotent Milestone 13D operationalization migration."""
import argparse,sqlite3
from milestone13c_migrate_early_warning import run_migration as migrate_13c
TABLES={
"scientific_reviewer_grants":"""CREATE TABLE scientific_reviewer_grants (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id),role VARCHAR(48) NOT NULL DEFAULT 'JURISDICTION_SCIENTIFIC_REVIEWER',status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',granted_by_user_id INTEGER NOT NULL REFERENCES users(id),grant_reference VARCHAR(256) NOT NULL,granted_at DATETIME NOT NULL,revoked_by_user_id INTEGER REFERENCES users(id),revoked_at DATETIME,CONSTRAINT uq_scientific_reviewer_grant UNIQUE(user_id,jurisdiction_id))""",
"anomaly_review_assignments":"""CREATE TABLE anomaly_review_assignments (id INTEGER PRIMARY KEY,anomaly_assessment_id INTEGER NOT NULL REFERENCES anomaly_assessments(id),jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id),reviewer_user_id INTEGER NOT NULL REFERENCES users(id),status VARCHAR(16) NOT NULL DEFAULT 'ASSIGNED',assigned_by_user_id INTEGER NOT NULL REFERENCES users(id),assigned_at DATETIME NOT NULL,unassigned_at DATETIME,reason TEXT NOT NULL)""",
"scientific_domain_events":"""CREATE TABLE scientific_domain_events (id INTEGER PRIMARY KEY,event_type VARCHAR(64) NOT NULL,jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id),taxon_id INTEGER REFERENCES species(id),observation_id INTEGER REFERENCES observations(id),dependency_reference VARCHAR(256),event_fingerprint VARCHAR(64) NOT NULL UNIQUE,payload_json TEXT NOT NULL DEFAULT '{}',processing_state VARCHAR(24) NOT NULL DEFAULT 'PENDING',attempts INTEGER NOT NULL DEFAULT 0,last_attempted_at DATETIME,last_error TEXT,processed_at DATETIME,created_at DATETIME NOT NULL)"""}
COLUMNS=(('mode',"VARCHAR(32) NOT NULL DEFAULT 'DESCRIPTIVE_ONLY'"),('environmental_context_json',"TEXT NOT NULL DEFAULT '{}'"),('minimum_evidence_json',"TEXT NOT NULL DEFAULT '{}'"),('algorithm_version',"VARCHAR(64) NOT NULL DEFAULT 'marine-early-warning-v1'"),('automatic_evaluation_enabled',"BOOLEAN NOT NULL DEFAULT 0"),('provenance_json',"TEXT NOT NULL DEFAULT '{}'"),('limitations_json',"TEXT NOT NULL DEFAULT '[]'"),('activated_at','DATETIME'),('deactivated_at','DATETIME'),('superseded_at','DATETIME'),('supersedes_configuration_id','INTEGER REFERENCES anomaly_configurations(id)'))
INDEXES=("CREATE INDEX IF NOT EXISTS ix_scientific_grant_scope ON scientific_reviewer_grants(user_id,jurisdiction_id,status)","CREATE INDEX IF NOT EXISTS ix_anomaly_assignment_active ON anomaly_review_assignments(anomaly_assessment_id,status)","CREATE INDEX IF NOT EXISTS ix_scientific_events_processing ON scientific_domain_events(processing_state,created_at)","CREATE INDEX IF NOT EXISTS ix_anomaly_assessment_status ON anomaly_assessments(overall_status)","CREATE INDEX IF NOT EXISTS ix_anomaly_assessment_dependency ON anomaly_assessments(dependency_fingerprint)")
def run_migration(c):
 migrate_13c(c);created=[];added=[];existing={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 with c:
  for name,sql in TABLES.items():
   if name not in existing:c.execute(sql);created.append(name)
  cols={r[1] for r in c.execute('PRAGMA table_info(anomaly_configurations)')}
  for name,ddl in COLUMNS:
   if name not in cols:c.execute(f'ALTER TABLE anomaly_configurations ADD COLUMN {name} {ddl}');added.append(name)
  for sql in INDEXES:c.execute(sql)
 return {'tables_created':created,'configuration_columns_added':added}
def main():
 p=argparse.ArgumentParser();p.add_argument('--database',default='marine_observations.db');a=p.parse_args()
 with sqlite3.connect(a.database) as c:print(run_migration(c))
if __name__=='__main__':main()
