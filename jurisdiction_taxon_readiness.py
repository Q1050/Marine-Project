"""Read-only, dimensional jurisdiction × taxon scientific readiness."""
from __future__ import annotations
import enum, hashlib
from dataclasses import asdict, dataclass
from jurisdiction_boundary_registry import canonical_json
from models import (EcologicalStatusAssertion, GovernedOccurrenceEvidence, HistoricalOccurrence, RegionalTaxonRegistry, ScientificDataset,
                    ScientificDatasetApplicability, Species, SpeciesJurisdictionStatus,
                    SpeciesProgram, SuitabilityDeployment, TrainingRun)

class ReadinessState(str, enum.Enum):
    READY="READY"; PARTIAL="PARTIAL"; BLOCKED="BLOCKED"; NOT_APPLICABLE="NOT_APPLICABLE"; REVIEW_REQUIRED="REVIEW_REQUIRED"; UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class ReadinessDimension:
    state: ReadinessState
    evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

@dataclass(frozen=True)
class JurisdictionTaxonReadiness:
    jurisdiction_id: int
    taxon_id: int
    dimensions: dict[str, ReadinessDimension]
    dependency_fingerprint: str
    def as_dict(self):
        return {"jurisdiction_id": self.jurisdiction_id, "taxon_id": self.taxon_id,
                "dimensions": {key: {**asdict(value), "state": value.state.value,
                                      "evidence": list(value.evidence), "limitations": list(value.limitations)}
                               for key, value in self.dimensions.items()},
                "dependency_fingerprint": self.dependency_fingerprint}

