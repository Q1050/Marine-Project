import json
from collections import Counter
from pathlib import Path


MANIFEST = Path("artifacts/taxonomy/manifests/caribbean-buildathon-multitaxon-v1.json")


def test_buildathon_manifest_is_small_multitaxon_and_review_only():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidates = payload["candidates"]
    assert 20 <= len(candidates) <= 30
    assert Counter(row["group"] for row in candidates) == {
        "FISH": 5,
        "CRUSTACEANS": 4,
        "MOLLUSCS": 4,
        "CNIDARIANS": 4,
        "ECHINODERMS": 4,
        "ALGAE_SEAWEED": 4,
    }
    assert len({row["aphia_id"] for row in candidates}) == len(candidates)
    assert len({row["accepted_scientific_name"] for row in candidates}) == len(candidates)
    assert all(row["review_state"] == "READY_FOR_REVIEW" for row in candidates)
    assert "does not establish jurisdiction presence" in payload["semantics"]
    assert all(row["provider_artifact_sha256"] for row in candidates)


def test_manifest_contains_no_scientific_approval_or_jurisdiction_claim():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert '"APPROVED"' not in serialized
    assert '"APPLIED"' not in serialized
    assert '"INVASIVE"' not in serialized
    assert '"jurisdiction_id"' not in serialized

