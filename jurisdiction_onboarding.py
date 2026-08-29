"""Default-dry-run jurisdiction and boundary onboarding planner."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from caribbean_jurisdiction_inventory import CaribbeanJurisdictionInventory, validate_inventory
from jurisdiction_boundary_registry import BoundaryRegistration, validate_registration
from models import Jurisdiction, JurisdictionBoundary, Region


@dataclass(frozen=True)
class PlanItem:
    canonical_identifier: str
    jurisdiction_action: str
    boundary_action: str
    messages: tuple[str, ...] = ()


def plan_onboarding(session, inventory_path) -> tuple[PlanItem, ...]:
    inventory = CaribbeanJurisdictionInventory.load(inventory_path)
    region = session.query(Region).filter_by(slug=inventory.parent_region_identifier).one_or_none()
    if region is None:
        return (PlanItem("*", "CONFLICT", "CONFLICT", ("Parent region does not exist",)),)
    existing = session.query(Jurisdiction).all()
    errors = validate_inventory(inventory, region_identifier=region.slug,
                                existing_jurisdictions=existing)
    if errors:
        return tuple(PlanItem("*", "CONFLICT", "CONFLICT", (error,)) for error in errors)
    by_identity = {(row.canonical_identifier_scheme, row.canonical_identifier): row for row in existing}
    by_name = {row.name.strip().casefold(): row for row in existing}
    plan = []
    for entry in inventory.entries:
        identity = (entry.canonical_identifier_scheme, entry.canonical_identifier)
        jurisdiction = by_identity.get(identity) or by_name.get(entry.canonical_name.strip().casefold())
        jurisdiction_action = "NO-OP" if jurisdiction else "CREATE"
        boundary_action = "NO-OP"
        messages = []
        if entry.review_classification != "READY_FOR_ONBOARDING":
            jurisdiction_action = "CONFLICT"
            messages.append(f"Scope state is {entry.review_classification}")
        if entry.boundary:
            try:
                request = BoundaryRegistration(jurisdiction_id=jurisdiction.id if jurisdiction else -1, **entry.boundary)
                _, geometry_hash = validate_registration(request)
                if jurisdiction:
                    active = session.query(JurisdictionBoundary).filter_by(
                        jurisdiction_id=jurisdiction.id,
                        boundary_type=request.boundary_type, status="ACTIVE",
                    ).all()
                    boundary_action = "NO-OP" if len(active) == 1 and active[0].geometry_hash == geometry_hash else "UPDATE" if len(active) <= 1 else "CONFLICT"
                else:
                    boundary_action = "CREATE"
            except Exception as exc:
                boundary_action = "CONFLICT"; messages.append(str(exc))
        plan.append(PlanItem(entry.canonical_identifier, jurisdiction_action, boundary_action, tuple(messages)))
    return tuple(plan)


__all__ = ["PlanItem", "plan_onboarding"]
