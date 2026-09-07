import json
import pytest
from sqlalchemy import create_engine

from database import Base
from identification_corpus_service import IdentificationCorpusService, LocalArtifactStore
from media_taxonomy_resolution_service import MediaTaxonomyResolutionService
from milestone19_migrate_taxonomy_resolution import migrate
from models import IdentificationMediaReviewEvent, IdentificationMediaTaxonomyEvidence, IdentificationMediaTaxonomyResolution
from test_milestone17_visual_corpus import active_source, asset_payload, db, png, seed


class FixtureCommons:
    def __init__(self, scientific_name="Pterois volitans"): self.scientific_name = scientific_name
    def fetch(self, page_id, timeout=15):
        return {"commons_page_id": page_id, "description": f"{self.scientific_name} reference", "provider_identification_state": "COMMONS_STRUCTURED_METADATA", "inaturalist_photo_reference": "https://www.inaturalist.org/photos/42"}


def taxonomy_asset(tmp_path):
    session = db(); user, _, taxa = seed(session); source = active_source(session, user)
    payload = asset_payload(source, taxa[0]); payload["source_metadata"] = {"commons_page_id": 42}; payload["taxonomic_linkage"] = "REVIEW_REQUIRED"
    asset = IdentificationCorpusService(session, LocalArtifactStore(tmp_path)).create_candidate(payload, user.id, data=png())
    IdentificationCorpusService(session).review(asset, "TAXONOMY_REVIEW_REQUIRED", user.id, "search context is insufficient")
    return session, user, asset


def test_migration_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert migrate(engine)["tables_created"] == []
    assert migrate(engine)["tables_created"] == []


def test_evidence_acquisition_is_idempotent_and_does_not_approve(tmp_path):
    session, _, asset = taxonomy_asset(tmp_path); service = MediaTaxonomyResolutionService(session)
    first = service.acquire_commons_evidence(asset, FixtureCommons()); second = service.acquire_commons_evidence(asset, FixtureCommons())
    assert first.id == second.id
    assert asset.review_state == "TAXONOMY_REVIEW_REQUIRED"
    assert session.query(IdentificationMediaTaxonomyEvidence).count() == 1


def test_human_resolution_is_append_only_and_preserves_original_review(tmp_path):
    session, user, asset = taxonomy_asset(tmp_path); service = MediaTaxonomyResolutionService(session)
    from models import Species
    evidence = service.acquire_commons_evidence(asset, FixtureCommons(session.get(Species, asset.taxon_id).scientific_name))
    original_event = session.query(IdentificationMediaReviewEvent).filter_by(media_asset_id=asset.id).first()
    resolution = service.resolve(asset, "CONFIRMED_TARGET_TAXON", user.id, "Structured provider evidence supports the governed target.", [evidence.id])
    assert asset.review_state == "REVIEW_REQUIRED" and asset.taxonomic_linkage == "EXACT_GOVERNED_TAXON"
    assert asset.review_state != "APPROVED"
    assert session.get(IdentificationMediaReviewEvent, original_event.id).action == "TAXONOMY_REVIEW_REQUIRED"
    assert session.query(IdentificationMediaReviewEvent).filter_by(media_asset_id=asset.id).count() == 2
    resolution.reviewer_reason = "rewrite"
    with pytest.raises(ValueError, match="append-only"): session.commit()


def test_duplicate_final_resolution_is_rejected(tmp_path):
    session, user, asset = taxonomy_asset(tmp_path); service = MediaTaxonomyResolutionService(session)
    from models import Species
    evidence = service.acquire_commons_evidence(asset, FixtureCommons(session.get(Species, asset.taxon_id).scientific_name))
    service.resolve(asset, "AMBIGUOUS", user.id, "Evidence does not establish species identity.", [evidence.id])
    with pytest.raises(ValueError, match="already has a final"):
        service.resolve(asset, "INSUFFICIENT_EVIDENCE", user.id, "Second disposition", [evidence.id])


def test_confirmation_requires_evidence_and_exact_target_name(tmp_path):
    session, user, asset = taxonomy_asset(tmp_path); service = MediaTaxonomyResolutionService(session)
    with pytest.raises(ValueError, match="persisted evidence"):
        service.resolve(asset, "CONFIRMED_TARGET_TAXON", user.id, "reason", [])


def test_nonconfirming_resolution_never_creates_corpus_or_science(tmp_path):
    session, user, asset = taxonomy_asset(tmp_path); service = MediaTaxonomyResolutionService(session)
    evidence = service.acquire_commons_evidence(asset, FixtureCommons())
    service.resolve(asset, "AMBIGUOUS", user.id, "Provider context is not independently authoritative.", [evidence.id])
    assert asset.review_state == "TAXONOMY_REVIEW_REQUIRED"
    assert session.query(IdentificationMediaTaxonomyResolution).count() == 1
    from models import IdentificationCorpus, GovernedOccurrenceEvidence, EcologicalStatusAssertion, AnomalyAssessment
    assert session.query(IdentificationCorpus).count() == 0
    assert session.query(GovernedOccurrenceEvidence).count() == 0
    assert session.query(EcologicalStatusAssertion).count() == 0
    assert session.query(AnomalyAssessment).count() == 0
