import hashlib
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import *
from phase12b5_migrate_taxon_manifests import run_migration
from regional_taxon_manifest_service import RegionalTaxonManifestService, canonicalize_manifest
from taxonomy_provider import TaxonomyProvider, TaxonomyRecord


class ManifestProvider(TaxonomyProvider):
    def __init__(self, root): self.root = root
    def resolve_name(self, name): return name
    def fetch_taxon(self, identifier): return {}
    def fetch_classification(self, identifier): return {}
    def acquire(self, name):
        if "/" in name: raise ValueError("Ambiguous identity")
        rank = "GENUS" if name == "Pterois" else "SPECIES"
        synonym = name == "Gasterosteus volitans"
        identifier = "301175" if synonym else ("159559" if name == "Pterois volitans" else str(800000 + int(hashlib.sha256(name.encode()).hexdigest()[:6], 16)))
        accepted = "159559" if synonym else identifier
        path = self.root / f"{identifier}.json"; path.write_text(name, encoding="utf-8"); digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return TaxonomyRecord("WoRMS", "WORMS_APHIA_ID", identifier, name, "Pterois volitans" if synonym else name, "Authority", rank, "SYNONYM" if synonym else "ACCEPTED", accepted, "204051", "Pterois", (), "fixture-v1", f"https://example.test/{identifier}"), path, digest, digest


@pytest.fixture()
def manifest_db(tmp_path):
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine); session = sessionmaker(bind=engine)()
    region = Region(name="Caribbean", slug="caribbean", status="ACTIVE"); admin = User(email="admin@example.test", display_name="Admin", password_hash="x", is_platform_admin=True)
    session.add_all([region, admin]); session.flush()
    pterois = Species(scientific_name="Pterois volitans", aphia_id=159559, authoritative_identifier_scheme="WORMS_APHIA_ID", authoritative_identifier="159559", taxonomic_rank="SPECIES", accepted_name_status="ACCEPTED", provenance_fingerprint="a" * 64)
    session.add(pterois); session.flush(); session.add(RegionalTaxonRegistry(region_id=region.id, taxon_id=pterois.id, registry_version="v1", inclusion_basis="reviewed", source_references_json="[]", review_status="APPROVED", provenance_json="{}", provenance_fingerprint="b" * 64)); session.commit()
    yield session, tmp_path, admin, region
    session.close()


def manifest(region_id, names, manifest_id="catalog-1"):
    return {"manifest_id": manifest_id, "manifest_version": "1.0", "region_id": region_id, "operator_reference": "review-pool-1", "provenance": {"source": "curated-test"}, "limitations": ["Review input only"], "candidates": [{"submitted_scientific_name": name, "source_reference": "fixture"} for name in names]}


def test_manifest_fingerprint_and_duplicate_refusal(manifest_db):
    session, _, _, region = manifest_db
    first, first_hash = canonicalize_manifest(manifest(region.id, ["Species beta", "Species alpha"]))
    second, second_hash = canonicalize_manifest(manifest(region.id, ["Species alpha", "Species beta"]))
    assert first == second and first_hash == second_hash and len(first_hash) == 64
    with pytest.raises(ValueError, match="Duplicate candidate"):
        canonicalize_manifest(manifest(region.id, ["Species alpha", " Species   alpha "]))


def test_mixed_preflight_is_zero_write_and_explicit(manifest_db):
    session, root, _, region = manifest_db; service = RegionalTaxonManifestService(session, ManifestProvider(root))
    before = {model: session.query(model).count() for model in (Species, RegionalTaxonRegistry, LocalTaxonCandidate, TaxonomyPreparation, SpeciesProgram, HistoricalOccurrence, AnomalyAssessment)}
    result = service.preflight(manifest(region.id, ["Pterois volitans", "Species alpha", "Pterois", "Pterois volitans/miles"]))
    statuses = {item["candidate"]["submitted_scientific_name"]: item["status"] for item in result["results"]}
    assert statuses == {"Pterois volitans": "ALREADY_GOVERNED", "Species alpha": "CREATE_LOCAL_TAXON_CANDIDATE", "Pterois": "UNSUPPORTED_RANK", "Pterois volitans/miles": "AMBIGUOUS"}
    assert result["scientific_firewall"]["status"] == "PASS"
    assert before == {model: session.query(model).count() for model in before}


