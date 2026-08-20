"""Species jurisdiction ecology registry.

This module provides the canonical lookup path for
``SpeciesJurisdictionStatus`` data. It deliberately avoids inventing
ecological claims: if no registry record exists for a given
(species_id, jurisdiction_id) pair, ``None`` is returned and the caller
MUST NOT silently fabricate a status.

The legacy :data:`JAMAICA_ECOLOGICAL_STATUS` dict in
``marine_observation_service`` is preserved as a behavioral-compat
fallback only. New code MUST prefer this registry.
"""

from typing import Optional

from sqlalchemy.orm import Session

from models import Species, SpeciesJurisdictionStatus


_UNKNOWN = "UNKNOWN"


def get_ecological_status(
    db: Session,
    species_id: int,
    jurisdiction_id: int,
) -> Optional[SpeciesJurisdictionStatus]:
    """Return the registry record for a (species, jurisdiction) pair.

    Returns ``None`` if no provenance-backed entry exists. Callers MUST
    treat ``None`` as "no record available" and MUST NOT derive a status
    from another jurisdiction.
    """
    return (
        db.query(SpeciesJurisdictionStatus)
        .filter(
            SpeciesJurisdictionStatus.species_id == species_id,
            SpeciesJurisdictionStatus.jurisdiction_id == jurisdiction_id,
        )
        .one_or_none()
    )


def get_ecological_status_payload(
    db: Session,
    species_id: int,
    jurisdiction_id: int,
):
    """Return a JSON-safe dict of the registry record, or ``None`` if absent."""
    record = get_ecological_status(db, species_id, jurisdiction_id)
    if record is None:
        return None
    return {
        "species_id": record.species_id,
        "jurisdiction_id": record.jurisdiction_id,
        "ecological_status": record.ecological_status,
        "source": record.source,
        "source_url": record.source_url,
        "last_reviewed_at": record.last_reviewed_at.isoformat() if record.last_reviewed_at else None,
        "notes": record.notes,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def resolve_ecological_status(
    db: Session,
    species_name: Optional[str],
    jurisdiction_id: int,
) -> str:
    """Return the ecological status for an identified species in a jurisdiction.

    Resolution path (jurisdiction-isolated):

    1. If ``species_name`` is None or empty → ``UNKNOWN``.
    2. Resolve canonical ``Species`` by ``scientific_name``. If absent
       → ``UNKNOWN``.
    3. Look up ``SpeciesJurisdictionStatus(species_id, jurisdiction_id)``.
       If present → return its ``ecological_status``.
    4. Otherwise → ``UNKNOWN``.

    MUST NOT consult any global or cross-jurisdiction knowledge. MUST NOT
    return a status derived from another jurisdiction.
    """
    if not species_name:
        return _UNKNOWN
    species_row = (
        db.query(Species)
        .filter(Species.scientific_name == species_name)
        .one_or_none()
    )
    if species_row is None:
        return _UNKNOWN
    record = get_ecological_status(db, species_row.id, jurisdiction_id)
    if record is None:
        return _UNKNOWN
    return record.ecological_status


def resolve_canonical_species_id(
    db: Session,
    species_name: Optional[str],
) -> Optional[int]:
    """Resolve a scientific name to a canonical ``Species.id``.

    Returns ``None`` if the species is not yet registered. This function
    MUST NOT auto-create ``Species`` records.
    """
    if not species_name:
        return None
    species_row = (
        db.query(Species)
        .filter(Species.scientific_name == species_name)
        .one_or_none()
    )
    if species_row is None:
        return None
    return species_row.id
