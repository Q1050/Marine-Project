"""Region-generic bulk taxonomy candidate planning using the governed workflow."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from models import LocalTaxonCandidate,Region,RegionalTaxonRegistry,Species,TaxonomyPreparation
from taxonomy_preparation_service import TaxonomyPreparationService
from local_taxon_candidate_service import LocalTaxonCandidateService
from taxonomy_provider import WoRMSTaxonomyProvider

@dataclass(frozen=True)
class RegionalTaxonCandidate:
    submitted_scientific_name:str
    submitted_identifier_scheme:str|None=None
    submitted_identifier:str|None=None
    candidate_source:str="ADMIN_SUBMISSION"
    source_reference:str|None=None
    source_artifact_reference:str|None=None
    source_artifact_sha256:str|None=None
    discovery_method:str="EXPLICIT_NAME"
    discovery_version:str="regional-taxonomy-candidate-v1"
    provenance:dict|None=None
    limitations:tuple[str,...]=()

class RegionalTaxonomyBulkService:
    def __init__(self,session,provider=None): self.session=session;self.provider=provider or WoRMSTaxonomyProvider()
    def plan(self,region_id,candidates,dry_run=True,prepared_by="admin"):
        region=self.session.get(Region,region_id)
        if not region: raise ValueError("Region does not exist")
        results=[];seen_names=set();seen_ids=set()
        for raw in candidates:
            candidate=raw if isinstance(raw,RegionalTaxonCandidate) else RegionalTaxonCandidate(**raw); base={"candidate":asdict(candidate),"region_id":region.id}
            normalized=" ".join(candidate.submitted_scientific_name.split()).casefold()
            if normalized in seen_names:
                results.append({**base,"status":"CONFLICT","reason":"DUPLICATE_SUBMITTED_NAME"});continue
            seen_names.add(normalized)
            try:
                record,path,artifact_sha,content_fp=self.provider.acquire(candidate.submitted_scientific_name)
            except ValueError as exc:
                results.append({**base,"status":"AMBIGUOUS" if "Ambiguous" in str(exc) else "NOT_FOUND","reason":str(exc)});continue
            except Exception as exc:
                results.append({**base,"status":"PROVIDER_ERROR","reason":str(exc)});continue
            resolved={"provider":record.provider,"provider_version":record.provider_version,"provider_source_reference":record.provider_reference,"authoritative_identifier_scheme":record.identifier_scheme,"authoritative_identifier":record.identifier,"canonical_scientific_name":record.scientific_name,"accepted_scientific_name":record.accepted_scientific_name,"authorship":record.authorship,"rank":record.rank,"accepted_name_status":record.status,"accepted_identifier":record.accepted_identifier,"parent_identifier":record.parent_identifier,"parent_name":record.parent_name,"artifact_reference":str(path),"artifact_sha256":artifact_sha,"content_fingerprint":content_fp}
            if candidate.submitted_identifier and (candidate.submitted_identifier_scheme!=record.identifier_scheme or str(candidate.submitted_identifier)!=record.identifier):
                results.append({**base,"resolution":resolved,"status":"CONFLICT","reason":"SUBMITTED_AUTHORITATIVE_ID_CONFLICT"});continue
            key=(record.identifier_scheme,record.identifier)
            if key in seen_ids:
                results.append({**base,"resolution":resolved,"status":"CONFLICT","reason":"DUPLICATE_AUTHORITATIVE_IDENTIFIER"});continue
            seen_ids.add(key)
            if record.rank!="SPECIES":
                results.append({**base,"resolution":resolved,"status":"UNSUPPORTED_RANK","reason":"INITIAL_POLICY_REQUIRES_EXACT_SPECIES"});continue
            governed=self.session.query(RegionalTaxonRegistry).join(Species).filter(RegionalTaxonRegistry.region_id==region.id,RegionalTaxonRegistry.review_status=="APPROVED",Species.authoritative_identifier_scheme==record.identifier_scheme,Species.authoritative_identifier==record.identifier).first()
            if governed:
                results.append({**base,"resolution":resolved,"status":"ALREADY_GOVERNED","taxon_id":governed.taxon_id,"registry_entry_id":governed.id});continue
            local=self.session.query(Species).filter((Species.authoritative_identifier_scheme==record.identifier_scheme)&(Species.authoritative_identifier==record.identifier)).one_or_none() or self.session.query(Species).filter_by(scientific_name=record.scientific_name).one_or_none()
            if record.status=="SYNONYM":
                accepted=self.session.query(Species).filter_by(authoritative_identifier_scheme=record.identifier_scheme,authoritative_identifier=record.accepted_identifier).one_or_none()
                if not accepted: results.append({**base,"resolution":resolved,"status":"REVIEW_REQUIRED","reason":"ACCEPTED_TAXON_NOT_GOVERNED_LOCALLY"});continue
            if not local:
                if dry_run:results.append({**base,"resolution":resolved,"status":"CREATE_LOCAL_TAXON_CANDIDATE","expected_local_action":"CREATE_SPECIES_ON_APPROVED_APPLY","expected_regional_action":"CREATE_APPROVED_REGISTRY_ENTRY"});continue
                row=LocalTaxonCandidateService(self.session).prepare(region.id,candidate,record,path,artifact_sha,content_fp,prepared_by);self.session.commit();results.append({**base,"resolution":resolved,"status":row.workflow_status,"local_taxon_candidate_id":row.id});continue
            if dry_run:
                results.append({**base,"resolution":resolved,"status":"CREATE_PREPARATION","taxon_id":local.id});continue
            row=TaxonomyPreparationService(self.session,self.provider).prepare(taxon_id=local.id,region_id=region.id,prepared_by=prepared_by)
            self.session.commit();results.append({**base,"resolution":resolved,"status":row.workflow_status,"taxon_id":local.id,"preparation_id":row.id})
        return results
    def approve_candidate_batch(self,ids,user_id,reference):
        results=[]
        for value in ids:
            row=self.session.get(LocalTaxonCandidate,value)
            try:
                if not row:raise ValueError("Unknown candidate")
                LocalTaxonCandidateService(self.session).approve(row,user_id,reference);self.session.commit();results.append({"candidate_id":row.id,"status":"APPROVED"})
            except Exception as exc:self.session.rollback();results.append({"candidate_id":value,"status":"BLOCKED","reason":str(exc)})
        return results
    def apply_candidate_batch(self,ids):
        rows=[self.session.get(LocalTaxonCandidate,value) for value in ids]
        if any(not row or row.workflow_status not in {"APPROVED","APPLIED"} for row in rows):raise ValueError("All candidates must be approved or applied")
        results=[]
        for row in rows:
            try:results.append(LocalTaxonCandidateService(self.session).apply(row))
            except Exception as exc:self.session.rollback();results.append({"candidate_id":row.id,"status":"BLOCKED","reason":str(exc)})
        return results
    def approve_batch(self,ids,user_id,approval_reference):
        rows=[self.session.get(TaxonomyPreparation,value) for value in ids]
        results=[]
        for row in rows:
            if not row: results.append({"preparation_id":None,"status":"BLOCKED","reason":"UNKNOWN_PREPARATION"});continue
            try:
                TaxonomyPreparationService(self.session,self.provider).approve(row,user_id=user_id,approval_reference=approval_reference,expected_fingerprint=row.preparation_fingerprint);self.session.commit();results.append({"preparation_id":row.id,"taxon_id":row.taxon_id,"status":"APPROVED"})
            except Exception as exc:self.session.rollback();results.append({"preparation_id":row.id,"status":"BLOCKED","reason":str(exc)})
        return results
    def apply_batch(self,ids):
        rows=[self.session.get(TaxonomyPreparation,value) for value in ids]
        if any(row is None or row.workflow_status not in {"APPROVED","APPLIED"} for row in rows): raise ValueError("Entire batch must contain known approved or applied preparations")
        results=[]
        for row in rows:
            try: results.append({"preparation_id":row.id,**TaxonomyPreparationService(self.session,self.provider).apply(row)})
            except Exception as exc:self.session.rollback();results.append({"preparation_id":row.id,"status":"BLOCKED","reason":str(exc)})
        return results
