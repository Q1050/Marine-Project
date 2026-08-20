"""Phase 10D-2: Generalized scientific dataset input loaders.

This module provides reusable loaders that accept a
``SuitabilityTrainingSpec`` and resolve the explicit Phase 10C
``ScientificDataset`` inputs identified by the spec. The loaders do
not infer:

- Jamaica
- Pterois volitans
- dataset identity from filenames
- dataset identity from model version
- jurisdiction from species
- species from dataset slug

This module does NOT:

- introduce database schema changes
- modify or delete any existing scientific records
- train a model
- activate or modify a SuitabilityDeployment
- download new scientific data

The loaders return a ``SuitabilityTrainingInputs`` bundle that
preserves Phase 10C provenance metadata for downstream training and
audit use.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import (
    HistoricalOccurrence,
    PredictionSampleEnvironmentalFeature,
    ScientificDataset,
)


# Accepted Phase 10C dataset_type values for occurrence training inputs.
# The v3 backfill uses 'OCCURRENCE'; future SLAs may use 'OCCURRENCE' or
# 'OCCURRENCE_PRESENCE' or 'PRESENCE_BACKGROUND' provided the producer
# stores sufficient provenance. We accept the same union.
ACCEPTED_OCCURRENCE_DATASET_TYPES = frozenset({
    "OCCURRENCE",
})

# Accepted Phase 10C dataset_type values for environmental feature
# inputs. The v3 backfill uses 'ENVIRONMENTAL'.
ACCEPTED_ENVIRONMENTAL_DATASET_TYPES = frozenset({
    "ENVIRONMENTAL",
})


@dataclass(frozen=True)
class DatasetProvenanceSummary:
    """Read-only provenance summary for a ScientificDataset record.

    This is what the loader returns to the caller so future training
    and audit code can reference the dataset without re-querying.
    """

    id: int
    slug: str
    name: str
    dataset_type: str
    status: str
    geographic_scope_type: str
    region_id: Optional[int]
    jurisdiction_id: Optional[int]
    species_id: Optional[int]
    species_program_id: Optional[int]
    source_name: str
    source_type: Optional[str]
    source_reference: Optional[str]
    source_version: Optional[str]
    retrieved_at: Optional[str]
    record_count: Optional[int]
    artifact_path: Optional[str]
    artifact_sha256: Optional[str]
    notes: Optional[str]


def _summarize_dataset(record: ScientificDataset) -> DatasetProvenanceSummary:
    """Convert a ScientificDataset row into a sanitized summary.

    The summary intentionally does NOT include acquisition_manifest_json
    because Phase 10C explicitly avoids persisting credentials or raw
    provider secrets there. All other provenance fields are passed
    through verbatim.
    """
    return DatasetProvenanceSummary(
        id=record.id,
        slug=record.slug,
        name=record.name,
        dataset_type=record.dataset_type,
        status=record.status,
        geographic_scope_type=record.geographic_scope_type,
        region_id=record.region_id,
        jurisdiction_id=record.jurisdiction_id,
        species_id=record.species_id,
        species_program_id=record.species_program_id,
        source_name=record.source_name,
        source_type=record.source_type,
        source_reference=record.source_reference,
        source_version=record.source_version,
        retrieved_at=(
            record.retrieved_at.isoformat() if record.retrieved_at else None
        ),
        record_count=record.record_count,
        artifact_path=record.artifact_path,
        artifact_sha256=record.artifact_sha256,
        notes=record.notes,
    )


def _resolve_dataset(
    db: Session,
    dataset_id: Optional[int],
    expected_dataset_types: frozenset,
    kind: str,
) -> ScientificDataset:
    """Resolve a ScientificDataset by ID and validate its dataset_type.

    Raises ``ValueError`` with a clear message when the dataset is missing
    or has an incompatible dataset type. The error message identifies the
    dataset field type so the caller can react precisely.
    """
    if dataset_id is None:
        raise ValueError(
            f"{kind} dataset_id is required for input loading"
        )
    record = (
        db.query(ScientificDataset)
        .filter(ScientificDataset.id == dataset_id)
        .one_or_none()
    )
    if record is None:
        raise ValueError(
            f"ScientificDataset {dataset_id} does not exist"
        )
    if record.dataset_type not in expected_dataset_types:
        raise ValueError(
            f"ScientificDataset {dataset_id} has dataset_type="
            f"{record.dataset_type!r}; expected one of "
            f"{sorted(expected_dataset_types)!r} for {kind} inputs"
        )
    if record.status != "ACTIVE":
        raise ValueError(
            f"ScientificDataset {dataset_id} is not ACTIVE; "
            f"status={record.status!r}"
        )
    return record


def _validate_occurrence_scope(
    db: Session,
    record: ScientificDataset,
    spec,
    allow_region_to_jurisdiction_relaxation: bool = False,
) -> None:
    """Validate that the dataset's scope is compatible with the spec.

    Scope rules:
    - A JURISDICTION-scoped dataset must belong to the spec's
      jurisdiction_id (when the spec is jurisdiction-scoped).
    - A REGION-scoped dataset must belong to the spec's region_id (when
      the spec is region-scoped).
    - Species-scoped (dataset.species_id is not None) datasets must
      match the spec's species.

    The ``allow_region_to_jurisdiction_relaxation`` flag extends the
    rule: a region-scoped dataset may be used for a jurisdiction-scoped
    spec when the dataset's region_id equals the spec's region_id.
    This is intended for environmental-feature datasets only; it does
    not relax occurrence-data scope for training.
    """
    if record.species_id is not None:
        from models import Species
        species_row = (
            db.query(Species)
            .filter(Species.id == record.species_id)
            .one_or_none()
        )
        if species_row is None:
            raise ValueError(
                f"ScientificDataset {record.id} references missing "
                f"species_id={record.species_id}"
            )
        if species_row.scientific_name != spec.species:
            raise ValueError(
                f"ScientificDataset {record.id} is scoped to species "
                f"{species_row.scientific_name!r} but spec requires "
                f"{spec.species!r}"
            )
    if record.geographic_scope_type == "JURISDICTION":
        if spec.geographic_scope != "JURISDICTION":
            raise ValueError(
                f"ScientificDataset {record.id} is jurisdiction-scoped "
                f"but spec.species scope is {spec.geographic_scope!r}"
            )
        if (
            spec.jurisdiction_id is not None
            and record.jurisdiction_id != spec.jurisdiction_id
        ):
            raise ValueError(
                f"ScientificDataset {record.id} belongs to "
                f"jurisdiction_id={record.jurisdiction_id} but spec requires "
                f"jurisdiction_id={spec.jurisdiction_id}"
            )
    elif record.geographic_scope_type == "REGION":
        if spec.geographic_scope == "REGION":
            if (
                spec.region_id is not None
                and record.region_id != spec.region_id
            ):
                raise ValueError(
                    f"ScientificDataset {record.id} belongs to "
                    f"region_id={record.region_id} but spec requires "
                    f"region_id={spec.region_id}"
                )
        elif spec.geographic_scope == "JURISDICTION":
            if allow_region_to_jurisdiction_relaxation:
                if record.region_id is None or spec.region_id is None:
                    raise ValueError(
                        f"ScientificDataset {record.id} region-scoped "
                        "use for a jurisdiction-scoped spec requires "
                        "both dataset and spec to identify a region"
                    )
                if record.region_id != spec.region_id:
                    raise ValueError(
                        f"ScientificDataset {record.id} is region-scoped "
                        f"(region_id={record.region_id}); spec is "
                        f"jurisdiction-scoped with region_id={spec.region_id}. "
                        "Region-to-jurisdiction relaxation only succeeds "
                        "when the dataset's region_id matches the spec's "
                        "region_id."
                    )
            else:
                raise ValueError(
                    f"ScientificDataset {record.id} is region-scoped but "
                    f"spec scope is {spec.geographic_scope!r}"
                )


def _allow_region_dataset_for_jurisdiction_spec(
    spec,
    record: ScientificDataset,
) -> bool:
    """Decide whether a region-scoped dataset may be used for a
    jurisdiction-scoped spec.

    A region-scoped dataset is a superset of features for the region.
    A jurisdiction-scoped training spec may legitimately use features
    from a region-scoped dataset when the spec's region_id matches the
    dataset's region_id. This mirrors the v3 case (the data was
    produced for the entire Caribbean region including Jamaica).

    The current Phase 10C infrastructure does not have a per-cell
    region-jurisdiction membership model, so the relaxation is at the
    region level only. A jurisdiction-scoped spec is allowed to use a
    region-scoped dataset when the datum's region_id equals the
    spec's region_id.

    This can be further refined in a future phase when a region
    definition model is added.
    """
    if spec.region_id is None:
        return False
    return record.region_id == spec.region_id


# ----------------------------------------------------------------------
# Occurrence loader
# ----------------------------------------------------------------------


def load_occurrences(
    db: Session,
    spec,
) -> Tuple[ScientificDataset, List[HistoricalOccurrence]]:
    """Load the occurrence rows for the training spec.

    Returns the dataset record and the rows. The dataset is loaded by
    the explicit ``spec.occurrence_dataset_id``; it is NOT derived from
    the species name or filename.

    Validates:
    - dataset exists
    - dataset_type is compatible with occurrence training
    - dataset species (if any) matches the spec species
    - dataset geographic scope matches the spec (strict — no relaxation
      for occurrence data: a JURISDICTION-scoped training spec needs a
      jurisdiction-scoped occurrence dataset)
    - rows actually belong to the selected dataset (the dataset_id
      column on each row must match the loaded dataset)
    """
    dataset = _resolve_dataset(
        db,
        spec.occurrence_dataset_id,
        ACCEPTED_OCCURRENCE_DATASET_TYPES,
        "occurrence",
    )
    _validate_occurrence_scope(db, dataset, spec)
    rows = (
        db.query(HistoricalOccurrence)
        .filter(HistoricalOccurrence.dataset_id == dataset.id)
        .all()
    )
    # Defensive invariant: every loaded row must belong to the
    # resolved dataset. This is a schema-level constraint already, but
    # we assert it here as a reproducibility guard.
    for row in rows:
        if row.dataset_id != dataset.id:
            raise ValueError(
                f"HistoricalOccurrence {row.id} has dataset_id={row.dataset_id}; "
                f"expected {dataset.id} from dataset {dataset.slug!r}"
            )
    return dataset, rows


# ----------------------------------------------------------------------
# Environmental loader
# ----------------------------------------------------------------------


def load_environmental(
    db: Session,
    spec,
) -> List[Tuple[ScientificDataset, List[PredictionSampleEnvironmentalFeature]]]:
    """Load the environmental features for the training spec.

    For each dataset_id in ``spec.environmental_dataset_ids``:

    - Resolve the dataset and validate it exists and is ACTIVE.
    - Validate compatibility with the spec (scope, species).
    - Apply the relaxation rule for region-scoped datasets claimed
      against a jurisdiction-scoped spec (currently conservative).
    - Load the ``PredictionSampleEnvironmentalFeature`` rows whose
      ``scientific_dataset_id`` matches the requested dataset. This is
      the primary ownership mechanism introduced by Phase 10E-1:
      each row carries an explicit ``scientific_dataset_id`` FK and
      can only be returned for the dataset that owns it.
    - Validate that every returned row's ``feature_version`` equals
      ``spec.feature_version``. This is a consistency check, not a
      load filter, because the primary ownership mechanism is the FK.
      Rows whose feature_version does not match the spec are reported
      as a hard error so silent drift cannot occur.
    """
    out: List[
        Tuple[ScientificDataset, List[PredictionSampleEnvironmentalFeature]]
    ] = []
    for dataset_id in spec.environmental_dataset_ids:
        dataset = _resolve_dataset(
            db,
            dataset_id,
            ACCEPTED_ENVIRONMENTAL_DATASET_TYPES,
            "environmental",
        )
        _validate_occurrence_scope(
            db,
            dataset,
            spec,
            allow_region_to_jurisdiction_relaxation=True,
        )
        rows = (
            db.query(PredictionSampleEnvironmentalFeature)
            .filter(
                PredictionSampleEnvironmentalFeature.scientific_dataset_id
                == dataset.id
            )
            .all()
        )
        if not rows:
            raise ValueError(
                f"ScientificDataset {dataset.id} has no "
                f"PredictionSampleEnvironmentalFeature rows owned by it"
            )
        # Consistency check: every row owned by this dataset must
        # carry the spec's feature_version. If not, fail loudly.
        mismatched = [
            (row.id, row.feature_version)
            for row in rows
            if row.feature_version != spec.feature_version
        ]
        if mismatched:
            raise ValueError(
                f"ScientificDataset {dataset.id} owns "
                f"{len(mismatched)} PredictionSampleEnvironmentalFeature "
                f"row(s) with feature_version != "
                f"spec.feature_version={spec.feature_version!r} "
                f"(examples={mismatched[:3]})"
            )
        out.append((dataset, rows))
    return out


# ----------------------------------------------------------------------
# Input bundle
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SuitabilityTrainingInputs:
    """Immutable input bundle produced by the Phase 10D-2 loaders.

    Carries the resolved occurrence dataset and rows and the
    resolved environmental datasets and feature rows. Does not
    carry credentials, raw acquisition manifests, or any other
    sensitive content. The provenance summary exposes only
    sanitized copy fields.
    """

    occurrence_dataset: ScientificDataset
    occurrence_rows: Tuple[HistoricalOccurrence, ...]
    environmental_datasets: Tuple[
        Tuple[ScientificDataset, Tuple[PredictionSampleEnvironmentalFeature, ...]],
        ...,
    ]
    provenance_summary: Dict[str, Any] = field(default_factory=dict)

    def occurrence_summary(self) -> DatasetProvenanceSummary:
        return _summarize_dataset(self.occurrence_dataset)

    def environmental_summaries(self):
        return [
            (record, _summarize_dataset(record))
            for record, _ in self.environmental_datasets
        ]


def load_training_inputs(
    db: Session,
    spec,
) -> SuitabilityTrainingInputs:
    """Convenience that runs both loaders.

    This is the single entry point the future training engine would
    call. It does NOT perform training, does NOT perform grid
    prediction, and does NOT create SuitabilityDeployment.
    """
    occurrence_dataset, occurrence_rows = load_occurrences(db, spec)
    environmental = load_environmental(db, spec)
    provenance_summary = {
        "occurrence": _summarize_dataset(occurrence_dataset),
        "environmental": [
            _summarize_dataset(record) for record, _ in environmental
        ],
    }
    return SuitabilityTrainingInputs(
        occurrence_dataset=occurrence_dataset,
        occurrence_rows=tuple(occurrence_rows),
        environmental_datasets=tuple(
            (record, tuple(feature_rows)) for record, feature_rows in environmental
        ),
        provenance_summary=provenance_summary,
    )