"""Provider-neutral deterministic taxonomy and regional-governance contracts."""
from __future__ import annotations
import hashlib
from jurisdiction_boundary_registry import canonical_json

TAXONOMIC_RANKS = frozenset({"SPECIES", "GENUS", "FAMILY", "ORDER", "CLASS", "PHYLUM", "KINGDOM", "UNRANKED"})
ACCEPTED_NAME_STATES = frozenset({"ACCEPTED", "SYNONYM", "UNRESOLVED", "CONFLICT", "SPECIES_COMPLEX"})
REGISTRY_STATES = frozenset({"CANDIDATE", "UNDER_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED"})

def taxonomy_identity_payload(*, scientific_name, taxonomic_rank, identifier_scheme, identifier,
                              accepted_name_status, accepted_taxon_identifier=None,
                              parent_taxon_identifier=None, authorship=None, provenance, provenance_version):
    rank = taxonomic_rank.upper(); status = accepted_name_status.upper()
    if rank not in TAXONOMIC_RANKS or status not in ACCEPTED_NAME_STATES:
        raise ValueError("Unsupported taxonomic rank or accepted-name state")
    if not identifier_scheme or not identifier or not scientific_name.strip():
        raise ValueError("Authoritative identifier and canonical scientific name are required")
    if status == "ACCEPTED" and rank == "SPECIES" and "/" in scientific_name:
        raise ValueError("Ambiguous species complexes cannot be coerced to an accepted species")
    return {"scientific_name": scientific_name.strip(), "taxonomic_rank": rank,
            "authoritative_identity": {"scheme": identifier_scheme.upper(), "identifier": str(identifier)},
            "accepted_name_status": status, "accepted_taxon_identifier": accepted_taxon_identifier,
            "parent_taxon_identifier": parent_taxon_identifier, "authorship": authorship,
            "provenance": provenance, "provenance_version": provenance_version}

_VOLATILE_IDENTITY_KEYS = frozenset({"created_at", "updated_at", "reviewed_at", "approved_at", "generated_at"})

def _stable_identity(value):
    if isinstance(value, dict): return {key:_stable_identity(item) for key,item in value.items() if key not in _VOLATILE_IDENTITY_KEYS}
    if isinstance(value, list): return [_stable_identity(item) for item in value]
    return value

def provenance_fingerprint(payload):
    return hashlib.sha256(canonical_json(_stable_identity(payload)).encode("utf-8")).hexdigest()

def regional_registry_payload(*, region_id, taxon_id, registry_version, inclusion_basis, source_references, taxon_fingerprint):
    return {"region_id": region_id, "taxon_id": taxon_id, "registry_version": registry_version,
            "inclusion_basis": inclusion_basis, "source_references": sorted(source_references),
            "taxon_fingerprint": taxon_fingerprint}
