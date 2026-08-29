"""Controlled prepare → approve → apply taxonomy workflow."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from jurisdiction_boundary_registry import canonical_json
from models import (HistoricalOccurrence,PredictionTrainingOccurrence,Region,RegionalTaxonRegistry,
                    Species,SpeciesJurisdictionStatus,SpeciesProgram,ScientificDatasetApplicability,
                    SuitabilityDeployment,TaxonomyPreparation)
from taxonomy_governance import provenance_fingerprint,regional_registry_payload,taxonomy_identity_payload
from taxonomy_provider import WoRMSTaxonomyProvider

def reconciliation(provider_record,local_taxon,obis_identifiers):
    conflicts=[]
    if local_taxon.scientific_name != provider_record.scientific_name: conflicts.append("LOCAL_CANONICAL_NAME_CONFLICT")
    if local_taxon.authoritative_identifier and str(local_taxon.authoritative_identifier)!=provider_record.identifier: conflicts.append("LOCAL_AUTHORITATIVE_IDENTIFIER_CONFLICT")
    mismatched={str(value) for value in obis_identifiers if str(value)!=provider_record.identifier}
    if mismatched: conflicts.append("OBIS_TAXON_IDENTIFIER_CONFLICT")
    if provider_record.status=="SYNONYM" and not provider_record.accepted_identifier: conflicts.append("UNRESOLVED_ACCEPTED_NAME")
    if conflicts: return "CONFLICT",tuple(conflicts)
    if local_taxon.scientific_name==provider_record.scientific_name and obis_identifiers: return "MATCH",()
    return "COMPATIBLE",("Local or OBIS authoritative metadata was incomplete.",)

def approval_dependency(row):
    value={"preparation_fingerprint":row.preparation_fingerprint,"raw_artifact_sha256":row.raw_artifact_sha256,"provider":row.provider,"authoritative_identifier":[row.authoritative_identifier_scheme,row.authoritative_identifier],"proposed_identity":[row.proposed_scientific_name,row.proposed_rank,row.proposed_accepted_name_status,row.proposed_accepted_identifier,row.proposed_parent_identifier]}
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()

class TaxonomyPreparationService:
    def __init__(self,session,provider=None): self.session=session; self.provider=provider or WoRMSTaxonomyProvider()
    def prepare(self,*,taxon_id,region_id,prepared_by):
        taxon=self.session.get(Species,taxon_id); region=self.session.get(Region,region_id)
        if not taxon or not region: raise ValueError("Taxon and region must already exist")
        record,path,artifact_sha,content_fingerprint=self.provider.acquire(taxon.scientific_name)
        obis={value[0] for value in self.session.query(HistoricalOccurrence.taxon_id).filter_by(scientific_name=taxon.scientific_name).distinct()} | {value[0] for value in self.session.query(PredictionTrainingOccurrence.taxon_id).filter_by(scientific_name=taxon.scientific_name).distinct()}
        result,limitations=reconciliation(record,taxon,obis)
        manifest={"workflow_version":"taxonomy-preparation-v1","taxon_id":taxon.id,"region_id":region.id,"provider":record.provider,"provider_version":record.provider_version,"provider_reference":record.provider_reference,"authoritative_identifier_scheme":record.identifier_scheme,"authoritative_identifier":record.identifier,"canonical_scientific_name":record.scientific_name,"accepted_scientific_name":record.accepted_scientific_name,"rank":record.rank,"accepted_name_status":record.status,"accepted_identifier":record.accepted_identifier,"parent_identifier":record.parent_identifier,"parent_name":record.parent_name,"authorship":record.authorship,"classification":list(record.classification),"raw_artifact_sha256":artifact_sha,"canonical_content_fingerprint":content_fingerprint,"reconciliation_result":result,"limitations":list(limitations)}
        fingerprint=provenance_fingerprint(manifest)
        existing=self.session.query(TaxonomyPreparation).filter_by(preparation_fingerprint=fingerprint).one_or_none()
        if existing: return existing
        row=TaxonomyPreparation(taxon_id=taxon.id,region_id=region.id,provider=record.provider,authoritative_identifier_scheme=record.identifier_scheme,authoritative_identifier=record.identifier,raw_artifact_reference=str(path),raw_artifact_sha256=artifact_sha,proposed_scientific_name=record.scientific_name,proposed_rank=record.rank,proposed_accepted_name_status=record.status,proposed_accepted_identifier=record.accepted_identifier,proposed_parent_identifier=record.parent_identifier,proposed_authorship=record.authorship,reconciliation_result=result,limitations_json=canonical_json(list(limitations)),manifest_json=canonical_json(manifest),preparation_fingerprint=fingerprint,workflow_status="READY_FOR_REVIEW",prepared_by=prepared_by)
        self.session.add(row); self.session.flush(); return row
    def validate_artifact(self,row):
        path=Path(row.raw_artifact_reference)
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=row.raw_artifact_sha256: raise ValueError("Raw taxonomy artifact changed or is unavailable")
    def approve(self,row,*,user_id,approval_reference,expected_fingerprint):
        if row.workflow_status=="APPROVED" and row.approved_dependency_fingerprint==approval_dependency(row): return row
        if row.workflow_status!="READY_FOR_REVIEW": raise ValueError("Preparation is not ready for review")
        if expected_fingerprint!=row.preparation_fingerprint: raise ValueError("Preparation fingerprint changed")
        if row.reconciliation_result not in {"MATCH","COMPATIBLE"}: raise ValueError("Conflicted or unresolved taxonomy cannot be approved")
        self.validate_artifact(row); row.workflow_status="APPROVED"; row.approval_reference=approval_reference; row.approved_by_user_id=user_id; row.approved_at=datetime.now(timezone.utc); row.approved_dependency_fingerprint=approval_dependency(row); self.session.flush(); return row
    def apply(self,row):
        if row.workflow_status=="APPLIED": return {"status":"NO-OP","taxon_id":row.taxon_id,"registry_entry_id":row.registry_entry_id}
        if row.workflow_status!="APPROVED" or row.approved_dependency_fingerprint!=approval_dependency(row): raise ValueError("Approval is stale or absent")
        self.validate_artifact(row); taxon=self.session.get(Species,row.taxon_id)
        before=(self.session.query(SpeciesProgram).count(),self.session.query(SpeciesJurisdictionStatus).count(),self.session.query(ScientificDatasetApplicability).count(),self.session.query(HistoricalOccurrence).count(),self.session.query(SuitabilityDeployment).count())
        accepted_taxon=None
        if row.proposed_accepted_name_status=="SYNONYM":
            accepted_taxon=self.session.query(Species).filter_by(authoritative_identifier_scheme=row.authoritative_identifier_scheme,authoritative_identifier=row.proposed_accepted_identifier).one_or_none()
            if not accepted_taxon: raise ValueError("Accepted synonym target is not governed locally")
        manifest=json.loads(row.manifest_json)
        identity=taxonomy_identity_payload(scientific_name=row.proposed_scientific_name,taxonomic_rank=row.proposed_rank,identifier_scheme=row.authoritative_identifier_scheme,identifier=row.authoritative_identifier,accepted_name_status=row.proposed_accepted_name_status,accepted_taxon_identifier=row.proposed_accepted_identifier,parent_taxon_identifier=row.proposed_parent_identifier,authorship=row.proposed_authorship,provenance={"provider":row.provider,"provider_reference":manifest["provider_reference"],"raw_artifact_sha256":row.raw_artifact_sha256,"reconciliation_result":row.reconciliation_result,"classification":manifest["classification"]},provenance_version=manifest["provider_version"])
        taxon.scientific_name=row.proposed_scientific_name; taxon.aphia_id=int(row.authoritative_identifier) if row.authoritative_identifier_scheme=="WORMS_APHIA_ID" else taxon.aphia_id; taxon.taxonomic_rank=row.proposed_rank; taxon.authoritative_identifier_scheme=row.authoritative_identifier_scheme; taxon.authoritative_identifier=row.authoritative_identifier; taxon.accepted_name_status=row.proposed_accepted_name_status; taxon.accepted_taxon_id=accepted_taxon.id if accepted_taxon else None; taxon.authorship=row.proposed_authorship; taxon.taxonomic_provenance_json=canonical_json(identity["provenance"]); taxon.provenance_version=identity["provenance_version"]; taxon.provenance_fingerprint=provenance_fingerprint(identity); self.session.flush()
        registry_payload=regional_registry_payload(region_id=row.region_id,taxon_id=taxon.id,registry_version="caribbean-taxonomy-v1",inclusion_basis="APPROVED_AUTHORITATIVE_TAXONOMY",source_references=[manifest["provider_reference"]],taxon_fingerprint=taxon.provenance_fingerprint)
        registry_fp=provenance_fingerprint(registry_payload); registry=self.session.query(RegionalTaxonRegistry).filter_by(provenance_fingerprint=registry_fp).one_or_none()
        if not registry:
            registry=RegionalTaxonRegistry(region_id=row.region_id,taxon_id=taxon.id,registry_version="caribbean-taxonomy-v1",inclusion_basis="APPROVED_AUTHORITATIVE_TAXONOMY",source_references_json=canonical_json([manifest["provider_reference"]]),review_status="APPROVED",approved_by=row.approval_reference,approved_at=row.approved_at,provenance_json=canonical_json(registry_payload),provenance_fingerprint=registry_fp); self.session.add(registry); self.session.flush()
        after=(self.session.query(SpeciesProgram).count(),self.session.query(SpeciesJurisdictionStatus).count(),self.session.query(ScientificDatasetApplicability).count(),self.session.query(HistoricalOccurrence).count(),self.session.query(SuitabilityDeployment).count())
        if before!=after: raise ValueError("Taxonomy scientific-firewall violation")
        row.workflow_status="APPLIED"; row.applied_at=datetime.now(timezone.utc); row.registry_entry_id=registry.id; self.session.commit(); return {"status":"APPLIED","taxon_id":taxon.id,"registry_entry_id":registry.id}
