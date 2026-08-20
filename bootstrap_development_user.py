"""Explicit development-only trusted-account bootstrap. Never runs automatically."""

import argparse

from auth_service import hash_password
from database import SessionLocal
from init_db import initialize_database
from models import Jurisdiction, Organization, OrganizationJurisdiction, OrganizationMembership, User


def main():
    parser = argparse.ArgumentParser(description="Create an explicit local development trusted account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", choices=["VIEWER", "REVIEWER", "MANAGER"], default="VIEWER")
    parser.add_argument("--platform-admin", action="store_true")
    parser.add_argument("--organization-name", default="Development Monitoring Organization")
    parser.add_argument("--organization-slug", default="development-monitoring-organization")
    args = parser.parse_args()

    initialize_database()
    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        if db.query(User).filter(User.email == email).first():
            raise SystemExit("A user with that email already exists.")
        user = User(
            email=email,
            display_name=args.name.strip(),
            password_hash=hash_password(args.password),
            status="ACTIVE",
            is_platform_admin=args.platform_admin,
        )
        db.add(user)
        db.flush()

        if not args.platform_admin:
            organization = db.query(Organization).filter(Organization.slug == args.organization_slug).first()
            if organization is None:
                organization = Organization(name=args.organization_name, slug=args.organization_slug, organization_type="OTHER", status="ACTIVE")
                db.add(organization)
                db.flush()
            jamaica = db.query(Jurisdiction).filter(Jurisdiction.slug == "jamaica").one()
            if not db.query(OrganizationJurisdiction).filter_by(organization_id=organization.id, jurisdiction_id=jamaica.id).first():
                db.add(OrganizationJurisdiction(organization_id=organization.id, jurisdiction_id=jamaica.id, status="ACTIVE"))
            db.add(OrganizationMembership(user_id=user.id, organization_id=organization.id, role=args.role, status="ACTIVE"))

        db.commit()
        print(f"Created development user: {email}")
        print("Platform admin" if args.platform_admin else f"Jamaica role: {args.role}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
