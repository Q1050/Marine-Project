"""Additive, idempotent Phase 11B-7 synthesis-snapshot migration."""

from __future__ import annotations

import argparse
import sqlite3


TABLE_SQL = """
CREATE TABLE IF NOT EXISTS anomaly_synthesis_snapshots (
    id INTEGER PRIMARY KEY,
    anomaly_assessment_id INTEGER NOT NULL
        REFERENCES anomaly_assessments(id) ON DELETE RESTRICT,
    observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE RESTRICT,
    jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT,
    synthesis_rules_version VARCHAR NOT NULL,
    dependency_fingerprint VARCHAR(64) NOT NULL,
    synthesis_fingerprint VARCHAR(64) NOT NULL,
    overall_status VARCHAR NOT NULL,
    overall_classification VARCHAR,
    requires_review BOOLEAN NOT NULL DEFAULT 0,
    review_type VARCHAR NOT NULL,
    assessment_confidence VARCHAR NOT NULL,
    provenance_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_anomaly_synthesis_assessment_rules_fingerprint UNIQUE (
        anomaly_assessment_id, synthesis_rules_version, synthesis_fingerprint
    )
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_anomaly_synthesis_assessment_id ON anomaly_synthesis_snapshots(anomaly_assessment_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_synthesis_observation_id ON anomaly_synthesis_snapshots(observation_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_synthesis_jurisdiction_id ON anomaly_synthesis_snapshots(jurisdiction_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_synthesis_rules_version ON anomaly_synthesis_snapshots(synthesis_rules_version)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_synthesis_fingerprint ON anomaly_synthesis_snapshots(synthesis_fingerprint)",
)


def run_migration(connection: sqlite3.Connection) -> dict[str, bool]:
    existed = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='anomaly_synthesis_snapshots'"
    ).fetchone() is not None
    with connection:
        connection.execute(TABLE_SQL)
        for statement in INDEXES:
            connection.execute(statement)
    return {"anomaly_synthesis_snapshots_created": not existed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="marine_observations.db")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        print(run_migration(connection))


if __name__ == "__main__":
    main()