class JurisdictionTaxonReadinessService:
    def __init__(self, session): self.session=session

    def evaluate(self, jurisdiction, taxon: Species):
        identity = bool((taxon.authoritative_identifier_scheme and taxon.authoritative_identifier) or taxon.aphia_id)
        accepted = taxon.accepted_name_status in {None, "ACCEPTED"} if taxon.aphia_id else taxon.accepted_name_status == "ACCEPTED"
        conflict = taxon.accepted_name_status in {"CONFLICT", "UNRESOLVED", "SPECIES_COMPLEX"}
        rank = (taxon.taxonomic_rank or ("SPECIES" if taxon.aphia_id else "UNKNOWN")).upper()
        taxonomy_state = ReadinessState.REVIEW_REQUIRED if conflict else ReadinessState.READY if identity and accepted and rank == "SPECIES" else ReadinessState.PARTIAL if identity else ReadinessState.BLOCKED

        registry = self.session.query(RegionalTaxonRegistry).filter_by(region_id=jurisdiction.region_id, taxon_id=taxon.id).order_by(RegionalTaxonRegistry.id.desc()).first()
        governance_state = ReadinessState.READY if registry and registry.review_status == "APPROVED" else ReadinessState.REVIEW_REQUIRED if registry else ReadinessState.BLOCKED

        datasets = self.session.query(ScientificDataset).filter(ScientificDataset.species_id == taxon.id).all()
        direct_ids = {row.id for row in datasets if row.jurisdiction_id == jurisdiction.id}
        assertions = self.session.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=jurisdiction.id).all()
        authorized_by_role = {}
        pending_by_role = {}
        for row in assertions:
            target = authorized_by_role if row.applicability_status == "AUTHORIZED" else pending_by_role if row.applicability_status == "PENDING_REVIEW" else None
            if target is not None: target.setdefault(row.evidence_role, set()).add(row.scientific_dataset_id)
        occurrence_ids = direct_ids | authorized_by_role.get("OCCURRENCE_HISTORY", set())
        legacy_occurrence_count = self.session.query(HistoricalOccurrence).filter(HistoricalOccurrence.scientific_name == taxon.scientific_name, HistoricalOccurrence.dataset_id.in_(occurrence_ids)).count() if occurrence_ids else 0
        governed_occurrence_count = self.session.query(GovernedOccurrenceEvidence).filter_by(jurisdiction_id=jurisdiction.id, taxon_id=taxon.id).count()
        occurrence_count = legacy_occurrence_count + governed_occurrence_count
        occurrence_state = ReadinessState.READY if occurrence_count else ReadinessState.REVIEW_REQUIRED if pending_by_role.get("OCCURRENCE_HISTORY") else ReadinessState.BLOCKED

        ecology = self.session.query(SpeciesJurisdictionStatus).filter_by(species_id=taxon.id, jurisdiction_id=jurisdiction.id).one_or_none()
        governed_ecology_rows = self.session.query(EcologicalStatusAssertion).filter_by(taxon_id=taxon.id,jurisdiction_id=jurisdiction.id,review_status="APPROVED",authority_classification="AUTHORITATIVE_FOR_JURISDICTION",lifecycle_state="CURRENT").order_by(EcologicalStatusAssertion.id).all()
        governed_ecology_count = len(governed_ecology_rows)
        ecology_state = ReadinessState.READY if governed_ecology_count and ecology and ecology.projection_state=="CURRENT_APPROVED" else ReadinessState.REVIEW_REQUIRED if ecology or governed_ecology_count else ReadinessState.BLOCKED
        program = self.session.query(SpeciesProgram).filter_by(species_id=taxon.id, jurisdiction_id=jurisdiction.id).one_or_none()
        deployment = self.session.query(SuitabilityDeployment).filter_by(species_program_id=program.id, status="ACTIVE").first() if program else None
        run = self.session.query(TrainingRun).filter_by(species_program_id=program.id, status="COMPLETED").first() if program else None

        def role_state(role):
            if authorized_by_role.get(role): return ReadinessState.READY
            if pending_by_role.get(role): return ReadinessState.REVIEW_REQUIRED
            return ReadinessState.BLOCKED

        dims = {
            "taxonomy": ReadinessDimension(taxonomy_state, ((taxon.authoritative_identifier_scheme or "WORMS_APHIA_ID") + ":" + str(taxon.authoritative_identifier or taxon.aphia_id),) if identity else (), ("Operational programs currently require species rank.",) if rank != "SPECIES" else ()),
            "regional_governance": ReadinessDimension(governance_state, (f"registry:{registry.id}",) if registry else (), ("Regional approval is inventory governance only; it is not jurisdiction presence.",)),
            "occurrence_evidence": ReadinessDimension(occurrence_state, tuple([*(f"dataset:{value}" for value in sorted(occurrence_ids)), *((f"governed_occurrence_count:{governed_occurrence_count}",) if governed_occurrence_count else ())])),
            "ecological_status": ReadinessDimension(ecology_state, tuple([*((f"status_projection:{ecology.id}",) if ecology else ()), *((f"governed_assertions:{governed_ecology_count}",) if governed_ecology_count else ())]), ("Legacy or conflicting status does not satisfy governed readiness.",) if ecology_state==ReadinessState.REVIEW_REQUIRED else ()),
            "environmental_applicability": ReadinessDimension(role_state("ENVIRONMENTAL_COVARIATE")),
            "geographic_evidence_applicability": ReadinessDimension(role_state("GEOGRAPHIC_EVIDENCE")),
            "training_applicability": ReadinessDimension(role_state("SUITABILITY_TRAINING") if program else ReadinessState.NOT_APPLICABLE),
            "species_program": ReadinessDimension(ReadinessState.READY if program else ReadinessState.BLOCKED, (f"program:{program.id}",) if program else ()),
            "suitability_configuration": ReadinessDimension(ReadinessState.READY if deployment and run else ReadinessState.PARTIAL if program else ReadinessState.NOT_APPLICABLE),
            "geographic_baseline": ReadinessDimension(role_state("GEOGRAPHIC_EVIDENCE")),
            "anomaly_prerequisites": ReadinessDimension(ReadinessState.PARTIAL if program and occurrence_state == ReadinessState.READY else ReadinessState.BLOCKED, (), ("Readiness does not activate anomaly detection.",)),
            "scientific_review": ReadinessDimension(ReadinessState.READY if ecology_state==ReadinessState.READY else ReadinessState.REVIEW_REQUIRED),
        }
        dependencies={"jurisdiction_id":jurisdiction.id,"taxon_id":taxon.id,"taxonomy_fingerprint":taxon.provenance_fingerprint,"registry_fingerprint":registry.provenance_fingerprint if registry else None,"dataset_ids":sorted(direct_ids),"applicability_ids":sorted(row.id for row in assertions),"ecology_id":ecology.id if ecology else None,"ecology_projection_fingerprint":ecology.projection_fingerprint if ecology else None,"ecological_assertion_ids":[row.id for row in governed_ecology_rows],"program_id":program.id if program else None,"deployment_id":deployment.id if deployment else None,"training_run_id":run.id if run else None}
        return JurisdictionTaxonReadiness(jurisdiction.id,taxon.id,dims,hashlib.sha256(canonical_json(dependencies).encode()).hexdigest())
