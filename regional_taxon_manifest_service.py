"""Operational regional taxon manifest orchestration over the governed 12B workflow."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from jurisdiction_boundary_registry import canonical_json
from models import (
    AnomalyAssessment, AnomalySignal, HistoricalOccurrence, LocalTaxonCandidate,
    PredictionModelSample, Region, RegionalTaxonManifestItem, RegionalTaxonManifestRun,
    ScientificDatasetApplicability, SpeciesJurisdictionStatus, SpeciesProgram,
    SuitabilityDeployment, TaxonomyPreparation, TrainingRun,
)
from regional_taxonomy_bulk_service import RegionalTaxonomyBulkService
from scientific_corpus_service import batch_progress, paginate


FIREWALL_MODELS = (
    SpeciesProgram, SpeciesJurisdictionStatus, ScientificDatasetApplicability,
    HistoricalOccurrence, SuitabilityDeployment, TrainingRun,
    PredictionModelSample, AnomalyAssessment, AnomalySignal,
)
ELIGIBLE_ACTIONS = {"CREATE_PREPARATION", "CREATE_LOCAL_TAXON_CANDIDATE"}


def _candidate_key(candidate):
    scheme = candidate.get("submitted_identifier_scheme")
    identifier = candidate.get("submitted_identifier")
    if scheme and identifier:
        return f"id:{scheme.strip().upper()}:{str(identifier).strip()}"
    return "name:" + " ".join(candidate["submitted_scientific_name"].split()).casefold()


def canonicalize_manifest(payload):
    candidates = []
    seen = set()
    for raw in payload.get("candidates") or []:
        candidate = {
            "submitted_scientific_name": " ".join(raw["submitted_scientific_name"].split()),
            "submitted_identifier_scheme": raw.get("submitted_identifier_scheme"),
            "submitted_identifier": str(raw["submitted_identifier"]) if raw.get("submitted_identifier") is not None else None,
            "candidate_source": raw.get("candidate_source", "ADMIN_MANIFEST"),
            "source_reference": raw.get("source_reference"),
            "source_artifact_reference": raw.get("source_artifact_reference"),
            "source_artifact_sha256": raw.get("source_artifact_sha256"),
            "discovery_method": raw.get("discovery_method", "MANIFEST_REVIEW_INPUT"),
            "discovery_version": raw.get("discovery_version", "regional-taxon-manifest-v1"),
            "provenance": raw.get("provenance") or {},
            "limitations": list(raw.get("limitations") or []),
        }
        key = _candidate_key(candidate)
        if key in seen:
            raise ValueError(f"Duplicate candidate identity: {key}")
        seen.add(key)
        candidate["item_key"] = key
        candidates.append(candidate)
    if not candidates:
        raise ValueError("Manifest requires at least one candidate")
    canonical = {
        "manifest_id": payload["manifest_id"],
        "manifest_version": payload["manifest_version"],
        "region_id": int(payload["region_id"]),
        "operator_reference": payload["operator_reference"],
        "provenance": payload.get("provenance") or {},
        "limitations": list(payload.get("limitations") or []),
        "configuration": payload.get("configuration") or {"provider_resolution": "GOVERNED_DEFAULT"},
        "candidates": sorted(candidates, key=lambda value: value["item_key"]),
    }
    encoded = canonical_json(canonical)
    return canonical, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _firewall_counts(session):
    return {model.__tablename__: session.query(model).count() for model in FIREWALL_MODELS}


def _summary(results):
    counts = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    clean = sum(counts.get(key, 0) for key in ELIGIBLE_ACTIONS)
    already = counts.get("ALREADY_GOVERNED", 0)
    blocked = sum(value for key, value in counts.items() if key not in ELIGIBLE_ACTIONS | {"ALREADY_GOVERNED"})
    return {"total": len(results), "cleanly_resolvable": clean, "already_governed": already, "requires_review_or_blocked": blocked, "counts": counts}


class RegionalTaxonManifestService:
    def __init__(self, session, provider=None):
        self.session = session
        self.bulk = RegionalTaxonomyBulkService(session, provider)

    def preflight(self, payload):
        canonical, fingerprint = canonicalize_manifest(payload)
        if not self.session.get(Region, canonical["region_id"]):
            raise ValueError("Region does not exist")
        candidates = [{key: value for key, value in candidate.items() if key != "item_key"} for candidate in canonical["candidates"]]
        before = _firewall_counts(self.session)
        results = self.bulk.plan(canonical["region_id"], candidates, dry_run=True)
        for result in results:
            if result["status"] == "REVIEW_REQUIRED" and result.get("resolution", {}).get("accepted_name_status") == "SYNONYM":
                result["status"] = "SYNONYM_REVIEW_REQUIRED"
        after = _firewall_counts(self.session)
        return {"manifest": canonical, "manifest_fingerprint": fingerprint, "dry_run": True, "summary": _summary(results), "results": results, "scientific_firewall": self._firewall_report(before, after)}

    def prepare(self, payload, user_id):
        canonical, fingerprint = canonicalize_manifest(payload)
        existing = self.session.query(RegionalTaxonManifestRun).filter_by(manifest_fingerprint=fingerprint).one_or_none()
        if existing:
            return self.detail(existing.id, rerun_status="NO-OP")
        if not self.session.get(Region, canonical["region_id"]):
            raise ValueError("Region does not exist")
        run = RegionalTaxonManifestRun(
            manifest_id=canonical["manifest_id"], manifest_version=canonical["manifest_version"], manifest_fingerprint=fingerprint,
            region_id=canonical["region_id"], operator_reference=canonical["operator_reference"], provenance_json=canonical_json(canonical["provenance"]),
            limitations_json=canonical_json(canonical["limitations"]), canonical_manifest_json=canonical_json(canonical), execution_state="PREPARING", created_by_user_id=user_id,
        )
        self.session.add(run); self.session.commit(); self.session.refresh(run)
        for ordinal, candidate in enumerate(canonical["candidates"]):
            submitted = {key: value for key, value in candidate.items() if key != "item_key"}
            try:
                result = self.bulk.plan(run.region_id, [submitted], dry_run=False, prepared_by=str(user_id))[0]
                action = self._action(result)
                state = "NO-OP" if action == "ALREADY_GOVERNED" else ("READY_FOR_REVIEW" if result.get("preparation_id") or result.get("local_taxon_candidate_id") else "BLOCKED")
                item = RegionalTaxonManifestItem(manifest_run_id=run.id, item_key=candidate["item_key"], ordinal=ordinal, submitted_identity_json=canonical_json(submitted), resolution_json=canonical_json(result.get("resolution")) if result.get("resolution") else None, proposed_action=action, workflow_state=state, preparation_id=result.get("preparation_id"), local_taxon_candidate_id=result.get("local_taxon_candidate_id"), species_id=result.get("taxon_id"), registry_entry_id=result.get("registry_entry_id"), result_json=canonical_json(result), created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            except Exception as exc:
                self.session.rollback()
                item = RegionalTaxonManifestItem(manifest_run_id=run.id, item_key=candidate["item_key"], ordinal=ordinal, submitted_identity_json=canonical_json(submitted), proposed_action="FAILED", workflow_state="FAILED", last_error=str(exc), result_json=canonical_json({"status": "FAILED", "reason": str(exc)}), created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            self.session.add(item); self.session.commit()
        run = self.session.get(RegionalTaxonManifestRun, run.id); run.execution_state = "PREPARED"; self.session.commit()
        return self.detail(run.id)

    @staticmethod
    def _action(result):
        if result.get("local_taxon_candidate_id"): return "CREATE_LOCAL_TAXON_CANDIDATE"
        if result.get("preparation_id"): return "CREATE_PREPARATION"
        if result["status"] == "REVIEW_REQUIRED" and result.get("resolution", {}).get("accepted_name_status") == "SYNONYM": return "SYNONYM_REVIEW_REQUIRED"
        return result["status"]

    def approve(self, run_id, item_ids, user_id, reference):
        run = self._run(run_id); results = []
        for item in self._items(run_id, item_ids):
            try:
                if item.preparation_id:
                    result = self.bulk.approve_batch([item.preparation_id], user_id, reference)[0]
                elif item.local_taxon_candidate_id:
                    result = self.bulk.approve_candidate_batch([item.local_taxon_candidate_id], user_id, reference)[0]
                else: raise ValueError("Item is not eligible for approval")
                if result["status"] != "APPROVED": raise ValueError(result.get("reason", "Approval blocked"))
                item.workflow_state = "APPROVED"; item.approval_reference = reference; item.approved_by_user_id = user_id; item.approved_at = datetime.now(timezone.utc); item.last_error = None
            except Exception as exc:
                item.workflow_state = "FAILED"; item.last_error = str(exc); result = {"item_id": item.id, "status": "FAILED", "reason": str(exc)}
            item.result_json = canonical_json(result); item.updated_at = datetime.now(timezone.utc); self.session.commit(); results.append({"item_id": item.id, **result})
        run.execution_state = "APPROVAL_IN_PROGRESS"; self.session.commit()
        return {"run_id": run.id, "results": results}

    def reject(self, run_id, item_id, user_id, reference):
        item = self._items(run_id, [item_id])[0]
        if item.workflow_state != "READY_FOR_REVIEW": raise ValueError("Only ready-for-review items are rejectable")
        if item.local_taxon_candidate_id:
            row = self.session.get(LocalTaxonCandidate, item.local_taxon_candidate_id)
            from local_taxon_candidate_service import LocalTaxonCandidateService
            LocalTaxonCandidateService(self.session).reject(row, user_id, reference)
        elif not item.preparation_id:
            raise ValueError("Item has no governed review record")
        item.workflow_state = "REJECTED"; item.approval_reference = reference; item.approved_by_user_id = user_id; item.approved_at = datetime.now(timezone.utc); self.session.commit()
        return self.item_payload(item)

    def apply(self, run_id, item_ids, retry=False):
        run = self._run(run_id); before = _firewall_counts(self.session); results = []
        for item in self._items(run_id, item_ids):
            if retry: item.retry_count += 1
            try:
                if item.workflow_state == "APPLIED": result = {"status": "NO-OP", "item_id": item.id}
                elif item.preparation_id: result = self.bulk.apply_batch([item.preparation_id])[0]
                elif item.local_taxon_candidate_id: result = self.bulk.apply_candidate_batch([item.local_taxon_candidate_id])[0]
                else: raise ValueError("Item is not eligible for apply")
                if result["status"] == "BLOCKED": raise ValueError(result.get("reason", "Apply blocked"))
                item.workflow_state = "APPLIED"; item.species_id = result.get("species_id", result.get("taxon_id", item.species_id)); item.registry_entry_id = result.get("registry_entry_id", item.registry_entry_id); item.applied_at = item.applied_at or datetime.now(timezone.utc); item.last_error = None
            except Exception as exc:
                self.session.rollback(); item = self.session.get(RegionalTaxonManifestItem, item.id); item.workflow_state = "FAILED"; item.last_error = str(exc); result = {"status": "FAILED", "reason": str(exc)}
            item.result_json = canonical_json(result); item.updated_at = datetime.now(timezone.utc); self.session.commit(); results.append({"item_id": item.id, **result})
        after = _firewall_counts(self.session); report = self._firewall_report(before, after); run = self._run(run_id); run.firewall_report_json = canonical_json(report)
        states = {item.workflow_state for item in self._items(run_id)}; run.execution_state = "COMPLETED" if states <= {"APPLIED", "NO-OP", "REJECTED", "BLOCKED"} else "PARTIAL"; run.completed_at = datetime.now(timezone.utc) if run.execution_state == "COMPLETED" else None; self.session.commit()
        return {"run_id": run.id, "execution_state": run.execution_state, "results": results, "scientific_firewall": report}

    def detail(self, run_id, rerun_status=None, page=1, page_size=100):
        run = self._run(run_id); items = self._items(run_id)
        payloads = [self.item_payload(item) for item in items]; page_data = paginate(payloads, page, page_size)
        return {"id": run.id, "manifest_id": run.manifest_id, "manifest_version": run.manifest_version, "manifest_fingerprint": run.manifest_fingerprint, "region_id": run.region_id, "operator_reference": run.operator_reference, "execution_state": run.execution_state, "created_at": run.created_at, "completed_at": run.completed_at, "rerun_status": rerun_status, "summary": _summary([{"status": item.proposed_action} for item in items]), "progress": batch_progress(payloads), **page_data, "scientific_firewall": json.loads(run.firewall_report_json) if run.firewall_report_json else None}

    def item_payload(self, item):
        return {"id": item.id, "ordinal": item.ordinal, "submitted_identity": json.loads(item.submitted_identity_json), "resolution": json.loads(item.resolution_json) if item.resolution_json else None, "proposed_action": item.proposed_action, "workflow_state": item.workflow_state, "preparation_id": item.preparation_id, "local_taxon_candidate_id": item.local_taxon_candidate_id, "species_id": item.species_id, "registry_entry_id": item.registry_entry_id, "approval_reference": item.approval_reference, "retry_count": item.retry_count, "last_error": item.last_error, "result": json.loads(item.result_json) if item.result_json else None}

    def _run(self, run_id):
        row = self.session.get(RegionalTaxonManifestRun, run_id)
        if not row: raise ValueError("Manifest run does not exist")
        return row

    def _items(self, run_id, item_ids=None):
        query = self.session.query(RegionalTaxonManifestItem).filter_by(manifest_run_id=run_id)
        if item_ids is not None: query = query.filter(RegionalTaxonManifestItem.id.in_(item_ids))
        rows = query.order_by(RegionalTaxonManifestItem.ordinal).all()
        if item_ids is not None and len(rows) != len(set(item_ids)): raise ValueError("One or more manifest items do not exist")
        return rows

    @staticmethod
    def _firewall_report(before, after):
        changes = {name: after[name] - before[name] for name in before}
        return {"status": "PASS" if all(value == 0 for value in changes.values()) else "FAIL", "statement": "REGIONAL TAXON GOVERNANCE != JURISDICTION SCIENTIFIC CONFIGURATION", "before": before, "after": after, "changes": changes}
