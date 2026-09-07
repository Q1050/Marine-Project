"""Build and optionally prepare the small governed-review Milestone 20 manifest."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from taxonomy_provider import WoRMSTaxonomyProvider

GROUPS = {
    "FISH": ["Pterois volitans", "Pterois miles", "Acanthurus coeruleus", "Scarus iseri", "Haemulon flavolineatum"],
    "CRUSTACEANS": ["Panulirus argus", "Callinectes sapidus", "Mithraculus sculptus", "Stenopus hispidus"],
    "MOLLUSCS": ["Perna viridis", "Aliger gigas", "Octopus briareus", "Dendostrea frons"],
    "CNIDARIANS": ["Acropora palmata", "Orbicella annularis", "Cassiopea xamachana", "Diploria labyrinthiformis"],
    "ECHINODERMS": ["Diadema antillarum", "Holothuria mexicana", "Oreaster reticulatus", "Echinometra lucunter"],
    "ALGAE_SEAWEED": ["Caulerpa taxifolia", "Halimeda opuntia", "Sargassum natans", "Gracilaria tikvahiae"],
}
OUTPUT = Path("artifacts/taxonomy/manifests/caribbean-buildathon-multitaxon-v1.json")


def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build():
    provider = WoRMSTaxonomyProvider(); candidates = []
    for group, names in GROUPS.items():
        for name in names:
            record, artifact, artifact_sha, content_fingerprint = provider.acquire(name)
            candidates.append({
                "group": group, "scientific_name": record.scientific_name,
                "accepted_scientific_name": record.accepted_scientific_name,
                "aphia_id": int(record.identifier), "rank": record.rank,
                "status": record.status, "authorship": record.authorship,
                "parent": {"aphia_id": record.parent_identifier, "scientific_name": record.parent_name},
                "lineage": list(record.classification), "source_reference": record.provider_reference,
                "provider_artifact": str(artifact), "provider_artifact_sha256": artifact_sha,
                "provider_content_fingerprint": content_fingerprint, "review_state": "READY_FOR_REVIEW",
            })
    body = {
        "manifest_id": "caribbean-buildathon-multitaxon", "manifest_version": "1",
        "purpose": "Small six-group Caribbean regional taxonomy candidate set for explicit human review",
        "authority": {"provider": provider.PROVIDER, "provider_version": provider.VERSION, "api": provider.BASE},
        "semantics": "Regional catalog candidacy does not establish jurisdiction presence or ecological status.",
        "candidates": candidates,
        "limitations": ["Human approval and apply are required.", "No occurrence, ecological status, media eligibility, model, or anomaly state is implied."],
    }
    body["manifest_fingerprint"] = hashlib.sha256(canonical(body).encode()).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return body


def prepare(body):
    from database import SessionLocal
    from models import Region, User
    from regional_taxon_manifest_service import RegionalTaxonManifestService
    with SessionLocal() as session:
        region = session.query(Region).filter_by(slug="caribbean").one()
        admin = session.query(User).filter_by(is_platform_admin=True).order_by(User.id).first()
        if not admin: raise RuntimeError("A real platform administrator is required")
        candidates = [{
            "submitted_scientific_name": row["scientific_name"], "submitted_identifier_scheme": "WORMS_APHIA_ID",
            "submitted_identifier": str(row["aphia_id"]), "candidate_source": "BUILDATHON_REGIONAL_CANDIDATE_MANIFEST",
            "source_reference": row["source_reference"], "source_artifact_reference": row["provider_artifact"],
            "discovery_method": "CURATED_CROSS_GROUP_DEMONSTRATION_SET", "discovery_version": body["manifest_version"],
            "provenance": {"group": row["group"], "artifact_sha256": row["provider_artifact_sha256"], "content_fingerprint": row["provider_content_fingerprint"]},
            "limitations": body["limitations"],
        } for row in body["candidates"]]
        payload = {"manifest_id": body["manifest_id"], "manifest_version": body["manifest_version"], "region_id": region.id,
                   "operator_reference": "Milestone 20 preparation only; human approval and apply not performed",
                   "provenance": {"source_artifact": str(OUTPUT), "manifest_fingerprint": body["manifest_fingerprint"]},
                   "limitations": body["limitations"], "configuration": {"provider_resolution": "WORMS_EXACT_SPECIES"}, "candidates": candidates}
        return RegionalTaxonManifestService(session).prepare(payload, admin.id)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--prepare", action="store_true"); args = parser.parse_args()
    body = build(); result = {"artifact": str(OUTPUT), "candidates": len(body["candidates"]), "groups": {key: len(value) for key, value in GROUPS.items()}, "fingerprint": body["manifest_fingerprint"], "production_approved": 0, "production_applied": 0}
    if args.prepare:
        run = prepare(body); result.update({"run_id": run["id"], "execution_state": run["execution_state"], "summary": run["summary"]})
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__": main()
