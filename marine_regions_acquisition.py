"""Explicit, DB-free Marine Regions EEZ acquisition adapter."""
from __future__ import annotations
import hashlib,json,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from shapely.geometry import shape
from jurisdiction_boundary_registry import canonical_json

PROVIDER="Marine Regions / VLIZ"
PROVIDER_VERSION="Maritime Boundaries Geodatabase EEZ v12 (2023-10-25)"
SOURCE_REFERENCE="https://doi.org/10.14284/632"
WFS="https://geo.vliz.be/geoserver/MarineRegions/wfs"


def acquire_marine_regions_boundary(*,canonical_name,canonical_identifier,expected_provider_iso,mrgid,
                                    boundary_type="MARINE_MONITORING",provider=PROVIDER,
                                    provider_version=PROVIDER_VERSION,output_directory="artifacts/onboarding",
                                    raw_directory="data/jurisdiction_boundaries"):
    if not all((canonical_name,canonical_identifier,expected_provider_iso,mrgid,boundary_type,provider,provider_version)):
        raise ValueError("All acquisition identities and provider parameters are explicit and required")
    params={"service":"WFS","version":"1.0.0","request":"GetFeature","typeName":"MarineRegions:eez","cql_filter":f"mrgid={int(mrgid)}","outputFormat":"application/json","srsName":"EPSG:4326"}
    uri=WFS+"?"+urllib.parse.urlencode(params)
    with urllib.request.urlopen(uri,timeout=120) as response: source=response.read()
    payload=json.loads(source); features=payload.get("features",[])
    if len(features)!=1: raise ValueError(f"Expected exactly one MRGID {mrgid} feature")
    feature=features[0]; props=feature.get("properties",{})
    if props.get("mrgid")!=int(mrgid) or props.get("iso_ter1")!=expected_provider_iso or props.get("pol_type")!="200NM":
        raise ValueError("Marine Regions feature identity does not match explicit expectations")
    if props.get("territory2") is not None:
        raise ValueError("Shared/joint-regime features require separate explicit approval")
    geometry=shape(feature["geometry"])
    if geometry.geom_type not in {"Polygon","MultiPolygon"} or geometry.is_empty or not geometry.is_valid or geometry.area<=0:
        raise ValueError("Provider geometry is invalid")
    source_sha=hashlib.sha256(source).hexdigest(); geometry_sha=hashlib.sha256(canonical_json(geometry.__geo_interface__).encode()).hexdigest()
    slug=canonical_name.lower().replace(" ","-").replace("and","and")
    raw_path=Path(raw_directory)/f"marine-regions-v12-{slug}-wfs-source.geojson"
    raw_path.parent.mkdir(parents=True,exist_ok=True); raw_path.write_bytes(source)
    acquired_at=datetime.now(timezone.utc).isoformat()
    artifact={"artifact_version":f"{slug}-boundary-marine-regions-eez-v12-v1","inventory_version":"caribbean-jurisdiction-candidates-v1","jurisdiction":{"canonical_name":canonical_name,"canonical_identifier_scheme":"ISO_3166_1_ALPHA_2","canonical_identifier":canonical_identifier,"jurisdiction_type":"SOVEREIGN_STATE","parent_region_identifier":"caribbean"},"boundary_type":boundary_type,"provider":provider,"provider_version":provider_version,"provider_boundary_identifier":str(mrgid),"source_reference":SOURCE_REFERENCE,"provider_record_reference":f"https://www.marineregions.org/gazetteer.php?id={mrgid}&p=details","acquisition_uri":uri,"acquired_at":acquired_at,"crs":"EPSG:4326","source_artifact_reference":raw_path.as_posix(),"source_artifact_sha256":source_sha,"geometry_sha256":geometry_sha,"geometry_type":geometry.geom_type,"geometry_bounds":list(geometry.bounds),"geometry_valid":True,"geometry_transformation":"NONE","feature_selection":{"mrgid":int(mrgid),"iso_ter1":expected_provider_iso,"pol_type":"200NM","territory2":None},"limitations":["Operational marine-monitoring boundary; not scientific evidence.","Shared/joint-regime features are excluded unless separately approved.","Provider legal and cartographic limitations apply."]}
    artifact_path=Path(output_directory)/f"{slug}-boundary-marine-regions-eez-v12.json"
    artifact_path.parent.mkdir(parents=True,exist_ok=True); artifact_path.write_text(json.dumps(artifact,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return artifact_path,raw_path,artifact