def test_prepare_approve_partial_apply_retry_and_idempotency(manifest_db):
    session, root, admin, region = manifest_db; service = RegionalTaxonManifestService(session, ManifestProvider(root))
    prepared = service.prepare(manifest(region.id, ["Species alpha", "Species beta"]), admin.id)
    assert prepared["execution_state"] == "PREPARED" and len(prepared["items"]) == 2 and session.query(Species).count() == 1
    ids = [item["id"] for item in prepared["items"]]; assert all(item["workflow_state"] == "READY_FOR_REVIEW" for item in prepared["items"])
    assert all(result["status"] == "APPROVED" for result in service.approve(prepared["id"], ids, admin.id, "approval-1")["results"])
    broken = session.get(LocalTaxonCandidate, prepared["items"][1]["local_taxon_candidate_id"]); open(broken.provider_artifact_reference, "w", encoding="utf-8").write("changed")
    applied = service.apply(prepared["id"], ids); assert [result["status"] for result in applied["results"]] == ["APPLIED", "FAILED"] and applied["scientific_firewall"]["status"] == "PASS"
    original = broken.canonical_scientific_name; open(broken.provider_artifact_reference, "w", encoding="utf-8").write(original)
    retried = service.apply(prepared["id"], [ids[1]], retry=True); assert retried["results"][0]["status"] == "APPLIED"
    assert service.apply(prepared["id"], ids)["results"][0]["status"] == "NO-OP"
    assert service.prepare(manifest(region.id, ["Species alpha", "Species beta"]), admin.id)["rerun_status"] == "NO-OP"


def test_synonym_review_dependency_and_pterois_noop(manifest_db):
    session, root, admin, region = manifest_db; service = RegionalTaxonManifestService(session, ManifestProvider(root))
    preflight = service.preflight(manifest(region.id, ["Pterois volitans", "Gasterosteus volitans"], "synonyms"))
    statuses = {item["candidate"]["submitted_scientific_name"]: item["status"] for item in preflight["results"]}
    assert statuses == {"Pterois volitans": "ALREADY_GOVERNED", "Gasterosteus volitans": "CREATE_LOCAL_TAXON_CANDIDATE"}
    prepared = service.prepare(manifest(region.id, ["Pterois volitans", "Gasterosteus volitans"], "synonyms"), admin.id)
    by_name = {item["submitted_identity"]["submitted_scientific_name"]: item for item in prepared["items"]}
    assert by_name["Pterois volitans"]["workflow_state"] == "NO-OP" and by_name["Gasterosteus volitans"]["proposed_action"] == "CREATE_LOCAL_TAXON_CANDIDATE"


def test_reasonable_synthetic_scale_and_firewall(manifest_db):
    session, root, _, region = manifest_db; service = RegionalTaxonManifestService(session, ManifestProvider(root)); names = [f"Synthetic species {index}" for index in range(40)]
    result = service.preflight(manifest(region.id, names, "scale-40"))
    assert result["summary"]["total"] == 40 and result["summary"]["cleanly_resolvable"] == 40 and result["scientific_firewall"]["status"] == "PASS"


def test_migration_idempotency(tmp_path):
    connection = sqlite3.connect(tmp_path / "migration.db"); connection.executescript("CREATE TABLE regions(id INTEGER PRIMARY KEY); CREATE TABLE users(id INTEGER PRIMARY KEY); CREATE TABLE species(id INTEGER PRIMARY KEY); CREATE TABLE regional_taxon_registry(id INTEGER PRIMARY KEY); CREATE TABLE taxonomy_preparations(id INTEGER PRIMARY KEY); CREATE TABLE local_taxon_candidates(id INTEGER PRIMARY KEY);")
    assert run_migration(connection) == {"runs_created": True, "items_created": True}
    assert run_migration(connection) == {"runs_created": False, "items_created": False}


def test_manifest_admin_endpoint_requires_platform_admin():
    from fastapi.testclient import TestClient
    from api import app
    assert TestClient(app).post("/admin/taxonomy/manifests/preflight", json={}).status_code == 401
