"""Generic persisted prepare, approve, and per-jurisdiction apply workflow."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path

from models import (Jurisdiction, JurisdictionBoundary, JurisdictionOnboardingPreparation,
 Region, ScientificDatasetApplicability, SpeciesJurisdictionStatus, SpeciesProgram)
from marine_regions_acquisition import acquire_marine_regions_boundary
from onboarding_batch import load_candidate_manifest, validate_boundary_artifact
from jurisdiction_boundary_registry import BoundaryRegistration, JurisdictionBoundaryRegistry, canonical_json
from jurisdiction_governance import create_artifact_reference, create_onboarding_record, set_sovereign_parent

def dependency_fingerprint(row):
    value={"manifest":row.manifest_fingerprint,"source":row.boundary_source_sha256,"geometry":row.geometry_sha256,"identity":[row.canonical_identifier_scheme,row.canonical_identifier],"region_id":row.region_id}
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()

class JurisdictionOnboardingService:
    def __init__(self, session): self.session=session

    def prepare_from_manifest(self, manifest_path, sovereign_parent_id=None):
        manifest=load_candidate_manifest(manifest_path)
        artifact=validate_boundary_artifact(manifest["boundary_artifact_reference"],manifest)
        region=self.session.query(Region).filter_by(slug=manifest["region"]).one()
        existing=self.session.query(JurisdictionOnboardingPreparation).filter_by(manifest_fingerprint=manifest["manifest_fingerprint"]).one_or_none()
        if existing: return existing
        identity=manifest["jurisdiction"]
        row=JurisdictionOnboardingPreparation(
            region_id=region.id, canonical_name=identity["canonical_name"],
            canonical_identifier_scheme=identity["canonical_identifier_scheme"],
            canonical_identifier=identity["canonical_identifier"], jurisdiction_type=identity["jurisdiction_type"],
            sovereign_parent_id=sovereign_parent_id, manifest_version=manifest["manifest_version"],
            manifest_path=str(manifest_path), manifest_json=canonical_json(manifest),
            manifest_fingerprint=manifest["manifest_fingerprint"], boundary_artifact_path=manifest["boundary_artifact_reference"],
            boundary_provider=artifact["provider"], provider_boundary_identifier=artifact["provider_boundary_identifier"],
            boundary_source_sha256=artifact["source_artifact_sha256"], geometry_sha256=artifact["geometry_sha256"],
            workflow_state="READY_FOR_REVIEW")
        self.session.add(row); self.session.flush(); return row

    def prepare(self, request):
        region=self.session.get(Region,request["region_id"])
        if not region: raise ValueError("Parent region does not exist")
        name=request["canonical_name"].strip()
        scheme=request["canonical_identifier_scheme"].strip().upper()
        identifier=request["canonical_identifier"].strip().upper()
        jurisdiction_type=request["jurisdiction_type"].strip().upper()
        if not name or not scheme or not identifier or not jurisdiction_type:
            raise ValueError("Canonical identity fields are required")
        if scheme == "ISO_3166_1_ALPHA_2" and (len(identifier) != 2 or not identifier.isalpha()):
            raise ValueError("ISO alpha-2 canonical identifier is invalid")
        parent_id=request.get("sovereign_parent_id")
        if jurisdiction_type == "SOVEREIGN_STATE" and parent_id is not None:
            raise ValueError("Sovereign jurisdictions cannot have a sovereign parent")
        if jurisdiction_type != "SOVEREIGN_STATE" and self.session.get(Jurisdiction,parent_id) is None:
            raise ValueError("Non-sovereign jurisdiction requires an existing sovereign parent")
        artifact_path,_,artifact=acquire_marine_regions_boundary(
            canonical_name=name,canonical_identifier=identifier,
            expected_provider_iso=request["expected_provider_iso"],mrgid=int(request["provider_boundary_identifier"]),
            boundary_type=request.get("boundary_type","MARINE_MONITORING"),provider=request["boundary_provider"],provider_version=request["provider_version"])
        slug=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")
        manifest={"manifest_version":f"{slug}-onboarding-manifest-v1","jurisdiction":{"canonical_name":name,"canonical_identifier_scheme":scheme,"canonical_identifier":identifier,"jurisdiction_type":jurisdiction_type},"region":region.slug,"inventory_version":"admin-prepared-v1","boundary_artifact_reference":artifact_path.as_posix(),"boundary_source_artifact_sha256":artifact["source_artifact_sha256"],"boundary_geometry_sha256":artifact["geometry_sha256"],"provider":artifact["provider"],"provider_version":artifact["provider_version"],"expected_post_state":"GEOGRAPHICALLY_CONFIGURED_SCIENTIFICALLY_UNCONFIGURED","scientific_configuration_expected":False,"approval_state":"READY_FOR_REVIEW","limitations":["Admin-prepared; approval required before apply."]}
        manifest["manifest_fingerprint"]=hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
        path=Path("artifacts/onboarding")/f"{slug}-onboarding-manifest-v1.json"
        path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        return self.prepare_from_manifest(path,request.get("sovereign_parent_id"))

    def approve(self,row,user_id,approval_reference):
        if row.workflow_state not in {"READY_FOR_REVIEW","APPROVED"}: raise ValueError("Preparation is not reviewable")
        if not approval_reference or not approval_reference.strip(): raise ValueError("Approval reference is required")
        if (row.workflow_state == "APPROVED" and row.approval_reference == approval_reference
                and row.approved_dependency_fingerprint == dependency_fingerprint(row)):
            return row
        manifest=load_candidate_manifest(row.manifest_path); validate_boundary_artifact(row.boundary_artifact_path,manifest)
        row.workflow_state="APPROVED"; row.approval_reference=approval_reference; row.approved_by_user_id=user_id
        row.approved_at=datetime.now(timezone.utc); row.approved_dependency_fingerprint=dependency_fingerprint(row)
        self.session.flush(); return row

    def validate_approval(self,row):
        if row.workflow_state not in {"APPROVED","APPLIED"}: raise ValueError("Preparation is not approved")
        manifest=load_candidate_manifest(row.manifest_path); artifact=validate_boundary_artifact(row.boundary_artifact_path,manifest)
        if row.approved_dependency_fingerprint!=dependency_fingerprint(row) or artifact["source_artifact_sha256"]!=row.boundary_source_sha256 or artifact["geometry_sha256"]!=row.geometry_sha256: raise ValueError("Approval is stale")
        return manifest,artifact

    def apply(self,row,operator_reference):
        if row.workflow_state=="APPLIED": return {"jurisdiction":row.canonical_name,"status":"NO-OP","jurisdiction_id":row.resulting_jurisdiction_id}
        manifest,artifact=self.validate_approval(row)
        before={"jurisdictions":self.session.query(Jurisdiction).count(),"boundaries":self.session.query(JurisdictionBoundary).count()}
        jurisdiction=self.session.query(Jurisdiction).filter_by(canonical_identifier_scheme=row.canonical_identifier_scheme,canonical_identifier=row.canonical_identifier).one_or_none()
        action="NO-OP" if jurisdiction else "CREATE"
        source=json.loads(Path(artifact["source_artifact_reference"]).read_text()); feature=source["features"][0]; props=feature["properties"]
        if jurisdiction is None:
            jurisdiction=Jurisdiction(region_id=row.region_id,name=row.canonical_name,slug=re.sub(r"[^a-z0-9]+","-",row.canonical_name.lower()).strip("-"),country_code=row.canonical_identifier,canonical_identifier_scheme=row.canonical_identifier_scheme,canonical_identifier=row.canonical_identifier,jurisdiction_type=row.jurisdiction_type,status="ACTIVE",center_latitude=props["y_1"],center_longitude=props["x_1"],default_zoom=6)
            self.session.add(jurisdiction); self.session.flush()
            if row.sovereign_parent_id: set_sovereign_parent(self.session,jurisdiction,self.session.get(Jurisdiction,row.sovereign_parent_id))
        active=self.session.query(JurisdictionBoundary).filter_by(jurisdiction_id=jurisdiction.id,boundary_type=artifact["boundary_type"],status="ACTIVE").one_or_none()
        if active and active.geometry_hash!=row.geometry_sha256: raise ValueError("Active boundary conflict")
        boundary_created=False
        if not active:
            request=BoundaryRegistration(jurisdiction.id,artifact["boundary_type"],artifact["provider"],artifact["provider_version"],artifact["provider_boundary_identifier"],artifact["source_reference"],artifact["crs"],feature["geometry"],artifact["source_artifact_reference"],artifact["source_artifact_sha256"],{"manifest_fingerprint":row.manifest_fingerprint},tuple(artifact["limitations"]))
            active,_=JurisdictionBoundaryRegistry(self.session).register_and_activate(request); boundary_created=True
        reference=create_artifact_reference(self.session,local_path=artifact["source_artifact_reference"],external_uri=None,sha256=artifact["source_artifact_sha256"],media_type="application/geo+json",artifact_type="JURISDICTION_BOUNDARY_SOURCE",size_bytes=Path(artifact["source_artifact_reference"]).stat().st_size,provider=artifact["provider"],source_reference=artifact["source_reference"],availability_status="AVAILABLE")
        after={"jurisdictions":before["jurisdictions"]+(action=="CREATE"),"boundaries":before["boundaries"]+boundary_created}
        audit=dict(manifest); audit["approval_state"]="APPROVED"
        audit_record=create_onboarding_record(self.session,jurisdiction=jurisdiction,boundary=active,artifact_reference=reference,manifest=audit,action_performed=action,execution_mode="APPLY",before_state=before,after_state=after,operator_reference=operator_reference)
        if any((self.session.query(SpeciesProgram).filter_by(jurisdiction_id=jurisdiction.id).count(),self.session.query(SpeciesJurisdictionStatus).filter_by(jurisdiction_id=jurisdiction.id).count(),self.session.query(ScientificDatasetApplicability).filter_by(jurisdiction_id=jurisdiction.id).count())): raise ValueError("Scientific empty-state violation")
        row.workflow_state="APPLIED"; row.applied_at=datetime.now(timezone.utc); row.resulting_jurisdiction_id=jurisdiction.id; row.resulting_boundary_id=active.id; row.last_error=None
        self.session.commit(); return {"jurisdiction":row.canonical_name,"status":"APPLIED" if action=="CREATE" else "NO-OP","jurisdiction_id":jurisdiction.id,"boundary_id":active.id,"onboarding_record_id":audit_record.id,"before_state":before,"after_state":after}

    def apply_batch(self,ids,operator_reference):
        rows=[self.session.get(JurisdictionOnboardingPreparation,x) for x in ids]
        if any(x is None for x in rows): raise ValueError("Unknown preparation in batch")
        for row in rows: self.validate_approval(row)
        results=[]
        for row in rows:
            name=row.canonical_name
            try: results.append(self.apply(row,operator_reference))
            except Exception as exc:
                row_id=row.id
                self.session.rollback()
                failed=self.session.get(JurisdictionOnboardingPreparation,row_id)
                if failed is not None:
                    failed.last_error=str(exc); self.session.commit()
                results.append({"jurisdiction":name,"status":"BLOCKED","reason":str(exc)})
        return results
