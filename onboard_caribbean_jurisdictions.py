"""Dry-run by default; apply accepts only the reviewed Barbados manifest."""
import argparse, json
from dataclasses import asdict
from database import SessionLocal
from jurisdiction_onboarding import plan_onboarding
from barbados_onboarding import apply_barbados, plan_barbados


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-manifest-fingerprint")
    args = parser.parse_args()
    with SessionLocal() as session:
        if args.inventory.endswith("barbados-onboarding-manifest-v1.json"):
            plan = plan_barbados(session, args.inventory)
            if not args.apply:
                print(json.dumps(plan, indent=2)); return
            if args.confirm_manifest_fingerprint != plan["manifest_fingerprint"]:
                raise SystemExit("Apply requires the exact reviewed manifest fingerprint")
            before = {"jurisdictions": session.query(__import__('models').Jurisdiction).count(), "boundaries": session.query(__import__('models').JurisdictionBoundary).count()}
            try:
                result = apply_barbados(session, args.inventory)
                session.commit()
            except Exception:
                session.rollback(); raise
            result["before"] = before
            result["after"] = {"jurisdictions": session.query(__import__('models').Jurisdiction).count(), "boundaries": session.query(__import__('models').JurisdictionBoundary).count()}
            print(json.dumps(result, indent=2)); return
        if args.apply:
            raise SystemExit("Apply accepts only the reviewed Barbados single-jurisdiction manifest")
        print(json.dumps({"mode": "DRY_RUN", "plan": [asdict(row) for row in plan_onboarding(session, args.inventory)]}, indent=2))


if __name__ == "__main__": main()
