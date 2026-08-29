"""Non-scientific reviewed inventory contract for jurisdiction onboarding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scientific_applicability_domain import CanonicalIdentifierScheme, JurisdictionType


INVENTORY_STATUSES = frozenset({
    "READY_FOR_ONBOARDING", "REQUIRES_SCOPE_DECISION", "REQUIRES_IDENTIFIER_VALIDATION",
})
SUPPORTED_SCHEMES = frozenset(item.value for item in CanonicalIdentifierScheme)
SUPPORTED_TYPES = frozenset(item.value for item in JurisdictionType)


@dataclass(frozen=True)
class InventoryEntry:
    canonical_name: str
    canonical_identifier_scheme: str
    canonical_identifier: str
    jurisdiction_type: str
    parent_region_identifier: str
    sovereign_parent_identifier: str | None
    operational_status: str
    source_reference: str
    inventory_version: str
    notes: tuple[str, ...]
    review_classification: str
    boundary: dict | None = None


@dataclass(frozen=True)
class CaribbeanJurisdictionInventory:
    inventory_version: str
    parent_region_identifier: str
    source_references: tuple[str, ...]
    entries: tuple[InventoryEntry, ...]

    @classmethod
    def load(cls, path) -> "CaribbeanJurisdictionInventory":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload["inventory_version"]
        parent = payload["parent_region_identifier"]
        entries = tuple(InventoryEntry(
            canonical_name=row["canonical_name"],
            canonical_identifier_scheme=row["canonical_identifier_scheme"],
            canonical_identifier=row["canonical_identifier"],
            jurisdiction_type=row["jurisdiction_type"],
            parent_region_identifier=row["parent_region_identifier"],
            sovereign_parent_identifier=row.get("sovereign_parent_identifier"),
            operational_status=row["operational_status"],
            source_reference=row["source_reference"], inventory_version=version,
            notes=tuple(row.get("notes", [])),
            review_classification=row["review_classification"],
            boundary=row.get("boundary"),
        ) for row in payload["entries"])
        return cls(version, parent, tuple(payload.get("source_references", [])), entries)


def validate_inventory(inventory: CaribbeanJurisdictionInventory, *, region_identifier: str,
                       existing_jurisdictions=()) -> tuple[str, ...]:
    """Pure validation: returns errors and performs no database writes."""
    errors: list[str] = []
    identities: set[tuple[str, str]] = set()
    names: set[str] = set()
    existing = {
        (row.canonical_identifier_scheme, row.canonical_identifier): row
        for row in existing_jurisdictions if row.canonical_identifier_scheme
    }
    existing_by_name = {row.name.strip().casefold(): row for row in existing_jurisdictions}
    for index, row in enumerate(inventory.entries):
        label = f"entry[{index}] {row.canonical_name!r}"
        identity = (row.canonical_identifier_scheme, row.canonical_identifier)
        if row.canonical_identifier_scheme not in SUPPORTED_SCHEMES:
            errors.append(f"{label}: unsupported canonical identifier scheme")
        if not row.canonical_identifier:
            errors.append(f"{label}: missing canonical identifier")
        if identity in identities:
            errors.append(f"{label}: duplicate canonical identifier")
        identities.add(identity)
        normalized_name = row.canonical_name.strip().casefold()
        if normalized_name in names:
            errors.append(f"{label}: duplicate canonical name")
        names.add(normalized_name)
        if row.jurisdiction_type not in SUPPORTED_TYPES:
            errors.append(f"{label}: missing or unsupported jurisdiction type")
        if row.parent_region_identifier != region_identifier:
            errors.append(f"{label}: invalid parent region")
        if row.review_classification not in INVENTORY_STATUSES:
            errors.append(f"{label}: unsupported review classification")
        non_sovereign = row.jurisdiction_type != JurisdictionType.SOVEREIGN_STATE.value
        if non_sovereign and not row.sovereign_parent_identifier:
            errors.append(f"{label}: non-sovereign jurisdiction requires sovereign parent")
        if row.jurisdiction_type == JurisdictionType.SOVEREIGN_STATE.value and row.sovereign_parent_identifier:
            errors.append(f"{label}: sovereign state cannot declare a sovereign parent")
        prior = existing.get(identity)
        if prior and (prior.name != row.canonical_name or prior.jurisdiction_type != row.jurisdiction_type):
            errors.append(f"{label}: inconsistent redefinition of existing jurisdiction")
        named_prior = existing_by_name.get(normalized_name)
        if named_prior and named_prior.country_code != row.canonical_identifier:
            errors.append(f"{label}: existing name has a conflicting canonical identifier")
        if named_prior and named_prior.jurisdiction_type and named_prior.jurisdiction_type != row.jurisdiction_type:
            errors.append(f"{label}: existing name has a conflicting jurisdiction type")
    return tuple(errors)


__all__ = ["CaribbeanJurisdictionInventory", "InventoryEntry", "validate_inventory"]
