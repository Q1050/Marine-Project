"""Governed, append-only media taxonomy evidence and human resolution."""
from datetime import datetime, timezone
import hashlib
import html
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from models import (
    IdentificationMediaAsset,
    IdentificationMediaReviewEvent,
    IdentificationMediaTaxonomyEvidence,
    IdentificationMediaTaxonomyResolution,
    Species,
)

EVIDENCE_STATES = {"UNRESOLVED", "EVIDENCE_ACQUIRED", "CONFIRMED_TARGET_TAXON", "DIFFERENT_TAXON", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "REJECTED_EVIDENCE"}
HUMAN_RESOLUTION_STATES = {"CONFIRMED_TARGET_TAXON", "DIFFERENT_TAXON", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "REJECTED_EVIDENCE"}
PROVENANCE_VERSION = "media-taxonomy-v1"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _plain(value):
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


class CommonsTaxonomyEvidenceAdapter:
    """Bounded MediaWiki API adapter. Commons context is evidence, never proof."""
    endpoint = "https://commons.wikimedia.org/w/api.php"

    def fetch(self, page_id, timeout=15):
        query = urlencode({"action": "query", "pageids": str(page_id), "prop": "imageinfo", "iiprop": "extmetadata|canonicaltitle", "format": "json"})
        request = Request(f"{self.endpoint}?{query}", headers={"User-Agent": "MarineMonitoringTaxonomyEvidence/1.0"})
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        page = next(iter(body.get("query", {}).get("pages", {}).values()), {})
        metadata = (page.get("imageinfo") or [{}])[0].get("extmetadata") or {}
        values = {key: item.get("value") for key, item in metadata.items()}
        links = re.findall(r"https?://[^\"'<> ]+", " ".join(str(values.get(key) or "") for key in ("Credit", "Artist", "ImageDescription")))
        photo = next((link for link in links if "inaturalist.org/photos/" in link), None)
        return {
            "commons_page_id": int(page_id), "canonical_title": page.get("title"),
            "scientific_name": _plain(values.get("ImageDescription")),
            "description": _plain(values.get("ImageDescription")), "categories": str(values.get("Categories") or "").split("|"),
            "provider_identification_state": "COMMONS_STRUCTURED_METADATA",
            "external_references": links, "inaturalist_photo_reference": photo,
            "license": values.get("LicenseShortName"), "license_url": values.get("LicenseUrl"),
            "retrieved_via": "MediaWiki imageinfo/extmetadata",
        }


