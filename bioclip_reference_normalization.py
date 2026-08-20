"""BioCLIP reference normalization.

The reference metadata file
(``embeddings/ground_species/reference_metadata.json``) was built
before canonical ``Species`` records were introduced. The 10 species
labels it contains (e.g. ``pterois_volitans``) are BioCLIP candidate
snake_case keys that must be resolved to canonical scientific names.

This module provides that resolution without modifying the reference
metadata or its corresponding 400×768 embedding matrix.

Resolution precedence (per request):

1. Canonical ``Species`` row whose ``scientific_name`` matches the
   ``SCIENTIFIC_NAMES`` mapping.
2. ``SCIENTIFIC_NAMES`` fallback from ``marine_observation_service``
   (BioCLIP candidate label → scientific name).
3. ``None`` — the caller is expected to render the raw label as
   ``Not yet registered`` rather than fabricate canonical identity.
"""

from typing import Optional

from sqlalchemy.orm import Session

from models import Species


# Embedded locally to avoid module-load coupling with the heavyweight
# BioCLIP service stack. This dict is the canonical reference-set
# label → scientific-name mapping. It MUST be kept in sync with the
# static SCIENTIFIC_NAMES dict in marine_observation_service.py.
_SCIENTIFIC_NAMES = {
    "acanthurus_bahianus": "Acanthurus bahianus",
    "acanthurus_coeruleus": "Acanthurus coeruleus",
    "diodon_hystrix": "Diodon hystrix",
    "gymnothorax_funebris": "Gymnothorax funebris",
    "holacanthus_ciliaris": "Holacanthus ciliaris",
    "lactophrys_triqueter": "Lactophrys triqueter",
    "pomacanthus_paru": "Pomacanthus paru",
    "pterois_volitans": "Pterois volitans",
    "sparisoma_viride": "Sparisoma viride",
    "sphyraena_barracuda": "Sphyraena barracuda",
}


def resolve_bioclip_label_to_scientific_name(label: str) -> Optional[str]:
    """Resolve a BioCLIP reference candidate label to a scientific name.

    Returns ``None`` if the label is not present in the reference
    candidate mapping. Callers MUST treat ``None`` as
    "unregistered reference candidate".
    """
    return _SCIENTIFIC_NAMES.get(label)


def resolve_bioclip_label_to_canonical_species(
    db: Session, label: str
) -> Optional[Species]:
    """Resolve a BioCLIP reference candidate label to a canonical
    ``Species`` row.

    Returns ``None`` if the label is not yet registered. This function
    MUST NOT auto-create ``Species`` records.
    """
    scientific_name = resolve_bioclip_label_to_scientific_name(label)
    if scientific_name is None:
        return None
    return (
        db.query(Species)
        .filter(Species.scientific_name == scientific_name)
        .one_or_none()
    )
