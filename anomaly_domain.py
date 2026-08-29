"""Phase 11B-1: anomaly domain enums and constants.

This module defines the typed enum values used by the anomaly
persistence layer. It does NOT perform any scientific evaluation.
Defining an enum value here does NOT authorize logic that assigns
unvalidated confidence levels or anomaly conclusions.
"""

from __future__ import annotations

import enum


class AssessmentStatus(str, enum.Enum):
    """Result of evaluating an observation for ecological anomaly.

    STALE is NOT a member of this enum; lifecycle is tracked
    separately via AssessmentLifecycleState.
    """

    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_EVALUATED = "NOT_EVALUATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_ANOMALY_DETECTED = "NO_ANOMALY_DETECTED"
    ANOMALY_SIGNAL = "ANOMALY_SIGNAL"
    REQUIRES_IDENTIFICATION_REVIEW = "REQUIRES_IDENTIFICATION_REVIEW"
    ERROR = "ERROR"
    NO_REVIEW_SIGNAL = "NO_REVIEW_SIGNAL"
    REVIEW_SUGGESTED = "REVIEW_SUGGESTED"
    INSUFFICIENT_BASELINE = "INSUFFICIENT_BASELINE"
    BLOCKED = "BLOCKED"
    TAXONOMY_REVIEW_REQUIRED = "TAXONOMY_REVIEW_REQUIRED"


class AssessmentLifecycleState(str, enum.Enum):
    """Lifecycle of an immutable assessment snapshot.

    Transitions:
        CURRENT -> STALE
        STALE -> SUPERSEDED

    Reverse transitions are rejected. Scientific result fields on
    AnomalyAssessment remain immutable across all transitions.
    """

    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class SignalStatus(str, enum.Enum):
    """Result of evaluating ONE signal for an observation.

    Distinct from AssessmentStatus. Signal results feed into the
    overall combination rule but do NOT themselves constitute an
    ecological anomaly conclusion.
    """

    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_EVALUATED = "NOT_EVALUATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_SIGNAL = "NO_SIGNAL"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    ERROR = "ERROR"


class OverallClassification(str, enum.Enum):
    """Overall conclusion only when sufficient evidence exists.

    INSUFFICIENT_EVIDENCE is NOT a member: when status is
    INSUFFICIENT_EVIDENCE, overall_classification must be NULL.
    """

    EXPECTED = "EXPECTED"
    UNUSUAL = "UNUSUAL"
    HIGHLY_UNUSUAL = "HIGHLY_UNUSUAL"


class IdentificationConfidence(str, enum.Enum):
    """Source: Observation verification + identification_status + score.

    VERIFIED is reserved for expert verification (CORRECTED /
    CONFIRMED). Numeric thresholds are NOT encoded here; tiers are
    applied via the identification gate at evaluation time.
    """

    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERIFIED = "VERIFIED"


class EvidenceConfidence(str, enum.Enum):
    """Per-signal evidence tier confidence.

    No numeric record-count thresholds are encoded; tier mapping is
    applied by the dependency resolver at evaluation time.
    """

    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ReviewType(str, enum.Enum):
    """Distinct review routing outcomes.

    The dual-review distinction (identification review vs ecological
    review) is preserved internally. A future API may expose a single
    requires_review boolean while preserving this taxonomy.
    """

    NO_REVIEW = "NO_REVIEW"
    IDENTIFICATION_REVIEW = "IDENTIFICATION_REVIEW"
    ECOLOGICAL_REVIEW = "ECOLOGICAL_REVIEW"
    BOTH = "BOTH"


class SignalType(str, enum.Enum):
    """Signal taxonomy for V1.

    V1 implements only the persistence layer; no signal evaluation
    is performed. The taxonomy is registered here so future
    evaluators may reference stable identifiers.
    """

    HABITAT_SUITABILITY_MISMATCH = "HABITAT_SUITABILITY_MISMATCH"
    GEOGRAPHIC_RANGE_ANOMALY = "GEOGRAPHIC_RANGE_ANOMALY"
    JURISDICTION_OCCURRENCE_NOVELTY = "JURISDICTION_OCCURRENCE_NOVELTY"
    TEMPORAL_PATTERN_ANOMALY = "TEMPORAL_PATTERN_ANOMALY"
    OBSERVATION_PATTERN_ANOMALY = "OBSERVATION_PATTERN_ANOMALY"
    # Phase 11B-4 descriptive evidence contexts. These names deliberately do
    # not assert novelty, mismatch, or ecological anomaly.
    HABITAT_SUITABILITY_CONTEXT = "HABITAT_SUITABILITY_CONTEXT"
    HISTORICAL_OCCURRENCE_CONTEXT = "HISTORICAL_OCCURRENCE_CONTEXT"
    IDENTIFICATION_CONTEXT = "IDENTIFICATION_CONTEXT"
    DUPLICATE_CONTEXT = "DUPLICATE_CONTEXT"
    OCCURRENCE_NOVELTY = "OCCURRENCE_NOVELTY"
    GEOGRAPHIC_CONTEXT = "GEOGRAPHIC_CONTEXT"
    ENVIRONMENTAL_CONTEXT = "ENVIRONMENTAL_CONTEXT"
    TEMPORAL_CONTEXT = "TEMPORAL_CONTEXT"
    ECOLOGICAL_CONTEXT = "ECOLOGICAL_CONTEXT"


class AnomalyReviewState(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    STALE = "STALE"


# The current anomaly method/version label.
# Bumped only on signal definition change, combination rule change,
# threshold change, confidence mapping change, or scientific-result
# bug fix. NOT bumped on deployment regeneration, data refresh, or
# platform upgrade that does not affect scientific semantics.
ANOMALY_PROVENANCE_VERSION = "ecological-anomaly-v1"


__all__ = [
    "AssessmentStatus",
    "AssessmentLifecycleState",
    "SignalStatus",
    "OverallClassification",
    "IdentificationConfidence",
    "EvidenceConfidence",
    "ReviewType",
    "SignalType",
    "ANOMALY_PROVENANCE_VERSION",
    "AnomalyReviewState",
]
