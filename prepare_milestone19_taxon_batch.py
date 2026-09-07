"""Prepare (never approve/apply) the existing authoritative representative manifest."""
import json
from pathlib import Path
from database import SessionLocal
from models import Region, User
from regional_taxon_manifest_service import RegionalTaxonManifestService

SOURCE=Path("artifacts/taxonomy/manifests/caribbean-visual-corpus-representatives-v1.json")

def main():
 data=json.loads(SOURCE.read_text(encoding="utf-8"));session=SessionLocal()
 try:
  region=session.query(Region).filter_by(slug="caribbean").one();admin=session.query(User).filter_by(is_platform_admin=True).order_by(User.id).first()
  if not admin:raise RuntimeError("A real platform administrator is required to prepare the review queue")
  candidates=[{"submitted_scientific_name":row["scientific_name"],"submitted_identifier_scheme":"WORMS_APHIA_ID","submitted_identifier":str(row["aphia_id"]),"candidate_source":"GOVERNED_REPRESENTATIVE_MANIFEST","source_reference":f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={row['aphia_id']}","source_artifact_reference":str(SOURCE),"discovery_method":"EXISTING_CROSS_GROUP_REPRESENTATIVE_MANIFEST","discovery_version":data["manifest_version"],"provenance":{"taxonomic_group":row["group"],"authority":data["authority"]},"limitations":data["limitations"]} for row in data["candidates"]]
  payload={"manifest_id":data["manifest_id"],"manifest_version":f"{data['manifest_version']}-m19","region_id":region.id,"operator_reference":"Milestone 19 controlled taxonomy preparation; no approval or apply","provenance":{"source_artifact":str(SOURCE),"authority":data["authority"]},"limitations":data["limitations"],"configuration":{"provider_resolution":"WORMS_EXACT_SPECIES"},"candidates":candidates}
  result=RegionalTaxonManifestService(session).prepare(payload,admin.id);print(json.dumps({"run_id":result["id"],"execution_state":result["execution_state"],"summary":result["summary"],"progress":result["progress"],"human_approval_performed":False,"taxa_applied":0},indent=2,default=str))
 finally:session.close()
if __name__=="__main__":main()
