"""Phase 11B-2 read-only evidence readiness for future anomaly evaluation.

This module resolves whether evidence is available and jurisdiction-compatible.
It deliberately does not score, classify, or persist ecological anomalies.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from models import Observation, ScientificDataset, SpeciesProgram, SuitabilityDeployment
from scientific_applicability_domain import EvidenceRole
from scientific_dataset_applicability import (
    applicability_dependency,
    authorized_applicability,
    dataset_is_jurisdiction_compatible as _role_compatible,
)


class AvailabilityState(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class IdentitySource(str, enum.Enum):
    EXPERT_VERIFIED = "EXPERT_VERIFIED"
    ACCEPTED_AI = "ACCEPTED_AI"
    UNRESOLVED = "UNRESOLVED"


class DuplicateState(str, enum.Enum):
    NOT_DUPLICATE = "NOT_DUPLICATE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    DUPLICATE_OF_OBSERVATION = "DUPLICATE_OF_OBSERVATION"


class ExpertVerificationState(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"


@dataclass(frozen=True)
class ResolvedIdentity:
    species: str | None
    source: IdentitySource


@dataclass(frozen=True)
class EvidenceReadiness:
    observation_id: int
    jurisdiction_id: int | None
    resolved_species: str | None
    identity_source: IdentitySource
    identification_readiness: AvailabilityState
    occurrence_history_availability: AvailabilityState
    suitability_model_availability: AvailabilityState
    jurisdiction_compatibility: AvailabilityState
    dataset_provenance_availability: AvailabilityState
    duplicate_status: DuplicateState
    is_duplicate: bool
    contributes_independent_evidence: bool
    expert_verification_status: ExpertVerificationState
    compatible_dataset_ids: tuple[int, ...]
    suitability_deployment_id: int | None
    limitations: tuple[str, ...]
    dependency_fingerprint: str

    def as_dict(self) -> dict:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, enum.Enum):
                value[key] = item.value
            elif isinstance(item, tuple):
                value[key] = list(item)
        return value


def resolve_observation_identity(observation: Observation) -> ResolvedIdentity:
    """Apply existing expert-over-accepted-AI identification semantics."""
    if (
        observation.verification_status in {"CONFIRMED", "CORRECTED"}
        and observation.verified_species
    ):
        return ResolvedIdentity(observation.verified_species, IdentitySource.EXPERT_VERIFIED)
    if observation.identification_status == "accepted" and observation.species:
        return ResolvedIdentity(observation.species, IdentitySource.ACCEPTED_AI)
    return ResolvedIdentity(None, IdentitySource.UNRESOLVED)


def dataset_is_jurisdiction_compatible(
    dataset: ScientificDataset,
    jurisdiction,
    session: Session | None = None,
    evidence_role: EvidenceRole | str = EvidenceRole.ANOMALY_EVIDENCE,
) -> bool:
    """Compatibility wrapper; region/global scopes fail closed without a session/assertion."""
    if jurisdiction is None:
        return False
    if (dataset.geographic_scope_type or "").upper() == "JURISDICTION":
        return dataset.jurisdiction_id == jurisdiction.id
    if session is None:
        return False
    return _role_compatible(session, dataset, jurisdiction, evidence_role)


def _evidence_role_for_dataset(dataset: ScientificDataset) -> EvidenceRole:
    dataset_type = (dataset.dataset_type or "").upper()
    if "OCCURRENCE" in dataset_type:
        return EvidenceRole.OCCURRENCE_HISTORY
    if "ENVIRONMENT" in dataset_type:
        return EvidenceRole.ENVIRONMENTAL_COVARIATE
    return EvidenceRole.ANOMALY_EVIDENCE


def _dataset_matches_species(dataset: ScientificDataset, identity: ResolvedIdentity) -> bool:
    if identity.species is None:
        return False
    if dataset.species_program_record is not None:
        return dataset.species_program_record.scientific_name == identity.species
    if dataset.species_record is not None:
        return dataset.species_record.scientific_name == identity.species
    return False


def _dataset_has_provenance(dataset: ScientificDataset) -> bool:
    return bool(
        dataset.source_name
        and (dataset.source_version or dataset.artifact_sha256 or dataset.source_reference)
    )


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dependency_fingerprint(payload: dict) -> str:
    """SHA-256 of canonical, scientifically relevant dependency state."""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class EvidenceReadinessResolver:
    """Read-only resolver; it never creates anomaly or scientific rows."""

    def __init__(self, session: Session):
        self.session = session

    def resolve(self, observation: Observation) -> EvidenceReadiness:
        identity = resolve_observation_identity(observation)
        jurisdiction = observation.jurisdiction
        duplicate = bool(
            observation.is_possible_duplicate
            or observation.duplicate_of_observation_id is not None
        )
        duplicate_state = (
            DuplicateState.DUPLICATE_OF_OBSERVATION
            if observation.duplicate_of_observation_id is not None
            else DuplicateState.POSSIBLE_DUPLICATE
            if observation.is_possible_duplicate
            else DuplicateState.NOT_DUPLICATE
        )

        candidates = []
        if identity.species is not None and jurisdiction is not None:
            candidates = [
                dataset for dataset in self.session.query(ScientificDataset).all()
                if dataset.status == "ACTIVE" and _dataset_matches_species(dataset, identity)
            ]
        compatible = sorted(
            (dataset for dataset in candidates if dataset_is_jurisdiction_compatible(
                dataset, jurisdiction, self.session, _evidence_role_for_dataset(dataset)
            )),
            key=lambda dataset: dataset.id,
        )
        occurrence = [
            dataset for dataset in compatible
            if "OCCURRENCE" in (dataset.dataset_type or "").upper()
        ]

        program = None
        deployment = None
        if identity.species is not None and observation.jurisdiction_id is not None:
            program = (
                self.session.query(SpeciesProgram)
                .filter(
                    SpeciesProgram.jurisdiction_id == observation.jurisdiction_id,
                    SpeciesProgram.scientific_name == identity.species,
                )
                .one_or_none()
            )
            if program is not None:
                deployment = (
                    self.session.query(SuitabilityDeployment)
                    .filter(
                        SuitabilityDeployment.species_program_id == program.id,
                        SuitabilityDeployment.status == "ACTIVE",
                    )
                    .order_by(SuitabilityDeployment.id.desc())
                    .first()
                )

        if identity.species is None:
            identification_state = AvailabilityState.UNAVAILABLE
            jurisdiction_state = AvailabilityState.NOT_APPLICABLE
            occurrence_state = AvailabilityState.NOT_APPLICABLE
            suitability_state = AvailabilityState.NOT_APPLICABLE
            provenance_state = AvailabilityState.NOT_APPLICABLE
        else:
            identification_state = AvailabilityState.AVAILABLE
            jurisdiction_state = (
                AvailabilityState.AVAILABLE if jurisdiction is not None
                else AvailabilityState.UNKNOWN
            )
            if occurrence:
                occurrence_state = (
                    AvailabilityState.AVAILABLE
                    if any(dataset.record_count is not None and dataset.record_count > 0 for dataset in occurrence)
                    else AvailabilityState.UNKNOWN
                )
            else:
                occurrence_state = AvailabilityState.UNAVAILABLE
            suitability_state = (
                AvailabilityState.AVAILABLE if deployment is not None
                else AvailabilityState.UNAVAILABLE
            )
            provenance_state = (
                AvailabilityState.AVAILABLE
                if compatible and all(_dataset_has_provenance(dataset) for dataset in compatible)
                else AvailabilityState.UNAVAILABLE if not compatible
                else AvailabilityState.UNKNOWN
            )

        limitations = []
        if duplicate:
            limitations.append("Observation is already represented by existing duplicate semantics.")
        if candidates and not compatible:
            limitations.append("Available scientific datasets are not jurisdiction-compatible.")
        if occurrence_state in {AvailabilityState.UNAVAILABLE, AvailabilityState.UNKNOWN}:
            limitations.append("Occurrence-history evidence is unavailable or its availability is unknown.")
        if suitability_state in {AvailabilityState.UNAVAILABLE, AvailabilityState.UNKNOWN}:
            limitations.append("A compatible active suitability deployment is unavailable.")

        dataset_dependencies = []
        for dataset in compatible:
            role = _evidence_role_for_dataset(dataset)
            assertion = None
            if (dataset.geographic_scope_type or "").upper() in {"REGION", "GLOBAL"}:
                assertion = authorized_applicability(
                    self.session, dataset.id, jurisdiction.id, role
                )
            dataset_dependencies.append({
                "id": dataset.id,
                "slug": dataset.slug,
                "dataset_type": dataset.dataset_type,
                "source_version": dataset.source_version,
                "artifact_sha256": dataset.artifact_sha256,
                "record_count": dataset.record_count,
                "scope": dataset.geographic_scope_type,
                "region_id": dataset.region_id,
                "jurisdiction_id": dataset.jurisdiction_id,
                "requested_evidence_role": role.value,
                "applicability": applicability_dependency(assertion),
            })
        fingerprint_payload = {
            "observation": {
                "id": observation.id,
                "jurisdiction_id": observation.jurisdiction_id,
                "identification_status": observation.identification_status,
                "species": observation.species,
                "verification_status": observation.verification_status,
                "verified_species": observation.verified_species,
                "image_hash": observation.image_hash,
                "is_possible_duplicate": bool(observation.is_possible_duplicate),
                "duplicate_of_observation_id": observation.duplicate_of_observation_id,
            },
            "identity": {"species": identity.species, "source": identity.source.value},
            "datasets": dataset_dependencies,
            "suitability_deployment": None if deployment is None else {
                "id": deployment.id,
                "model_version": deployment.model_version,
                "artifact_hash": deployment.artifact_hash,
                "species_program_id": deployment.species_program_id,
            },
        }

        return EvidenceReadiness(
            observation_id=observation.id,
            jurisdiction_id=observation.jurisdiction_id,
            resolved_species=identity.species,
            identity_source=identity.source,
            identification_readiness=identification_state,
            occurrence_history_availability=occurrence_state,
            suitability_model_availability=suitability_state,
            jurisdiction_compatibility=jurisdiction_state,
            dataset_provenance_availability=provenance_state,
            duplicate_status=duplicate_state,
            is_duplicate=duplicate,
            contributes_independent_evidence=not duplicate,
            expert_verification_status=(
                ExpertVerificationState.VERIFIED
                if identity.source is IdentitySource.EXPERT_VERIFIED
                else ExpertVerificationState.NOT_VERIFIED
            ),
            compatible_dataset_ids=tuple(dataset.id for dataset in compatible),
            suitability_deployment_id=None if deployment is None else deployment.id,
            limitations=tuple(limitations),
            dependency_fingerprint=dependency_fingerprint(fingerprint_payload),
        )


__all__ = [
    "AvailabilityState", "IdentitySource", "DuplicateState", "ExpertVerificationState",
    "ResolvedIdentity", "EvidenceReadiness",
    "EvidenceReadinessResolver", "resolve_observation_identity",
    "dataset_is_jurisdiction_compatible", "dependency_fingerprint",
]
