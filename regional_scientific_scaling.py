"""Read-only Caribbean scientific scaling projections.

The projections in this module describe governed configuration and missing work.
They never create evidence, ecological status, model deployments, or anomalies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import time

from sqlalchemy import func, inspect

from caribbean_jurisdiction_inventory import CaribbeanJurisdictionInventory
from models import (
    AnomalyAssessment, EcologicalStatusAssertion, EcologicalStatusIngestionRun,
    EcologicalStatusSourceRegistration, GovernedOccurrenceEvidence, Jurisdiction,
    JurisdictionBoundary, OccurrenceAcquisitionPreparation,
    OccurrenceSourceRegistration, Observation, Region, RegionalTaxonRegistry,
    ScientificDataset, ScientificDatasetApplicability, Species, SpeciesProgram,
    SuitabilityDeployment, TrainingRun, GovernedPublicMedia, IdentificationMediaAsset,
)
from scientific_corpus_service import derive_taxonomic_group

READINESS = {"READY", "PARTIAL", "BLOCKED", "NOT_APPLICABLE", "REVIEW_REQUIRED", "UNKNOWN"}
WORKFLOW_BY_CATEGORY = {
    "GEOGRAPHIC_ONBOARDING_REQUIRED": "Use jurisdiction onboarding and boundary review.",
    "TAXONOMY_REQUIRED": "Resolve or approve the regional taxonomy candidate.",
    "OCCURRENCE_SOURCE_REQUIRED": "Register and activate a governed occurrence source.",
    "OCCURRENCE_ACQUISITION_AVAILABLE": "Prepare a bounded occurrence acquisition.",
    "OCCURRENCE_REVIEW_REQUIRED": "Review the existing occurrence preparation or candidates.",
    "ECOLOGICAL_SOURCE_REQUIRED": "Supply and govern a jurisdiction-appropriate ecological-status source.",
    "ECOLOGICAL_REVIEW_REQUIRED": "Review ecological source rows, assertions, or conflicts.",
    "MODEL_PREREQUISITES_INCOMPLETE": "Review dataset applicability and configure model prerequisites.",
    "READY_FOR_MODEL_CONFIGURATION": "Use the governed species-program workflow; no model action is automatic.",
    "GOVERNED_DIRECTORY_AVAILABLE": "Inspect the public governed jurisdiction directory.",
}


def _state(state, reason, evidence_count=0):
    assert state in READINESS
    return {"state": state, "reason": reason, "evidence_count": int(evidence_count)}


class RegionalScientificScalingService:
    """Build a matrix with a fixed number of bulk queries, not one query per cell."""

    def __init__(self, session, inventory_path=None):
        self.session = session
        self.inventory_path = Path(inventory_path or Path(__file__).parent / "artifacts/onboarding/caribbean-jurisdiction-candidates-v1.json")

    def _region(self, region_id):
        region = self.session.get(Region, int(region_id))
        if not region:
            raise ValueError("Region not found")
        return region

    def inventory(self, region_id):
        region = self._region(region_id)
        inventory = CaribbeanJurisdictionInventory.load(self.inventory_path)
        onboarded = self.session.query(Jurisdiction).filter_by(region_id=region.id).all()
        boundaries = {row[0] for row in self.session.query(JurisdictionBoundary.jurisdiction_id).filter(
            JurisdictionBoundary.status == "ACTIVE",
            JurisdictionBoundary.jurisdiction_id.in_([j.id for j in onboarded] or [-1]),
        ).all()}
        by_identity = {(j.canonical_identifier_scheme, j.canonical_identifier): j for j in onboarded}
        items = []
        for entry in inventory.entries:
            jurisdiction = by_identity.get((entry.canonical_identifier_scheme, entry.canonical_identifier))
            if jurisdiction and jurisdiction.id in boundaries:
                state = "ONBOARDED"
            elif jurisdiction:
                state = "BOUNDARY_UNAVAILABLE"
            elif entry.review_classification == "READY_FOR_ONBOARDING":
                state = "READY_FOR_ONBOARDING" if entry.boundary else "PREPARATION_REQUIRED"
            elif entry.review_classification == "REQUIRES_SCOPE_DECISION":
                state = "SCOPE_REVIEW_REQUIRED"
            else:
                state = "IDENTIFIER_REVIEW_REQUIRED"
            items.append({
                "canonical_name": entry.canonical_name,
                "canonical_identifier": entry.canonical_identifier,
                "jurisdiction_type": entry.jurisdiction_type,
                "state": state,
                "jurisdiction_id": jurisdiction.id if jurisdiction else None,
                "has_active_boundary": bool(jurisdiction and jurisdiction.id in boundaries),
                "notes": list(entry.notes),
            })
        counts = Counter(item["state"] for item in items)
        return {"region": {"id": region.id, "name": region.name, "slug": region.slug},
                "inventory_version": inventory.inventory_version, "total_governed_inventory": len(items),
                "summary": {"onboarded": counts["ONBOARDED"], "ready": counts["READY_FOR_ONBOARDING"],
                            "blocked": counts["PREPARATION_REQUIRED"] + counts["BOUNDARY_UNAVAILABLE"],
                            "review_required": counts["SCOPE_REVIEW_REQUIRED"] + counts["IDENTIFIER_REVIEW_REQUIRED"],
                            "missing_boundary": counts["BOUNDARY_UNAVAILABLE"] + counts["PREPARATION_REQUIRED"]},
                "states": dict(counts), "items": items,
                "semantics": "Inventory state is administrative geography readiness, not scientific evidence."}

    def _snapshot(self, region_id):
        region = self._region(region_id)
        jurisdictions = self.session.query(Jurisdiction).filter_by(region_id=region.id).order_by(Jurisdiction.name).all()
        registries = self.session.query(RegionalTaxonRegistry, Species).join(Species, Species.id == RegionalTaxonRegistry.taxon_id).filter(
            RegionalTaxonRegistry.region_id == region.id,
            RegionalTaxonRegistry.review_status == "APPROVED",
            RegionalTaxonRegistry.superseded_at.is_(None),
        ).order_by(Species.scientific_name).all()
        jids, tids = [j.id for j in jurisdictions], [t.id for _, t in registries]
        boundaries = {x[0] for x in self.session.query(JurisdictionBoundary.jurisdiction_id).filter(
            JurisdictionBoundary.jurisdiction_id.in_(jids or [-1]), JurisdictionBoundary.status == "ACTIVE").all()}
        occurrence_sources = self.session.query(OccurrenceSourceRegistration).filter_by(workflow_status="ACTIVE").all()
        preparations = self.session.query(OccurrenceAcquisitionPreparation).filter(
            OccurrenceAcquisitionPreparation.jurisdiction_id.in_(jids or [-1]),
            OccurrenceAcquisitionPreparation.taxon_id.in_(tids or [-1])).all()
        prep_by_key = defaultdict(list)
        for row in preparations: prep_by_key[(row.jurisdiction_id, row.taxon_id)].append(row)
        occurrence_counts = {(j, t): n for j, t, n in self.session.query(
            GovernedOccurrenceEvidence.jurisdiction_id, GovernedOccurrenceEvidence.taxon_id,
            func.count(GovernedOccurrenceEvidence.id)).filter(
            GovernedOccurrenceEvidence.jurisdiction_id.in_(jids or [-1]),
            GovernedOccurrenceEvidence.taxon_id.in_(tids or [-1])).group_by(
            GovernedOccurrenceEvidence.jurisdiction_id, GovernedOccurrenceEvidence.taxon_id).all()}
        eco_sources = self.session.query(EcologicalStatusSourceRegistration).filter_by(workflow_status="ACTIVE").all()
        eco_runs = self.session.query(EcologicalStatusIngestionRun).filter(
            EcologicalStatusIngestionRun.jurisdiction_id.in_(jids or [-1])).all()
        eco_run_jids = {r.jurisdiction_id for r in eco_runs}
        assertion_rows = self.session.query(EcologicalStatusAssertion).filter(
            EcologicalStatusAssertion.jurisdiction_id.in_(jids or [-1]),
            EcologicalStatusAssertion.taxon_id.in_(tids or [-1]),
            EcologicalStatusAssertion.review_status == "APPROVED",
            EcologicalStatusAssertion.authority_classification == "AUTHORITATIVE_FOR_JURISDICTION",
            EcologicalStatusAssertion.lifecycle_state == "CURRENT").all()
        assertions = defaultdict(list)
        for row in assertion_rows: assertions[(row.jurisdiction_id, row.taxon_id)].append(row)
        datasets = self.session.query(ScientificDataset).filter(ScientificDataset.species_id.in_(tids or [-1])).all()
        dataset_by_id = {d.id: d for d in datasets}
        applicability_rows = self.session.query(ScientificDatasetApplicability).filter(
            ScientificDatasetApplicability.jurisdiction_id.in_(jids or [-1]),
            ScientificDatasetApplicability.scientific_dataset_id.in_(list(dataset_by_id) or [-1])).all()
        applicability = defaultdict(lambda: defaultdict(list))
        for row in applicability_rows:
            dataset = dataset_by_id.get(row.scientific_dataset_id)
            if dataset: applicability[(row.jurisdiction_id, dataset.species_id)][row.evidence_role].append(row)
        programs = self.session.query(SpeciesProgram).filter(
            SpeciesProgram.jurisdiction_id.in_(jids or [-1]), SpeciesProgram.species_id.in_(tids or [-1])).all()
        programs_by_key = {(p.jurisdiction_id, p.species_id): p for p in programs}
        pids = [p.id for p in programs]
        deployments = {d.species_program_id: d for d in self.session.query(SuitabilityDeployment).filter(
            SuitabilityDeployment.species_program_id.in_(pids or [-1]), SuitabilityDeployment.status == "ACTIVE").all()}
        training = {r.species_program_id for r in self.session.query(TrainingRun).filter(
            TrainingRun.species_program_id.in_(pids or [-1]), TrainingRun.status == "COMPLETED").all()}
        observations = self.session.query(Observation).filter(Observation.jurisdiction_id.in_(jids or [-1])).all()
        observation_counts = defaultdict(lambda: {"verified": 0, "unresolved": 0})
        name_to_tid = {t.scientific_name.casefold(): t.id for _, t in registries}
        for row in observations:
            name = (row.verified_species or row.species or "").casefold()
            tid = name_to_tid.get(name)
            if not tid or row.is_possible_duplicate: continue
            key = (row.jurisdiction_id, tid)
            if row.verification_status in {"CONFIRMED", "CORRECTED"}: observation_counts[key]["verified"] += 1
            elif row.verification_status not in {"REJECTED"}: observation_counts[key]["unresolved"] += 1
        media_counts = {taxon_id: count for taxon_id, count in self.session.query(
            GovernedPublicMedia.taxon_id, func.count(GovernedPublicMedia.id)).filter(
            GovernedPublicMedia.taxon_id.in_(tids or [-1]),
            GovernedPublicMedia.lifecycle_state == "APPROVED",
            GovernedPublicMedia.public_visibility == "PUBLIC").group_by(GovernedPublicMedia.taxon_id).all()}
        identification_counts = defaultdict(lambda: {"candidates": 0, "approved": 0, "eligible": 0})
        if inspect(self.session.get_bind()).has_table(IdentificationMediaAsset.__tablename__):
            for taxon_id, review_state, license_state, quality_state, duplicate_state, count in self.session.query(
                IdentificationMediaAsset.taxon_id, IdentificationMediaAsset.review_state,
                IdentificationMediaAsset.license_classification, IdentificationMediaAsset.quality_state,
                IdentificationMediaAsset.duplicate_state, func.count(IdentificationMediaAsset.id)).filter(
                IdentificationMediaAsset.taxon_id.in_(tids or [-1])).group_by(
                IdentificationMediaAsset.taxon_id, IdentificationMediaAsset.review_state,
                IdentificationMediaAsset.license_classification, IdentificationMediaAsset.quality_state,
                IdentificationMediaAsset.duplicate_state).all():
                values=identification_counts[taxon_id];values["candidates"]+=count
                if review_state=="APPROVED":values["approved"]+=count
                if review_state=="APPROVED" and license_state in {"TRAINING_ALLOWED","ATTRIBUTION_REQUIRED"} and quality_state=="VALID" and duplicate_state in {"UNIQUE","DISTINCT"}:values["eligible"]+=count
        anomaly_keys = {}
        if inspect(self.session.get_bind()).has_table(AnomalyAssessment.__tablename__):
            anomaly_keys = {(j, name.casefold()): n for j, name, n in self.session.query(
                AnomalyAssessment.jurisdiction_id, AnomalyAssessment.evaluated_species,
                func.count(AnomalyAssessment.id)).filter(AnomalyAssessment.jurisdiction_id.in_(jids or [-1])).group_by(
                AnomalyAssessment.jurisdiction_id, AnomalyAssessment.evaluated_species).all() if name}
        return locals()

    @staticmethod
    def _source_applies(source, jurisdiction, *, ecological=False):
        if ecological:
            if source.scope_type == "JURISDICTION_SPECIFIC": return source.jurisdiction_id == jurisdiction.id
            return False  # regional/global membership cannot establish jurisdiction ecology
        try:
            scope = json.loads(source.geographic_scope_json or "{}")
        except (TypeError, json.JSONDecodeError):
            return False
        ids = scope.get("jurisdiction_ids") or []
        slugs = scope.get("jurisdiction_slugs") or []
        return not ids and not slugs or jurisdiction.id in ids or jurisdiction.slug in slugs

    def _cell(self, snap, jurisdiction, registry, taxon):
        key = (jurisdiction.id, taxon.id)
        boundary = jurisdiction.id in snap["boundaries"]
        preps = snap["prep_by_key"].get(key, [])
        occ_count = snap["occurrence_counts"].get(key, 0)
        occ_source = any(self._source_applies(s, jurisdiction) for s in snap["occurrence_sources"])
        current_assertions = snap["assertions"].get(key, [])
        statuses = sorted({a.asserted_status for a in current_assertions})
        eco_source = any(self._source_applies(s, jurisdiction, ecological=True) for s in snap["eco_sources"])
        roles = snap["applicability"].get(key, {})
        role_state = lambda role: "READY" if any(r.applicability_status == "AUTHORIZED" for r in roles.get(role, [])) else "REVIEW_REQUIRED" if roles.get(role) else "BLOCKED"
        program = snap["programs_by_key"].get(key)
        deployment = snap["deployments"].get(program.id) if program else None
        obs = snap["observation_counts"].get(key, {"verified": 0, "unresolved": 0})
        conflicts = bool({"NATIVE", "NON_NATIVE"}.issubset(statuses) or {"NATIVE", "INVASIVE"}.issubset(statuses))
        occurrence_state = "READY" if occ_count else "REVIEW_REQUIRED" if preps else "PARTIAL" if occ_source else "BLOCKED"
        ecology_state = "REVIEW_REQUIRED" if conflicts or jurisdiction.id in snap["eco_run_jids"] else "READY" if current_assertions else "PARTIAL" if eco_source else "BLOCKED"
        model_ready = bool(program and role_state("SUITABILITY_TRAINING") == "READY" and role_state("ENVIRONMENTAL_COVARIATE") == "READY")
        media_count = snap["media_counts"].get(taxon.id, 0)
        identification = snap["identification_counts"].get(taxon.id, {"candidates":0,"approved":0,"eligible":0})
        identification_state = "READY" if identification["eligible"] else "REVIEW_REQUIRED" if identification["candidates"] else "BLOCKED"
        environment_state = role_state("ENVIRONMENTAL_COVARIATE")
        dimensions = {
            "geography": _state("READY" if boundary else "BLOCKED", "Active governed marine boundary." if boundary else "Jurisdiction has no active marine boundary."),
            "taxonomy": _state("READY", "Authoritative taxon identity is approved in the regional catalog.", 1),
            "occurrence": _state(occurrence_state, "Applied governed jurisdiction occurrence evidence." if occ_count else "Occurrence source/acquisition requires governed review; absence is not evidence of absence.", occ_count),
            "ecology": _state(ecology_state, "Current approved jurisdiction assertions." if current_assertions else "No approved jurisdiction ecological-status assertion; regional status is not inferred.", len(current_assertions)),
            "public_directory": _state("READY" if current_assertions else "BLOCKED", "Only current approved jurisdiction assertions are publicly listable."),
            "imagery": _state("READY" if media_count else "BLOCKED", "Approved public governed media." if media_count else "No approved public governed image; absence does not affect taxonomy.", media_count),
            "identification": _state(identification_state, "Governed training-eligible regional identification assets exist; jurisdiction presence is not inferred." if identification["eligible"] else "Identification-media candidates require review or are unavailable.", identification["eligible"]),
            "environmental": _state(environment_state, "Environmental covariate applicability remains independently governed."),
            "suitability": _state("READY" if deployment else "PARTIAL" if model_ready or program else "BLOCKED", "Active deployment exists." if deployment else "Suitability prerequisites remain independently governed."),
            "early_warning": _state("PARTIAL" if boundary and occ_count and obs["verified"] else "BLOCKED", "Prerequisite projection only; readiness does not mean an anomaly exists.", snap["anomaly_keys"].get((jurisdiction.id, taxon.scientific_name.casefold()), 0)),
        }
        # Compatibility aliases keep existing admin clients stable while the
        # explicit suitability/early-warning dimensions are adopted.
        dimensions["modeling"] = dimensions["suitability"]
        dimensions["anomaly"] = dimensions["early_warning"]
        try:
            provenance = json.loads(taxon.taxonomic_provenance_json or "{}")
            lineage = provenance.get("classification") or provenance.get("lineage") or []
        except (TypeError, json.JSONDecodeError):
            lineage = []
        taxon_group = derive_taxonomic_group(lineage)
        return {"region": {"id": snap["region"].id, "name": snap["region"].name, "slug": snap["region"].slug},
                "jurisdiction": {"id": jurisdiction.id, "name": jurisdiction.name, "slug": jurisdiction.slug},
                "taxon": {"id": taxon.id, "scientific_name": taxon.scientific_name, "common_name": taxon.common_name,
                          "rank": taxon.taxonomic_rank, "authoritative_identifier_scheme": taxon.authoritative_identifier_scheme,
                          "authoritative_identifier": taxon.authoritative_identifier or taxon.aphia_id,
                          "registry_version": registry.registry_version, "descriptive_group": taxon_group["group"],
                          "descriptive_group_basis": taxon_group["basis"]},
                "dimensions": dimensions, "approved_statuses": statuses, "conflict": conflicts,
                "dataset_applicability": {role: role_state(role) for role in ("OCCURRENCE_HISTORY", "ENVIRONMENTAL_COVARIATE", "GEOGRAPHIC_EVIDENCE", "SUITABILITY_TRAINING")},
                "model_eligibility": {"state": "READY" if model_ready else "BLOCKED", "species_program": bool(program),
                                      "training_data": role_state("SUITABILITY_TRAINING"), "environmental_data": role_state("ENVIRONMENTAL_COVARIATE"),
                                      "geographic_evidence": role_state("GEOGRAPHIC_EVIDENCE"), "completed_training_run": bool(program and program.id in snap["training"]),
                                      "active_deployment": bool(deployment), "reason": "Projection only; no training or deployment is performed."},
                "anomaly_prerequisites": {"state": dimensions["early_warning"]["state"], "governed_taxon": True, "active_boundary": boundary,
                                          "governed_occurrence_evidence": occ_count, "approved_ecological_status": bool(current_assertions),
                                          "verified_observations": obs["verified"], "baseline_available": role_state("GEOGRAPHIC_EVIDENCE") == "READY",
                                          "model_available": bool(deployment), "semantics": "Prerequisites do not indicate that an anomaly exists."},
                "operations": obs}

    def matrix(self, region_id, *, jurisdiction_id=None, taxon_id=None, taxon_group=None, dimension=None, readiness_state=None, search=None, page=1, page_size=50):
        started = time.perf_counter(); snap = self._snapshot(region_id)
        jurisdictions = [j for j in snap["jurisdictions"] if not jurisdiction_id or j.id == int(jurisdiction_id)]
        registries = [(r, t) for r, t in snap["registries"] if not taxon_id or t.id == int(taxon_id)]
        if search:
            needle=str(search).casefold();matching_jurisdictions=[j for j in jurisdictions if needle in j.name.casefold()]
            matching_taxa=[(r,t) for r,t in registries if needle in t.scientific_name.casefold() or needle in (t.common_name or "").casefold()]
            if matching_jurisdictions:jurisdictions=matching_jurisdictions
            elif matching_taxa:registries=matching_taxa
            else:jurisdictions=[]
        size = min(max(1, page_size), 200)
        number = max(1, page); start = (number - 1) * size
        if taxon_group:
            requested = str(taxon_group).upper()
            def group_for(taxon):
                try: provenance = json.loads(taxon.taxonomic_provenance_json or "{}")
                except (TypeError, json.JSONDecodeError): provenance = {}
                return derive_taxonomic_group(provenance.get("classification") or provenance.get("lineage") or [])["group"]
            registries = [(r, t) for r, t in registries if group_for(t) == requested]
        if dimension:
            allowed = {"geography", "taxonomy", "occurrence", "ecology", "public_directory", "imagery", "identification", "environmental", "suitability", "early_warning", "modeling", "anomaly"}
            if dimension not in allowed: raise ValueError("Unknown readiness dimension")
            matching = []
            for jurisdiction in jurisdictions:
                for registry, taxon in registries:
                    cell = self._cell(snap, jurisdiction, registry, taxon)
                    if not readiness_state or cell["dimensions"][dimension]["state"] == str(readiness_state).upper(): matching.append(cell)
            total = len(matching); cells = matching[start:start + size]
        else:
            # Apply pagination before projection so a 40k matrix response does
            # not materialize 40k detailed dictionaries in memory.
            total = len(jurisdictions) * len(registries); cells = []
            for offset in range(start, min(start + size, total)):
                jurisdiction_index, taxon_index = divmod(offset, len(registries))
                registry, taxon = registries[taxon_index]
                cells.append(self._cell(snap, jurisdictions[jurisdiction_index], registry, taxon))
        return {"region": {"id": snap["region"].id, "name": snap["region"].name, "slug": snap["region"].slug},
                "page": number, "page_size": size, "total": total, "items": cells,
                "projection_runtime_ms": round((time.perf_counter() - started) * 1000, 2),
                "semantics": "Categorical governed-state projection; no overall score and no scientific writes."}

    def detail(self, region_id, jurisdiction_id, taxon_id):
        result = self.matrix(region_id, jurisdiction_id=jurisdiction_id, taxon_id=taxon_id, page_size=1)
        if not result["items"]: raise ValueError("Jurisdiction/taxon combination not found in governed regional configuration")
        return result["items"][0]

    def preflight(self, region_id, **filters):
        matrix = self.matrix(region_id, page=1, page_size=200, **filters)
        items = []
        for cell in matrix["items"]:
            dims = cell["dimensions"]
            categories = []
            if dims["geography"]["state"] != "READY": categories.append("GEOGRAPHIC_ONBOARDING_REQUIRED")
            if dims["taxonomy"]["state"] != "READY": categories.append("TAXONOMY_REQUIRED")
            if dims["occurrence"]["state"] == "BLOCKED": categories.append("OCCURRENCE_SOURCE_REQUIRED")
            elif dims["occurrence"]["state"] == "PARTIAL": categories.append("OCCURRENCE_ACQUISITION_AVAILABLE")
            elif dims["occurrence"]["state"] == "REVIEW_REQUIRED": categories.append("OCCURRENCE_REVIEW_REQUIRED")
            if dims["ecology"]["state"] == "BLOCKED": categories.append("ECOLOGICAL_SOURCE_REQUIRED")
            elif dims["ecology"]["state"] == "REVIEW_REQUIRED": categories.append("ECOLOGICAL_REVIEW_REQUIRED")
            if cell["model_eligibility"]["state"] == "READY": categories.append("READY_FOR_MODEL_CONFIGURATION")
            else: categories.append("MODEL_PREREQUISITES_INCOMPLETE")
            if dims["ecology"]["state"] == "READY": categories.append("GOVERNED_DIRECTORY_AVAILABLE")
            for category in categories:
                items.append({"category": category, "state": "READY" if category in {"READY_FOR_MODEL_CONFIGURATION", "GOVERNED_DIRECTORY_AVAILABLE"} else "REVIEW_REQUIRED",
                              "jurisdiction": cell["jurisdiction"], "taxon": cell["taxon"],
                              "reason": WORKFLOW_BY_CATEGORY[category], "next_workflow": WORKFLOW_BY_CATEGORY[category],
                              "dependency": category.split("_REQUIRED")[0].lower()})
        grouped = Counter(item["category"] for item in items)
        return {"region": matrix["region"], "count": len(items), "categories": dict(grouped), "items": items,
                "semantics": "Read-only work projection. Items are not evidence and perform no actions."}

    def summary(self, region_id):
        snap = self._snapshot(region_id)
        cells = [self._cell(snap, j, registry, taxon) for j in snap["jurisdictions"] for registry, taxon in snap["registries"]]
        inventory = self.inventory(region_id)
        names = ("taxonomy", "occurrence", "ecology", "public_directory", "imagery", "identification", "environmental", "suitability", "early_warning")
        dimension_counts = {name: dict(Counter(cell["dimensions"][name]["state"] for cell in cells)) for name in names}
        return {"region": {"id": snap["region"].id, "name": snap["region"].name, "slug": snap["region"].slug},
                "jurisdiction_inventory": inventory["summary"],
                "onboarded_jurisdictions": len(snap["jurisdictions"]), "governed_taxa": len(snap["registries"]),
                "combinations": len(cells), "readiness": dimension_counts,
                "governed_directory_combinations": sum(c["dimensions"]["ecology"]["state"] == "READY" for c in cells),
                "semantics": "Categorical governed-state projection; no overall score and no scientific writes."}

    def regional_taxa(self, region_id, *, page=1, page_size=50):
        snap = self._snapshot(region_id); rows = []
        for registry, taxon in snap["registries"]:
            jurisdictions = []
            for jurisdiction in snap["jurisdictions"]:
                assertions = snap["assertions"].get((jurisdiction.id, taxon.id), [])
                if assertions:
                    jurisdictions.append({"jurisdiction_id": jurisdiction.id, "jurisdiction": jurisdiction.name,
                                          "statuses": sorted({a.asserted_status for a in assertions})})
            rows.append({"taxon_id": taxon.id, "scientific_name": taxon.scientific_name, "common_name": taxon.common_name,
                         "rank": taxon.taxonomic_rank, "authoritative_identifier_scheme": taxon.authoritative_identifier_scheme,
                         "authoritative_identifier": taxon.authoritative_identifier or taxon.aphia_id,
                         "approved_jurisdiction_statuses": jurisdictions})
        size=min(max(1,page_size),100); start=(max(1,page)-1)*size
        return {"region":{"id":snap["region"].id,"name":snap["region"].name,"slug":snap["region"].slug},
                "page":max(1,page),"page_size":size,"total":len(rows),"items":rows[start:start+size],
                "semantics":"Regional catalog membership does not imply presence, establishment, or invasiveness in any jurisdiction."}

    def taxon_comparison(self, region_id, taxon_id):
        snap=self._snapshot(region_id); matching=[(r,t) for r,t in snap["registries"] if t.id==int(taxon_id)]
        if not matching: raise ValueError("Taxon is not approved in this regional catalog")
        _,taxon=matching[0]; items=[]
        for jurisdiction in snap["jurisdictions"]:
            assertions=snap["assertions"].get((jurisdiction.id,taxon.id),[])
            items.append({"jurisdiction_id":jurisdiction.id,"jurisdiction":jurisdiction.name,
                          "statuses":sorted({a.asserted_status for a in assertions}),
                          "state":"GOVERNED_STATUS_AVAILABLE" if assertions else "NO_GOVERNED_ECOLOGICAL_STATUS"})
        return {"region":{"id":snap["region"].id,"name":snap["region"].name},"taxon":{"id":taxon.id,"scientific_name":taxon.scientific_name,"common_name":taxon.common_name},
                "jurisdictions":items,"semantics":"Missing status is not interpreted as absence or any ecological category."}
