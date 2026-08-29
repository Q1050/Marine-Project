import json

import pytest
from sqlalchemy import event

from regional_scientific_scaling import RegionalScientificScalingService
from scientific_corpus_service import (
    TAXON_GROUPS, batch_progress, derive_taxonomic_group, paginate,
    parse_manifest_content, storage_contract,
)
from test_milestone13b_scientific_scaling import seed, session


def test_manifest_parsers_are_deterministic_and_provider_neutral():
    pasted = parse_manifest_content("Pterois volitans\nPerna viridis", "PASTED_NAMES")
    csv_result = parse_manifest_content("scientific_name,aphia_id\nPterois volitans,159559", "CSV")
    json_result = parse_manifest_content(json.dumps({"candidates": [{"scientific_name": "Pterois volitans", "aphia_id": 159559}]}), "JSON")
    assert pasted["accepted_rows"] == 2 and pasted["rejected_rows"] == 0
    assert csv_result["candidates"][0]["submitted_identifier_scheme"] == "APHIA_ID"
    assert csv_result["content_fingerprint"] == json_result["content_fingerprint"]
    assert "no taxonomy approval" in pasted["semantics"]


def test_manifest_duplicate_and_malformed_rows_are_explicit():
    result = parse_manifest_content("scientific_name\nPterois volitans\n Pterois  volitans ", "CSV")
    assert result["accepted_rows"] == 1 and result["errors"] == [{"row": 2, "code": "DUPLICATE_INPUT_IDENTITY"}]
    with pytest.raises(ValueError, match="array"):
        parse_manifest_content('{"bad": true}', "JSON")


def test_descriptive_groups_require_authoritative_lineage():
    assert derive_taxonomic_group([{"rank": "class", "scientific_name": "Actinopterygii"}])["group"] == "FISH"
    assert derive_taxonomic_group([{"rank": "phylum", "scientific_name": "Mollusca"}])["group"] == "MOLLUSCS"
    assert derive_taxonomic_group([]) == {"group": "OTHER", "basis": "INSUFFICIENT_GOVERNED_LINEAGE"}
    assert set(TAXON_GROUPS) == {"FISH", "ALGAE_SEAWEED", "CRUSTACEANS", "MOLLUSCS", "CNIDARIANS", "ECHINODERMS", "OTHER"}


def test_batch_progress_pagination_and_storage_contract():
    rows = [{"workflow_state": state} for state in ("READY_FOR_REVIEW", "FAILED", "APPLIED")]
    assert batch_progress(rows)["resumable"] == 2
    assert paginate(list(range(600)), 2, 500) == {"page": 2, "page_size": 500, "total": 600, "items": list(range(500, 600))}
    contract = storage_contract()
    assert contract["metadata_system_of_record"] == "POSTGRESQL" and contract["database_blob_storage"] is False


def test_40k_projection_is_batched_categorical_and_read_only():
    db = session(); region, _, _ = seed(db, jurisdictions=40, taxa=1000)
    statements = 0
    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def count_queries(*_args):
        nonlocal statements; statements += 1
    result = RegionalScientificScalingService(db).matrix(region.id, page=1, page_size=100)
    assert result["total"] == 40_000 and len(result["items"]) == 100 and statements < 30
    dimensions = result["items"][0]["dimensions"]
    for name in ("taxonomy", "occurrence", "ecology", "public_directory", "imagery", "identification", "environmental", "suitability", "early_warning"):
        assert dimensions[name]["state"] in {"READY", "PARTIAL", "BLOCKED", "NOT_APPLICABLE", "REVIEW_REQUIRED", "UNKNOWN"}
    assert "percentage" not in json.dumps(result).casefold()


def test_corpus_admin_contract_is_platform_admin_only():
    from api import app
    paths = {route.path: route for route in app.routes if hasattr(route, "dependant")}
    for path in ("/admin/scientific-corpus/manifests/parse", "/admin/scientific-corpus/contract"):
        assert "require_platform_admin" in {dependency.call.__name__ for dependency in paths[path].dependant.dependencies}
