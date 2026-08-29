"""Additive/idempotent Phase 12C-3 occurrence-review migration."""
import argparse, sqlite3

REVIEW_SQL="""
CREATE TABLE occurrence_candidate_reviews (
 id INTEGER PRIMARY KEY,
 preparation_id INTEGER NOT NULL REFERENCES occurrence_acquisition_preparations(id) ON DELETE RESTRICT,
 candidate_id INTEGER NOT NULL REFERENCES occurrence_candidate_records(id) ON DELETE RESTRICT,
 disposition VARCHAR(48) NOT NULL,
 reason_code VARCHAR(64) NOT NULL,
 evidence_note TEXT,
 reviewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 reviewed_at DATETIME NOT NULL,
 dependency_fingerprint VARCHAR(64) NOT NULL,
 source_license_json TEXT NOT NULL,
 provenance_json TEXT NOT NULL,
 review_fingerprint VARCHAR(64) NOT NULL UNIQUE,
 resulting_evidence_id INTEGER REFERENCES governed_occurrence_evidence(id) ON DELETE RESTRICT
);
CREATE INDEX ix_occurrence_candidate_reviews_preparation_id ON occurrence_candidate_reviews(preparation_id);
CREATE INDEX ix_occurrence_candidate_reviews_candidate_id ON occurrence_candidate_reviews(candidate_id);
CREATE INDEX ix_occurrence_candidate_reviews_disposition ON occurrence_candidate_reviews(disposition);
"""
LINK_SQL="""
CREATE TABLE occurrence_legacy_links (
 id INTEGER PRIMARY KEY,
 preparation_id INTEGER NOT NULL REFERENCES occurrence_acquisition_preparations(id) ON DELETE RESTRICT,
 candidate_id INTEGER NOT NULL REFERENCES occurrence_candidate_records(id) ON DELETE RESTRICT,
 historical_occurrence_id INTEGER NOT NULL REFERENCES historical_occurrences(id) ON DELETE RESTRICT,
 overlap_basis VARCHAR(128) NOT NULL,
 provider_occurrence_id VARCHAR(512),
 upstream_occurrence_id VARCHAR(512),
 candidate_provenance_fingerprint VARCHAR(64) NOT NULL,
 link_fingerprint VARCHAR(64) NOT NULL UNIQUE,
 created_at DATETIME NOT NULL,
 CONSTRAINT uq_occurrence_legacy_link UNIQUE(candidate_id,historical_occurrence_id,overlap_basis)
);
CREATE INDEX ix_occurrence_legacy_links_preparation_id ON occurrence_legacy_links(preparation_id);
CREATE INDEX ix_occurrence_legacy_links_candidate_id ON occurrence_legacy_links(candidate_id);
CREATE INDEX ix_occurrence_legacy_links_historical_occurrence_id ON occurrence_legacy_links(historical_occurrence_id);
"""

def _exists(connection,name):return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
def run_migration(connection):
 result={"review_table_created":False,"legacy_link_table_created":False}
 if not _exists(connection,"occurrence_candidate_reviews"):connection.executescript(REVIEW_SQL);result["review_table_created"]=True
 if not _exists(connection,"occurrence_legacy_links"):connection.executescript(LINK_SQL);result["legacy_link_table_created"]=True
 connection.commit();return result
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args()
 with sqlite3.connect(args.database) as connection:print(run_migration(connection))
if __name__=="__main__":main()