class MediaTaxonomyResolutionService:
    def __init__(self, session): self.session = session

    def acquire_commons_evidence(self, asset, adapter=None):
        if asset.review_state != "TAXONOMY_REVIEW_REQUIRED": raise ValueError("Asset is not in taxonomy review")
        metadata = json.loads(asset.source_metadata_json)
        page_id = metadata.get("commons_page_id")
        if not page_id: raise ValueError("Commons page identity is unavailable")
        record = (adapter or CommonsTaxonomyEvidenceAdapter()).fetch(page_id)
        target = self.session.get(Species, asset.taxon_id)
        description = record.get("description", "")
        name = target.scientific_name if target and target.scientific_name.casefold() in description.casefold() else None
        # A Commons description/category/search result can locate evidence, but is not authoritative proof.
        state = "EVIDENCE_ACQUIRED" if record else "UNRESOLVED"
        payload = {
            "media_asset_id": asset.id, "target_taxon_id": asset.taxon_id, "provider": "WIKIMEDIA_COMMONS",
            "external_id": str(page_id), "reference": asset.source_reference, "type": "PROVIDER_STRUCTURED_METADATA",
            "scientific_name": name, "state": state, "metadata": record,
        }
        fp = fingerprint(payload)
        existing = self.session.query(IdentificationMediaTaxonomyEvidence).filter_by(evidence_fingerprint=fp).one_or_none()
        if existing: return existing
        row = IdentificationMediaTaxonomyEvidence(
            media_asset_id=asset.id, target_taxon_id=asset.taxon_id, evidence_provider="WIKIMEDIA_COMMONS",
            external_evidence_identifier=str(page_id), evidence_reference=asset.source_reference,
            evidence_type="PROVIDER_STRUCTURED_METADATA", scientific_name=name,
            provider_identification_state=record.get("provider_identification_state"), reconciliation_state=state,
            evidence_metadata_json=canonical_json(record), limitations_json=canonical_json([
                "Commons structured metadata, categories, search context, and visual resemblance are not independently authoritative species identification.",
                "An iNaturalist photo reference is attribution/provenance and may require observation-level linkage before confirmation."
            ]), evidence_fingerprint=fp, retrieved_at=datetime.now(timezone.utc),
        )
        self.session.add(row); self.session.commit(); return row

    def resolve(self, asset, state, reviewer_user_id, reason, evidence_ids):
        if state not in HUMAN_RESOLUTION_STATES: raise ValueError("Unsupported final taxonomy resolution")
        if not reason.strip(): raise ValueError("A concise scientific reason is required")
        if self.session.query(IdentificationMediaTaxonomyResolution).filter_by(media_asset_id=asset.id).first():
            raise ValueError("Asset already has a final taxonomy resolution")
        evidence = self.session.query(IdentificationMediaTaxonomyEvidence).filter(
            IdentificationMediaTaxonomyEvidence.media_asset_id == asset.id,
            IdentificationMediaTaxonomyEvidence.id.in_(evidence_ids or [-1]),
        ).order_by(IdentificationMediaTaxonomyEvidence.id).all()
        if not evidence: raise ValueError("A final taxonomy resolution requires persisted evidence")
        if state == "CONFIRMED_TARGET_TAXON" and not any(e.scientific_name and e.scientific_name.casefold() == self.session.get(Species, asset.taxon_id).scientific_name.casefold() for e in evidence):
            raise ValueError("Persisted evidence does not identify the governed target species")
        evidence_fps = sorted(e.evidence_fingerprint for e in evidence)
        data = {"asset": asset.id, "target": asset.taxon_id, "state": state, "reviewer": reviewer_user_id, "reason": reason.strip(), "evidence": evidence_fps, "version": PROVENANCE_VERSION}
        fp = fingerprint(data)
        existing = self.session.query(IdentificationMediaTaxonomyResolution).filter_by(resolution_fingerprint=fp).one_or_none()
        if existing: return existing
        row = IdentificationMediaTaxonomyResolution(media_asset_id=asset.id, target_taxon_id=asset.taxon_id, resolution_state=state, reviewer_user_id=reviewer_user_id, reviewer_reason=reason.strip(), evidence_fingerprints_json=canonical_json(evidence_fps), provenance_version=PROVENANCE_VERSION, resolution_fingerprint=fp)
        self.session.add(row)
        prior = asset.review_state
        if state == "CONFIRMED_TARGET_TAXON":
            # Taxonomy confirmation makes ordinary media review possible; it is not media approval.
            asset.review_state = "REVIEW_REQUIRED"; asset.taxonomic_linkage = "EXACT_GOVERNED_TAXON"; action = "TAXONOMY_CONFIRMED"
        elif state == "DIFFERENT_TAXON":
            asset.review_state = "EXCLUDED"; asset.exclusion_reason = reason.strip(); action = "TAXONOMY_DIFFERENT_TAXON"
        else:
            asset.review_state = "TAXONOMY_REVIEW_REQUIRED"; action = f"TAXONOMY_{state}"
        asset.reviewed_by_user_id = reviewer_user_id; asset.review_reference = reason.strip(); asset.reviewed_at = datetime.now(timezone.utc)
        self.session.add(IdentificationMediaReviewEvent(media_asset_id=asset.id, reviewer_user_id=reviewer_user_id, action=action, prior_review_state=prior, current_review_state=asset.review_state, reason=reason.strip(), license_state=asset.license_classification, duplicate_state=asset.duplicate_state, quality_state=asset.quality_state))
        self.session.commit(); return row

    def history(self, asset_id):
        evidence = self.session.query(IdentificationMediaTaxonomyEvidence).filter_by(media_asset_id=asset_id).order_by(IdentificationMediaTaxonomyEvidence.created_at, IdentificationMediaTaxonomyEvidence.id).all()
        resolutions = self.session.query(IdentificationMediaTaxonomyResolution).filter_by(media_asset_id=asset_id).order_by(IdentificationMediaTaxonomyResolution.created_at, IdentificationMediaTaxonomyResolution.id).all()
        return {"evidence": [self.evidence_payload(row) for row in evidence], "resolutions": [self.resolution_payload(row) for row in resolutions]}

    @staticmethod
    def evidence_payload(row):
        return {"id": row.id, "provider": row.evidence_provider, "external_identifier": row.external_evidence_identifier, "reference": row.evidence_reference, "evidence_type": row.evidence_type, "provider_taxon_identifier": row.provider_taxon_identifier, "scientific_name": row.scientific_name, "taxon_rank": row.taxon_rank, "provider_identification_state": row.provider_identification_state, "reconciliation_state": row.reconciliation_state, "metadata": json.loads(row.evidence_metadata_json), "limitations": json.loads(row.limitations_json), "retrieved_at": row.retrieved_at, "created_at": row.created_at}

    @staticmethod
    def resolution_payload(row):
        return {"id": row.id, "resolution_state": row.resolution_state, "reviewer_user_id": row.reviewer_user_id, "reviewer_reason": row.reviewer_reason, "evidence_fingerprints": json.loads(row.evidence_fingerprints_json), "provenance_version": row.provenance_version, "created_at": row.created_at}
