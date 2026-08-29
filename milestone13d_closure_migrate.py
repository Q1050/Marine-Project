"""Additive/idempotent Milestone 13D Closure migration."""
import argparse
import sqlite3

from milestone13d_migrate_early_warning_operations import run_migration as migrate_13d

INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS uq_anomaly_active_assignment ON anomaly_review_assignments(anomaly_assessment_id) WHERE status = 'ASSIGNED'"


def run_migration(connection):
    migrate_13d(connection)
    before = connection.execute("SELECT count(1) FROM sqlite_master WHERE type='index' AND name='uq_anomaly_active_assignment'").fetchone()[0]
    with connection:
        connection.execute(INDEX)
    return {"active_assignment_unique_index_created": not bool(before)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="marine_observations.db")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        print(run_migration(connection))


if __name__ == "__main__":
    main()
