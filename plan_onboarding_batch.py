import argparse,json
from dataclasses import asdict
from database import SessionLocal
from onboarding_batch import plan_manifests
def main():
 p=argparse.ArgumentParser(); p.add_argument("manifests",nargs="+"); p.add_argument("--apply",action="store_true"); a=p.parse_args()
 if a.apply: raise SystemExit("Live multi-manifest APPLY is disabled in Phase 12A-5")
 with SessionLocal() as db: print(json.dumps({"mode":"DRY_RUN","plans":[asdict(x) for x in plan_manifests(db,a.manifests)]},indent=2))
if __name__=="__main__":main()
