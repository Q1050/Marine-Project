"""Additive, idempotent Phase 11B-1 anomaly-domain schema migration.

This migration creates only the two persistence tables required by the anomaly
domain foundation. It neither evaluates observations nor inserts anomaly rows.
"""

from __future__ import annotations

import argparse
import sqlite3


ASSESSMENTS_SQL = """
CREATE TABLE IF NOT EXISTS anomaly_assessments (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE RESTRICT,
    jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT,
    species_program_id INTEGER REFERENCES species_programs(id) ON DELETE RESTRICT,
    evaluated_species VARCHAR,
    evaluated_species_source VARCHAR,
    overall_status VARCHAR NOT NULL,
    overall_classification VARCHAR,
    assessment_confidence VARCHAR NOT NULL,
    requires_review BOOLEAN NOT NULL DEFAULT 0,
    review_type VARCHAR NOT NULL DEFAULT 'NO_REVIEW',
    provenance_version VARCHAR NOT NULL,
    dependency_fingerprint VARCHAR,
    current_state VARCHAR NOT NULL DEFAULT 'CURRENT',
    generated_at DATETIME NOT NULL,
    invalidated_at DATETIME,
    superseded_at DATETIME,
    evidence_summary_json TEXT,
    limitations_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
)
"""

SIGNALS_SQL = """
CREATE TABLE IF NOT EXISTS anomaly_signals (
    id INTEGER PRIMARY KEY,
    anomaly_assessment_id INTEGER NOT NULL
        REFERENCES anomaly_assessments(id) ON DELETE CASCADE,
    signal_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    anomaly_strength VARCHAR,
    evidence_confidence VARCHAR NOT NULL,
    evidence_summary_json TEXT,
    limitations_json TEXT NOT NULL,
    source_dataset_ids_json TEXT,
    suitability_deployment_id INTEGER
        REFERENCES suitability_deployments(id) ON DELETE RESTRICT,
    supporting_observation_ids_json TEXT,
    generated_at DATETIME NOT NULL,
    provenance_version VARCHAR NOT NULL,
    CONSTRAINT uq_anomaly_signal_assessment_type
        UNIQUE (anomaly_assessment_id, signal_type)
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_anomaly_assessments_observation_id ON anomaly_assessments(observation_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_assessments_jurisdiction_id ON anomaly_assessments(jurisdiction_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_assessments_species_program_id ON anomaly_assessments(species_program_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_assessments_current_state ON anomaly_assessments(current_state)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_signals_assessment_id ON anomaly_signals(anomaly_assessment_id)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_signals_signal_type ON anomaly_signals(signal_type)",
    "CREATE INDEX IF NOT EXISTS ix_anomaly_signals_suitability_deployment_id ON anomaly_signals(suitability_deployment_id)",
)


def run_migration(connection: sqlite3.Connection) -> dict[str, bool]:
    before = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    with connection:
        connection.execute(ASSESSMENTS_SQL)
        connection.execute(SIGNALS_SQL)
        for statement in INDEXES:
            connection.execute(statement)
    return {
        "anomaly_assessments_created": "anomaly_assessments" not in before,
        "anomaly_signals_created": "anomaly_signals" not in before,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="marine_observations.db")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        print(run_migration(connection))


if __name__ == "__main__":
    main()
