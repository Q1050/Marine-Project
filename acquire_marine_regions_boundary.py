import argparse,json
from marine_regions_acquisition import acquire_marine_regions_boundary

def main():
 p=argparse.ArgumentParser(); p.add_argument("--name",required=True); p.add_argument("--canonical-id",required=True); p.add_argument("--provider-iso",required=True); p.add_argument("--mrgid",type=int,required=True); p.add_argument("--boundary-type",default="MARINE_MONITORING"); args=p.parse_args()
 artifact,raw,metadata=acquire_marine_regions_boundary(canonical_name=args.name,canonical_identifier=args.canonical_id,expected_provider_iso=args.provider_iso,mrgid=args.mrgid,boundary_type=args.boundary_type)
 print(json.dumps({"artifact":str(artifact),"raw_source":str(raw),"source_sha256":metadata["source_artifact_sha256"],"geometry_sha256":metadata["geometry_sha256"]},indent=2))
if __name__=="__main__":main()
