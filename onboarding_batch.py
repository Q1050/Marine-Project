"""Read-only multi-manifest planning. Batch APPLY is intentionally disabled."""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass,asdict
from pathlib import Path
from shapely.geometry import shape
from jurisdiction_boundary_registry import canonical_json
from models import Jurisdiction,JurisdictionBoundary,Region

@dataclass(frozen=True)
class ManifestPlan:
    manifest_version:str; canonical_identifier:str; provider_boundary_identifier:str|None
    jurisdiction_action:str; boundary_action:str; status:str; messages:tuple[str,...]=()

def load_candidate_manifest(path):
    value=json.loads(Path(path).read_text(encoding="utf-8")); supplied=value.pop("manifest_fingerprint")
    actual=hashlib.sha256(canonical_json(value).encode()).hexdigest()
    if actual!=supplied: raise ValueError(f"Manifest fingerprint mismatch: {path}")
    value["manifest_fingerprint"]=supplied
    if value.get("scientific_configuration_expected") is not False: raise ValueError("Scientific empty state is required")
    return value

def validate_boundary_artifact(path,manifest):
    artifact=json.loads(Path(path).read_text(encoding="utf-8")); source=Path(artifact["source_artifact_reference"]).read_bytes()
    if hashlib.sha256(source).hexdigest()!=artifact["source_artifact_sha256"] or artifact["source_artifact_sha256"]!=manifest["boundary_source_artifact_sha256"]: raise ValueError("Source artifact fingerprint mismatch")
    payload=json.loads(source); selection=artifact["feature_selection"]
    matches=[f for f in payload.get("features",[]) if all(f.get("properties",{}).get(k)==v for k,v in selection.items())]
    if len(matches)!=1: raise ValueError("Boundary provider identity mismatch")
    geometry=shape(matches[0]["geometry"]); geometry_sha=hashlib.sha256(canonical_json(geometry.__geo_interface__).encode()).hexdigest()
    if not geometry.is_valid or geometry_sha!=artifact["geometry_sha256"] or geometry_sha!=manifest["boundary_geometry_sha256"]: raise ValueError("Geometry validation/fingerprint mismatch")
    return artifact

def plan_manifests(session,manifest_paths):
    manifests=[]; errors=[]; identities=set(); provider_ids=set(); fingerprints=set()
    for path in manifest_paths:
        try:
            m=load_candidate_manifest(path); a=validate_boundary_artifact(m["boundary_artifact_reference"],m)
            identity=(m["jurisdiction"]["canonical_identifier_scheme"],m["jurisdiction"]["canonical_identifier"]); provider=(a["provider"],a["provider_version"],a["provider_boundary_identifier"])
            duplicates=[]
            if identity in identities: duplicates.append("duplicate canonical identity")
            if provider in provider_ids: duplicates.append("duplicate provider boundary ID")
            if m["manifest_fingerprint"] in fingerprints: duplicates.append("duplicate manifest fingerprint")
            identities.add(identity); provider_ids.add(provider); fingerprints.add(m["manifest_fingerprint"])
            manifests.append((m,a,tuple(duplicates)))
        except Exception as exc: errors.append(ManifestPlan(Path(path).stem,"UNKNOWN",None,"CONFLICT","CONFLICT","CONFLICT",(str(exc),)))
    region=session.query(Region).filter_by(slug="caribbean").one()
    plans=[]
    for m,a,duplicates in manifests:
        identity=m["jurisdiction"]; row=session.query(Jurisdiction).filter_by(canonical_identifier_scheme=identity["canonical_identifier_scheme"],canonical_identifier=identity["canonical_identifier"]).one_or_none()
        ja="NO-OP" if row else "CREATE"; ba="CREATE"; messages=list(duplicates)
        if row:
            active=session.query(JurisdictionBoundary).filter_by(jurisdiction_id=row.id,boundary_type=a["boundary_type"],status="ACTIVE").all()
            ba="CONFLICT" if len(active)>1 or (len(active)==1 and active[0].geometry_hash!=a["geometry_sha256"]) else "NO-OP" if active else "CREATE"
        if m["region"]!=region.slug or m["approval_state"] not in {"READY_FOR_REVIEW","APPROVED_FOR_CONTROLLED_PHASE_12A_4_APPLY"}: messages.append("manifest state/region is not plannable")
        status="CONFLICT" if messages or "CONFLICT" in {ja,ba} else "READY"
        plans.append(ManifestPlan(m["manifest_version"],identity["canonical_identifier"],a["provider_boundary_identifier"],ja,ba,status,tuple(messages)))
    return tuple(plans+errors)

def apply_manifest_batch(*_args,**_kwargs): raise RuntimeError("Live multi-manifest APPLY is disabled in Phase 12A-5")

FAILURE_RESUME_POLICY={"prevalidation":"ENTIRE_BATCH","transaction_scope":"ONE_APPROVED_JURISDICTION","durable_log":"REQUIRED","completed_rerun":"NO_OP","failed_manifest":"EXPLICITLY_RETRYABLE","background_jobs":"NOT_IMPLEMENTED"}
