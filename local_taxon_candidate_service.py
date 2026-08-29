from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from jurisdiction_boundary_registry import canonical_json
from models import *
from taxonomy_governance import provenance_fingerprint,regional_registry_payload,taxonomy_identity_payload

def candidate_dependency(row):
 value={"region_id":row.region_id,"submitted":[row.submitted_scientific_name,row.submitted_identifier_scheme,row.submitted_identifier],"provider":row.provider,"identity":[row.authoritative_identifier_scheme,row.authoritative_identifier,row.canonical_scientific_name,row.taxonomic_rank,row.accepted_name_status,row.accepted_authoritative_identifier,row.parent_authoritative_identifier],"artifact":row.provider_artifact_sha256,"content":row.provider_content_fingerprint}
 return provenance_fingerprint(value)

class LocalTaxonCandidateService:
 def __init__(self,session):self.session=session
 def prepare(self,region_id,candidate,record,path,artifact_sha,content_fp,created_by):
  if record.rank!="SPECIES" or record.status not in {"ACCEPTED","SYNONYM"}:raise ValueError("Only exact accepted species or governed synonyms are eligible")
  values={"region_id":region_id,"submitted_scientific_name":candidate.submitted_scientific_name,"submitted_identifier_scheme":candidate.submitted_identifier_scheme,"submitted_identifier":candidate.submitted_identifier,"canonical_scientific_name":record.scientific_name,"authorship":record.authorship,"taxonomic_rank":record.rank,"authoritative_identifier_scheme":record.identifier_scheme,"authoritative_identifier":record.identifier,"accepted_name_status":record.status,"accepted_authoritative_identifier":record.accepted_identifier,"parent_authoritative_identifier":record.parent_identifier,"parent_name":record.parent_name,"provider":record.provider,"provider_version":record.provider_version,"provider_source_reference":record.provider_reference,"provider_artifact_reference":str(path),"provider_artifact_sha256":artifact_sha,"provider_content_fingerprint":content_fp,"candidate_source":candidate.candidate_source,"candidate_provenance_json":canonical_json(candidate.provenance or {}),"reconciliation_result":"EXACT_ACCEPTED_MATCH" if record.status=="ACCEPTED" else "SYNONYM","limitations_json":canonical_json(list(candidate.limitations)),"created_by":created_by}
  probe=LocalTaxonCandidate(**values,dependency_fingerprint="");values["dependency_fingerprint"]=candidate_dependency(probe)
  existing=self.session.query(LocalTaxonCandidate).filter_by(dependency_fingerprint=values["dependency_fingerprint"]).one_or_none()
  if existing:return existing
  row=LocalTaxonCandidate(**values,workflow_status="READY_FOR_REVIEW");self.session.add(row);self.session.flush();return row
 def validate(self,row):
  if candidate_dependency(row)!=row.dependency_fingerprint:raise ValueError("Candidate dependencies changed")
  path=Path(row.provider_artifact_reference)
  if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=row.provider_artifact_sha256:raise ValueError("Provider artifact is stale")
 def approve(self,row,user_id,reference):
  if row.workflow_status=="APPROVED" and row.approved_dependency_fingerprint==candidate_dependency(row):return row
  if row.workflow_status!="READY_FOR_REVIEW":raise ValueError("Candidate is not ready for review")
  self.validate(row);row.workflow_status="APPROVED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;row.approved_dependency_fingerprint=candidate_dependency(row);self.session.flush();return row
 def reject(self,row,user_id,reference):
  if row.workflow_status!="READY_FOR_REVIEW":raise ValueError("Candidate is not rejectable")
  row.workflow_status="REJECTED";row.reviewed_by_user_id=user_id;row.reviewed_at=datetime.now(timezone.utc);row.approval_reference=reference;self.session.flush();return row
 def apply(self,row):
  if row.workflow_status=="APPLIED":return {"status":"NO-OP","candidate_id":row.id,"species_id":row.resulting_species_id,"registry_entry_id":row.resulting_registry_entry_id}
  if row.workflow_status!="APPROVED" or row.approved_dependency_fingerprint!=candidate_dependency(row):raise ValueError("Approval is stale or absent")
  self.validate(row);models=(SpeciesProgram,SpeciesJurisdictionStatus,ScientificDatasetApplicability,HistoricalOccurrence,SuitabilityDeployment,TrainingRun,AnomalyAssessment,AnomalySignal);before={m:self.session.query(m).count() for m in models}
  accepted=None
  if row.accepted_name_status=="SYNONYM":
   accepted=self.session.query(Species).filter_by(authoritative_identifier_scheme=row.authoritative_identifier_scheme,authoritative_identifier=row.accepted_authoritative_identifier).one_or_none()
   if not accepted:raise ValueError("Accepted taxon must exist before synonym apply")
  species=self.session.query(Species).filter_by(authoritative_identifier_scheme=row.authoritative_identifier_scheme,authoritative_identifier=row.authoritative_identifier).one_or_none()
  by_name=self.session.query(Species).filter_by(scientific_name=row.canonical_scientific_name).one_or_none()
  if species and by_name and species.id!=by_name.id:raise ValueError("Conflicting local species identities")
  species=species or by_name
  if species and species.authoritative_identifier and species.authoritative_identifier!=row.authoritative_identifier:raise ValueError("Canonical-name collision")
  if not species:
   identity=taxonomy_identity_payload(scientific_name=row.canonical_scientific_name,taxonomic_rank=row.taxonomic_rank,identifier_scheme=row.authoritative_identifier_scheme,identifier=row.authoritative_identifier,accepted_name_status=row.accepted_name_status,accepted_taxon_identifier=row.accepted_authoritative_identifier,parent_taxon_identifier=row.parent_authoritative_identifier,authorship=row.authorship,provenance={"provider":row.provider,"provider_reference":row.provider_source_reference,"artifact_sha256":row.provider_artifact_sha256,"candidate_id":row.id},provenance_version=row.provider_version)
   species=Species(scientific_name=row.canonical_scientific_name,aphia_id=int(row.authoritative_identifier) if row.authoritative_identifier_scheme=="WORMS_APHIA_ID" else None,taxonomic_rank=row.taxonomic_rank,authoritative_identifier_scheme=row.authoritative_identifier_scheme,authoritative_identifier=row.authoritative_identifier,accepted_name_status=row.accepted_name_status,accepted_taxon_id=accepted.id if accepted else None,authorship=row.authorship,taxonomic_provenance_json=canonical_json(identity["provenance"]),provenance_version=row.provider_version,provenance_fingerprint=provenance_fingerprint(identity));self.session.add(species);self.session.flush()
  registry_taxon=accepted or species;payload=regional_registry_payload(region_id=row.region_id,taxon_id=registry_taxon.id,registry_version="regional-taxonomy-catalog-v1",inclusion_basis="APPROVED_LOCAL_TAXON_CANDIDATE",source_references=[row.provider_source_reference],taxon_fingerprint=registry_taxon.provenance_fingerprint);fp=provenance_fingerprint(payload)
  registry=self.session.query(RegionalTaxonRegistry).filter_by(provenance_fingerprint=fp).one_or_none()
  if not registry:registry=RegionalTaxonRegistry(region_id=row.region_id,taxon_id=registry_taxon.id,registry_version="regional-taxonomy-catalog-v1",inclusion_basis="APPROVED_LOCAL_TAXON_CANDIDATE",source_references_json=canonical_json([row.provider_source_reference]),review_status="APPROVED",approved_by=row.approval_reference,approved_at=row.reviewed_at,provenance_json=canonical_json(payload),provenance_fingerprint=fp);self.session.add(registry);self.session.flush()
  after={m:self.session.query(m).count() for m in models}
  if before!=after:raise ValueError("Scientific firewall violation")
  row.workflow_status="APPLIED";row.applied_at=datetime.now(timezone.utc);row.resulting_species_id=species.id;row.resulting_registry_entry_id=registry.id;self.session.commit();return {"status":"APPLIED","candidate_id":row.id,"species_id":species.id,"registry_entry_id":registry.id}
