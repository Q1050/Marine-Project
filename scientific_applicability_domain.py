"""Controlled vocabulary for jurisdiction identity and dataset applicability."""

from __future__ import annotations

import enum


class CanonicalIdentifierScheme(str, enum.Enum):
    ISO_3166_1_ALPHA_2 = "ISO_3166_1_ALPHA_2"


class JurisdictionType(str, enum.Enum):
    SOVEREIGN_STATE = "SOVEREIGN_STATE"
    OVERSEAS_TERRITORY = "OVERSEAS_TERRITORY"
    CONSTITUENT_COUNTRY = "CONSTITUENT_COUNTRY"
    OVERSEAS_COLLECTIVITY_OR_REGION = "OVERSEAS_COLLECTIVITY_OR_REGION"
    OTHER_OPERATIONAL_JURISDICTION = "OTHER_OPERATIONAL_JURISDICTION"


class EvidenceRole(str, enum.Enum):
    OCCURRENCE_HISTORY = "OCCURRENCE_HISTORY"
    ENVIRONMENTAL_COVARIATE = "ENVIRONMENTAL_COVARIATE"
    SUITABILITY_TRAINING = "SUITABILITY_TRAINING"
    SUITABILITY_VALIDATION = "SUITABILITY_VALIDATION"
    GEOGRAPHIC_EVIDENCE = "GEOGRAPHIC_EVIDENCE"
    ANOMALY_EVIDENCE = "ANOMALY_EVIDENCE"


class ApplicabilityStatus(str, enum.Enum):
    AUTHORIZED = "AUTHORIZED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    PENDING_REVIEW = "PENDING_REVIEW"
    SUPERSEDED = "SUPERSEDED"


__all__ = [
    "ApplicabilityStatus", "CanonicalIdentifierScheme", "EvidenceRole",
    "JurisdictionType",
]
