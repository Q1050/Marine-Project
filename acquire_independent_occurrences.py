"""Acquire one controlled experimental occurrence snapshot from USGS NAS.

Example (the Phase 11C-6 audit parameters)::

    python acquire_independent_occurrences.py --nas-species-id 963 \
      --nas-state JM --target-species "Pterois volitans" \
      --jurisdiction-slug jamaica --output artifacts/experimental_validation/usgs-nas-963-jm.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import requests
from shapely.geometry import shape

from database import SessionLocal
from independent_occurrence_source import (
    CandidateOccurrence, SourceProvenance, audit_candidate,
    build_controlled_artifact, summarize_audit, write_controlled_artifact,
)
from models import HistoricalOccurrence, Jurisdiction, JurisdictionBoundary
from anomaly_repository import canonical_json


NAS_API = "https://nas.er.usgs.gov/api/v2/occurrence/search"


def acquire(args):
    response = requests.get(NAS_API, params={
        "species_ID": args.nas_species_id, "state": args.nas_state,
        "limit": args.limit, "offset": 0,
    }, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("endOfRecords", "false")).casefold() != "true":
        raise RuntimeError("Controlled acquisition is incomplete; increase --limit")
    raw_rows = payload.get("results", [])

    db = SessionLocal()
    try:
        jurisdiction = db.query(Jurisdiction).filter_by(slug=args.jurisdiction_slug).one()
        boundary = db.query(JurisdictionBoundary).filter_by(
            jurisdiction_id=jurisdiction.id, status="ACTIVE"
        ).one()
        calibration = db.query(HistoricalOccurrence).filter_by(
            scientific_name=args.target_species
        ).order_by(HistoricalOccurrence.id).all()
        geometry = shape(json.loads(boundary.geometry_json))
        candidates = []
        for row in raw_rows:
            references = row.get("references") or []
            candidate = CandidateOccurrence(
                provider_record_id=str(row["key"]),
                scientific_name=row.get("scientificName") or "",
                latitude=row.get("decimalLatitude"), longitude=row.get("decimalLongitude"),
                event_date=row.get("date"),
                upstream_occurrence_id=row.get("UUID") or None,
                authoritative_id=f"USGS-NAS:{row['key']}",
                source_reference_ids=tuple(str(item.get("key")) for item in references if item.get("key") is not None),
                source_reference_titles=tuple(str(item.get("title") or item.get("author") or "") for item in references),
                raw_provenance_json=canonical_json({
                    "record_type": row.get("recordType"), "state": row.get("state"),
                    "locality": row.get("locality"), "spatial_accuracy": row.get("latLongAccuracy"),
                    "coordinate_source": row.get("latLongSource"), "references": references,
                }),
                independence_basis_verified=False,
            )
            candidates.append(audit_candidate(candidate, calibration, args.target_species, geometry))
        retrieved_at = datetime.now(timezone.utc).isoformat()
        provenance = SourceProvenance(
            provider="USGS Nonindigenous Aquatic Species Database",
            dataset_name=f"NAS taxon {args.nas_species_id}, state {args.nas_state}",
            source_reference=NAS_API,
            acquisition_method="USGS_NAS_V2_OCCURRENCE_SEARCH_API",
            acquisition_parameters_json=canonical_json({
                "species_ID": args.nas_species_id, "state": args.nas_state,
                "limit": args.limit, "offset": 0,
            }),
            retrieved_at=retrieved_at,
            taxon_representation=raw_rows[0].get("scientificName", "") if raw_rows else "",
            geographic_scope=f"source state code {args.nas_state}; reconciled to jurisdiction {jurisdiction.id}",
            usage_constraints=(
                "USGS NAS disclaimer applies; accuracy, completeness, scale, and origin vary. "
                "Contact USGS for publication use guidance."
            ),
            role="CONTEXTUAL_VALIDATION_CANDIDATE",
        )
        artifact = build_controlled_artifact(provenance, candidates)
        path, file_sha = write_controlled_artifact(artifact, args.output)
        return {**summarize_audit(candidates), "artifact_path": str(path),
                "content_fingerprint": artifact.content_sha256, "file_sha256": file_sha,
                "source_taxon": provenance.taxon_representation,
                "validation_role": provenance.role}
    finally:
        db.close()


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--nas-species-id", type=int, required=True)
    result.add_argument("--nas-state", required=True)
    result.add_argument("--target-species", required=True)
    result.add_argument("--jurisdiction-slug", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--limit", type=int, default=5000)
    return result


if __name__ == "__main__":
    print(json.dumps(acquire(parser().parse_args()), indent=2, sort_keys=True))
