"""Additive/idempotent Phase 12A-2 SQLite migration.

This migration adds identity and applicability metadata only. It does not
alter scientific observations, occurrences, models, deployments, or outputs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone


def _table_exists(connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def run_migration(connection: sqlite3.Connection) -> dict[str, int | bool]:
    summary: dict[str, int | bool] = {
        "identity_columns_added": 0,
        "applicability_table_created": False,
        "canonical_identities_backfilled": 0,
        "jamaica_applicabilities_backfilled": 0,
    }
    with connection:
        columns = _columns(connection, "jurisdictions")
        for name, definition in (
            ("canonical_identifier_scheme", "VARCHAR(32)"),
            ("canonical_identifier", "VARCHAR(64)"),
            ("jurisdiction_type", "VARCHAR(48)"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE jurisdictions ADD COLUMN {name} {definition}")
                summary["identity_columns_added"] += 1
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_jurisdiction_canonical_identity "
            "ON jurisdictions(canonical_identifier_scheme, canonical_identifier)"
        )

        before = _table_exists(connection, "scientific_dataset_applicabilities")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS scientific_dataset_applicabilities (
                id INTEGER PRIMARY KEY,
                scientific_dataset_id INTEGER NOT NULL REFERENCES scientific_datasets(id) ON DELETE RESTRICT,
                jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id) ON DELETE RESTRICT,
                evidence_role VARCHAR(48) NOT NULL,
                applicability_status VARCHAR(24) NOT NULL DEFAULT 'PENDING_REVIEW',
                reconciliation_method VARCHAR(64) NOT NULL,
                reconciliation_version VARCHAR(64) NOT NULL,
                jurisdiction_boundary_id INTEGER REFERENCES jurisdiction_boundaries(id) ON DELETE RESTRICT,
                provenance_reference VARCHAR(512) NOT NULL,
                provenance_json TEXT NOT NULL,
                provenance_fingerprint VARCHAR(64) NOT NULL,
                reviewed_by VARCHAR(256), reviewed_at DATETIME,
                approved_by VARCHAR(256), approved_at DATETIME,
                created_at DATETIME NOT NULL,
                superseded_at DATETIME,
                CONSTRAINT uq_dataset_applicability_assertion UNIQUE (
                    scientific_dataset_id, jurisdiction_id, evidence_role, provenance_fingerprint
                )
            )
        """)
        summary["applicability_table_created"] = not before
        for column in (
            "scientific_dataset_id", "jurisdiction_id", "evidence_role",
            "applicability_status", "jurisdiction_boundary_id", "provenance_fingerprint",
        ):
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS ix_dataset_applicability_{column} "
                f"ON scientific_dataset_applicabilities({column})"
            )

        for name, code in (("Jamaica", "JM"), ("Bahamas", "BS")):
            cursor = connection.execute(
                "UPDATE jurisdictions SET canonical_identifier_scheme=?, "
                "canonical_identifier=?, jurisdiction_type=? "
                "WHERE name=? AND country_code=? AND canonical_identifier IS NULL",
                ("ISO_3166_1_ALPHA_2", code, "SOVEREIGN_STATE", name, code),
            )
            summary["canonical_identities_backfilled"] += cursor.rowcount

        jamaica = connection.execute(
            "SELECT id FROM jurisdictions WHERE canonical_identifier_scheme=? AND canonical_identifier=?",
            ("ISO_3166_1_ALPHA_2", "JM"),
        ).fetchone()
        environmental = connection.execute(
            "SELECT id FROM scientific_datasets WHERE slug=? AND geographic_scope_type='REGION'",
            ("pterois-volitans-environmental-caribbean-grid-v2-environment-v1",),
        ).fetchone()
        if jamaica and environmental:
            provenance = {
                "decision": "Preserve the existing Jamaica suitability-v3 environmental relationship only",
                "phase": "12A-2",
                "scientific_scope": "ENVIRONMENTAL_COVARIATE",
                "source_relationship": "existing Jamaica species-program environmental feature dataset",
            }
            cursor = connection.execute(
                "INSERT OR IGNORE INTO scientific_dataset_applicabilities ("
                "scientific_dataset_id,jurisdiction_id,evidence_role,applicability_status,"
                "reconciliation_method,reconciliation_version,jurisdiction_boundary_id,"
                "provenance_reference,provenance_json,provenance_fingerprint,approved_by,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    environmental[0], jamaica[0], "ENVIRONMENTAL_COVARIATE", "AUTHORIZED",
                    "LEGACY_PROVENANCE_RECONCILIATION", "phase12a2-v1", None,
                    "Phase 12A-1 audit and persisted Jamaica suitability-v3 provenance",
                    _canonical_json(provenance), _fingerprint(provenance),
                    "PHASE_12A_2_CONTROLLED_BACKFILL", datetime.now(timezone.utc).isoformat(),
                ),
            )
            summary["jamaica_applicabilities_backfilled"] += cursor.rowcount
    return summary


if __name__ == "__main__":
    connection = sqlite3.connect("marine_observations.db")
    try:
        print(json.dumps(run_migration(connection), sort_keys=True))
    finally:
        connection.close()
