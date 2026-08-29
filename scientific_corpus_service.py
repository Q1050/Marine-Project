"""Provider-neutral scientific corpus intake and descriptive projections.

This module deliberately stops at parsing, normalization and readiness.  It
does not assert jurisdiction presence, ecology, or model/anomaly eligibility.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter

from jurisdiction_boundary_registry import canonical_json


CORPUS_VERSION = "caribbean-scientific-corpus-v1"
MAX_MANIFEST_ITEMS = 10_000
TAXON_GROUPS = ("FISH", "ALGAE_SEAWEED", "CRUSTACEANS", "MOLLUSCS", "CNIDARIANS", "ECHINODERMS", "OTHER")
LINEAGE_GROUPS = {
    "FISH": {"actinopterygii", "chondrichthyes", "myxini", "petromyzontida"},
    "ALGAE_SEAWEED": {"rhodophyta", "chlorophyta", "ochrophyta", "phaeophyceae"},
    "CRUSTACEANS": {"crustacea", "malacostraca", "maxillopoda", "branchiopoda"},
    "MOLLUSCS": {"mollusca"},
    "CNIDARIANS": {"cnidaria"},
    "ECHINODERMS": {"echinodermata"},
}


def derive_taxonomic_group(lineage):
    """Return a descriptive UI group from governed authoritative lineage."""
    names = {str(node.get("scientific_name") or node.get("name") or "").strip().casefold() for node in lineage or []}
    for group, markers in LINEAGE_GROUPS.items():
        if names & markers:
            return {"group": group, "basis": "AUTHORITATIVE_TAXONOMIC_LINEAGE"}
    return {"group": "OTHER", "basis": "INSUFFICIENT_GOVERNED_LINEAGE"}


def _normalize_row(row, ordinal):
    aliases = {str(k).strip().casefold(): v for k, v in row.items() if k is not None}
    name = aliases.get("submitted_scientific_name") or aliases.get("scientific_name") or aliases.get("species")
    if not name or not str(name).strip():
        raise ValueError(f"Row {ordinal} has no scientific_name")
    identifier = aliases.get("submitted_identifier") or aliases.get("authoritative_identifier") or aliases.get("aphia_id")
    scheme = aliases.get("submitted_identifier_scheme") or aliases.get("authoritative_identifier_scheme")
    if aliases.get("aphia_id") and not scheme:
        scheme = "APHIA_ID"
    return {
        "submitted_scientific_name": " ".join(str(name).split()),
        "submitted_identifier_scheme": str(scheme).strip().upper() if scheme else None,
        "submitted_identifier": str(identifier).strip() if identifier not in (None, "") else None,
        "candidate_source": str(aliases.get("candidate_source") or "ADMIN_MANIFEST"),
        "source_reference": aliases.get("source_reference"),
        "provenance": {"input_ordinal": ordinal, "corpus_version": CORPUS_VERSION},
        "limitations": ["Candidate intake is not jurisdiction occurrence or ecological-status evidence."],
    }


def parse_manifest_content(content, input_format):
    """Parse pasted text, CSV, or JSON without performing scientific writes."""
    fmt = str(input_format or "PASTED_NAMES").strip().upper()
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Manifest content is required")
    if len(content.encode("utf-8")) > 5_000_000:
        raise ValueError("Manifest content exceeds the 5 MB intake limit")
    if fmt == "PASTED_NAMES":
        rows = [{"scientific_name": line} for line in content.splitlines() if line.strip()]
    elif fmt == "CSV":
        rows = list(csv.DictReader(io.StringIO(content)))
    elif fmt == "JSON":
        decoded = json.loads(content)
        if isinstance(decoded, dict) and "candidates" not in decoded and "items" not in decoded:
            raise ValueError("JSON manifest must be an array or contain candidates/items array")
        rows = decoded.get("candidates", decoded.get("items", [])) if isinstance(decoded, dict) else decoded
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("JSON manifest must be an array or contain candidates/items array")
    else:
        raise ValueError("input_format must be PASTED_NAMES, CSV, or JSON")
    if not rows:
        raise ValueError("Manifest contains no candidate rows")
    if len(rows) > MAX_MANIFEST_ITEMS:
        raise ValueError(f"Manifest exceeds {MAX_MANIFEST_ITEMS} candidates")
    candidates, errors, seen = [], [], set()
    for ordinal, row in enumerate(rows, 1):
        try:
            candidate = _normalize_row(row, ordinal)
            key = (candidate["submitted_identifier_scheme"], candidate["submitted_identifier"]) if candidate["submitted_identifier"] else ("NAME", candidate["submitted_scientific_name"].casefold())
            if key in seen:
                errors.append({"row": ordinal, "code": "DUPLICATE_INPUT_IDENTITY"})
                continue
            seen.add(key); candidates.append(candidate)
        except ValueError as exc:
            errors.append({"row": ordinal, "code": "INVALID_ROW", "detail": str(exc)})
    canonical = canonical_json(candidates)
    return {"input_format": fmt, "parser_version": CORPUS_VERSION, "source_rows": len(rows), "accepted_rows": len(candidates),
            "rejected_rows": len(errors), "content_fingerprint": hashlib.sha256(canonical.encode()).hexdigest(),
            "candidates": candidates, "errors": errors,
            "semantics": "Candidate parsing performs no taxonomy approval and creates no jurisdiction science."}


def paginate(items, page=1, page_size=100):
    size = min(max(int(page_size), 1), 500); number = max(int(page), 1); start = (number - 1) * size
    return {"page": number, "page_size": size, "total": len(items), "items": items[start:start + size]}


def batch_progress(items):
    counts = Counter(str(item.get("workflow_state") or item.get("status") or "UNKNOWN") for item in items)
    return {"total": len(items), "states": dict(sorted(counts.items())), "failed": counts.get("FAILED", 0),
            "resumable": counts.get("FAILED", 0) + counts.get("READY_FOR_REVIEW", 0) + counts.get("APPROVED", 0)}


def storage_contract():
    return {"metadata_system_of_record": "POSTGRESQL", "blob_strategy": "HASH_ADDRESSED_EXTERNAL_OR_CONTROLLED_LOCAL",
            "artifact_identity": "SHA256", "database_blob_storage": False, "object_storage_ready": True,
            "accepted_manifest_formats": ["PASTED_NAMES", "CSV", "JSON"], "maximum_manifest_bytes": 5_000_000,
            "semantics": "ArtifactReference stores metadata; large source/media bytes remain outside PostgreSQL."}
