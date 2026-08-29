"""Additive/idempotent anomaly and early-warning persistence migration."""
import argparse, sqlite3
from phase11b1_migrate_anomaly_domain import run_migration as migrate_domain
from phase11b7_migrate_synthesis_snapshot import run_migration as migrate_synthesis

REVIEW_SQL="""CREATE TABLE IF NOT EXISTS anomaly_review_events (id INTEGER PRIMARY KEY, anomaly_assessment_id INTEGER NOT NULL REFERENCES anomaly_assessments(id) ON DELETE RESTRICT, jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT, reviewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, from_state VARCHAR(32), to_state VARCHAR(32) NOT NULL, reason TEXT NOT NULL, created_at DATETIME NOT NULL)"""
CONFIG_SQL="""CREATE TABLE IF NOT EXISTS anomaly_configurations (id INTEGER PRIMARY KEY, jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT, taxon_id INTEGER NOT NULL REFERENCES species(id) ON DELETE RESTRICT, configuration_version VARCHAR(64) NOT NULL, enabled_signal_types_json TEXT NOT NULL DEFAULT '[]', spatial_rule_json TEXT, temporal_rule_json TEXT, review_status VARCHAR(24) NOT NULL DEFAULT 'READY_FOR_REVIEW', reviewed_by_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT, review_reference VARCHAR(256), reviewed_at DATETIME, dependency_fingerprint VARCHAR(64) NOT NULL UNIQUE, created_at DATETIME NOT NULL, CONSTRAINT uq_anomaly_configuration_version UNIQUE(jurisdiction_id,taxon_id,configuration_version))"""
INDEXES=("CREATE INDEX IF NOT EXISTS ix_anomaly_assessment_generated ON anomaly_assessments(generated_at)","CREATE INDEX IF NOT EXISTS ix_anomaly_review_assessment ON anomaly_review_events(anomaly_assessment_id)","CREATE INDEX IF NOT EXISTS ix_anomaly_review_jurisdiction ON anomaly_review_events(jurisdiction_id)","CREATE INDEX IF NOT EXISTS ix_anomaly_review_state ON anomaly_review_events(to_state)","CREATE INDEX IF NOT EXISTS ix_anomaly_review_created ON anomaly_review_events(created_at)","CREATE INDEX IF NOT EXISTS ix_anomaly_config_jurisdiction_taxon ON anomaly_configurations(jurisdiction_id,taxon_id)")
def run_migration(connection):
 before={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")};domain=migrate_domain(connection);synthesis=migrate_synthesis(connection)
 with connection:
  connection.execute(REVIEW_SQL);connection.execute(CONFIG_SQL)
  for sql in INDEXES:connection.execute(sql)
 return {**domain,**synthesis,"anomaly_review_events_created":"anomaly_review_events" not in before,"anomaly_configurations_created":"anomaly_configurations" not in before}
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="marine_observations.db");a=p.parse_args()
 with sqlite3.connect(a.database) as c:print(run_migration(c))
if __name__=="__main__":main()
