"""Phase 10E-4 dataset artifact repository.

Implements the chain-of-custody helpers for ScientificDataset
artifacts and TrainingRun input integrity.

Public API:

- ``register_dataset_artifact(db, dataset, artifact_path,
   artifact_format=None, expected_record_count=None)``
   Persist a controlled artifact for a ScientificDataset. The file
   MUST exist; the SHA-256 is computed byte-for-byte and persisted
   on the dataset row. If the dataset is already linked to a
   COMPLETED native TrainingRun whose dataset artifact_sha256
   differs, the call is refused with ``ValueError``.

- ``verify_dataset_artifact(dataset, artifact_path=None)``
   Re-read the artifact from disk (or accept a precomputed SHA)
   and confirm the bytes still match the persisted
   ``ScientificDataset.artifact_sha256``.

- ``compute_training_input_sha256(db, run)``
   Compute a deterministic SHA-256 over the ordered
   TrainingRunDataset links for ``run``. Returns
   ``(sha, integrity_status)``. If any linked dataset has a NULL
   ``artifact_sha256``, ``integrity_status`` is ``PARTIAL``;
   otherwise it is ``COMPLETE``.

- ``persist_training_input_sha256(db, run)``
   Convenience wrapper that calls ``compute_training_input_sha256``
   and writes the result to the TrainingRun row.

- ``verify_model_artifact_chain(run, deployment=None)``
   Read-only validation that ``run.artifact_sha256`` matches the
   bytes on disk and (when ``deployment`` is provided) matches
   ``deployment.artifact_hash``. Raises ``ValueError`` on mismatch.

- ``find_datasets_used_by_completed_runs(db, dataset)``
   Return the count of COMPLETED TrainingRuns that link to
   ``dataset``. Used by the immutability guard.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import models
from models import (
    ScientificDataset,
    SuitabilityDeployment,
    TrainingRun,
    TrainingRunDataset,
)


logger = logging.getLogger(__name__)


# Integrity status constants.
INTEGRITY_NOT_COMPUTED = "NOT_COMPUTED"
INTEGRITY_PARTIAL = "PARTIAL"
INTEGRITY_COMPLETE = "COMPLETE"


# Role vocabulary (mirrors Phase 10E-2).
ROLE_TRAINING_OCCURRENCES = "TRAINING_OCCURRENCES"
ROLE_ENVIRONMENTAL_INPUT = "ENVIRONMENTAL_INPUT"
ROLE_VALIDATION_INPUT = "VALIDATION_INPUT"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_datasets_used_by_completed_runs(
    db: Session, dataset: ScientificDataset
) -> int:
    """Return the count of COMPLETED native TrainingRuns that
    link to ``dataset`` via TrainingRunDataset."""
    return (
        db.query(TrainingRunDataset)
        .join(TrainingRun, TrainingRun.id == TrainingRunDataset.training_run_id)
        .filter(
            TrainingRunDataset.scientific_dataset_id == dataset.id,
            TrainingRun.status == "COMPLETED",
            TrainingRun.provenance_origin == "NATIVE",
        )
        .count()
    )


def register_dataset_artifact(
    db: Session,
    dataset: ScientificDataset,
    artifact_path: str,
    *,
    artifact_format: Optional[str] = None,
    expected_record_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Persist a controlled artifact for a ScientificDataset.

    Behaviour:

    - ``artifact_path`` MUST be a file on local disk; ``FileNotFoundError``
      is raised if it does not exist.
    - The SHA-256 of the file bytes is computed and persisted as
      ``ScientificDataset.artifact_sha256``.
    - ``ScientificDataset.artifact_path`` is persisted as the
      caller-supplied ``artifact_path``.
    - ``ScientificDataset.artifact_format`` is updated if supplied.
    - If the dataset has an existing ``artifact_sha256`` and the new
      SHA differs, AND the dataset is currently linked to at least
      one COMPLETED native TrainingRun, the call is refused with
      ``ValueError`` (chain-of-custody protection).
    - If ``expected_record_count`` is supplied and differs from
      ``dataset.record_count``, the call is refused with
      ``ValueError``.

    Returns a small summary describing what was done.
    """
    if not os.path.exists(artifact_path):
        raise FileNotFoundError(artifact_path)
    if not os.path.isfile(artifact_path):
        raise ValueError(f"{artifact_path!r} is not a regular file")
    new_sha = _sha256_file(artifact_path)
    new_size = os.path.getsize(artifact_path)

    summary = {
        "dataset_id": dataset.id,
        "artifact_path_set": False,
        "artifact_sha256_set": False,
        "format_set": False,
        "record_count_verified": False,
        "refused_for_chain_of_custody": False,
    }

    if (
        dataset.artifact_sha256 is not None
        and dataset.artifact_sha256 != new_sha
        and find_datasets_used_by_completed_runs(db, dataset) > 0
    ):
        summary["refused_for_chain_of_custody"] = True
        raise ValueError(
            f"ScientificDataset {dataset.id} already has artifact_sha256="
            f"{dataset.artifact_sha256} and is used by COMPLETED native "
            f"TrainingRuns; refusing to silently replace with "
            f"sha256={new_sha}."
        )

    if (
        expected_record_count is not None
        and dataset.record_count is not None
        and expected_record_count != dataset.record_count
    ):
        raise ValueError(
            f"ScientificDataset {dataset.id} record_count={dataset.record_count} "
            f"does not match expected_record_count={expected_record_count}"
        )

    if dataset.artifact_path != artifact_path:
        dataset.artifact_path = artifact_path
        summary["artifact_path_set"] = True
    if dataset.artifact_sha256 != new_sha:
        dataset.artifact_sha256 = new_sha
        summary["artifact_sha256_set"] = True
    if artifact_format is not None and dataset.acquisition_manifest_json != artifact_format:
        # Reuse the acquisition_manifest_json field for the format
        # string. We store JSON so future callers can introspect.
        try:
            existing = json.loads(dataset.acquisition_manifest_json or "{}")
        except (TypeError, ValueError):
            existing = {}
        if existing.get("artifact_format") != artifact_format:
            existing["artifact_format"] = artifact_format
            existing["artifact_size_bytes"] = new_size
            dataset.acquisition_manifest_json = json.dumps(existing)
            summary["format_set"] = True
    summary["record_count_verified"] = (
        expected_record_count is not None
        and dataset.record_count == expected_record_count
    )
    db.flush()
    return summary


def verify_dataset_artifact(
    dataset: ScientificDataset,
    artifact_path: Optional[str] = None,
    precomputed_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-read the artifact and confirm the bytes match.

    If both ``artifact_path`` and ``precomputed_sha`` are None, the
    function uses ``dataset.artifact_path`` (and reads from disk)
    if available; otherwise the dataset is reported as
    ``NO_CONTROLLED_SOURCE_ARTIFACT``.

    Returns a small summary describing the verification outcome.
    """
    summary = {
        "dataset_id": dataset.id,
        "stored_sha256": dataset.artifact_sha256,
        "verified": False,
        "status": "NO_CONTROLLED_SOURCE_ARTIFACT",
    }
    if dataset.artifact_sha256 is None and precomputed_sha is None:
        return summary
    expected = dataset.artifact_sha256 or precomputed_sha
    if precomputed_sha is not None:
        summary["actual_sha256"] = precomputed_sha
        summary["verified"] = (precomputed_sha == expected)
        summary["status"] = "COMPLETE" if summary["verified"] else "MISMATCH"
        return summary
    path = artifact_path or dataset.artifact_path
    if path is None or not os.path.exists(path):
        summary["status"] = "MISSING_FILE"
        return summary
    actual = _sha256_file(path)
    summary["actual_sha256"] = actual
    summary["artifact_path"] = path
    summary["verified"] = actual == expected
    summary["status"] = "COMPLETE" if summary["verified"] else "MISMATCH"
    return summary


def compute_training_input_sha256(
    db: Session, run: TrainingRun
) -> Tuple[Optional[str], str]:
    """Compute a deterministic SHA-256 over the TrainingRun
    dataset links.

    Each link contributes a canonical tuple:

        (role, dataset_id, dataset_slug, artifact_sha256_or_null,
         record_count_or_null, source_version_or_null)

    Tuples are sorted by ``(role, dataset_id)`` so the hash is
    stable regardless of insertion order. Datasets lacking a
    populated ``artifact_sha256`` do not prevent the hash; they
    simply contribute NULL for that field, and the integrity
    status is reported as ``PARTIAL`` if at least one link is
    missing the artifact SHA.
    """
    links = (
        db.query(TrainingRunDataset, ScientificDataset)
        .join(
            ScientificDataset,
            ScientificDataset.id == TrainingRunDataset.scientific_dataset_id,
        )
        .filter(TrainingRunDataset.training_run_id == run.id)
        .all()
    )
    if not links:
        return None, INTEGRITY_NOT_COMPUTED
    entries: List[Dict[str, Any]] = []
    any_missing_artifact_sha = False
    for link, dataset in links:
        entry = {
            "role": link.role,
            "dataset_id": dataset.id,
            "dataset_slug": dataset.slug,
            "artifact_sha256": dataset.artifact_sha256,
            "record_count": dataset.record_count,
            "source_version": dataset.source_version,
        }
        entries.append(entry)
        if dataset.artifact_sha256 is None:
            any_missing_artifact_sha = True
    entries.sort(key=lambda e: (e["role"], e["dataset_id"]))
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    integrity = INTEGRITY_PARTIAL if any_missing_artifact_sha else INTEGRITY_COMPLETE
    return sha, integrity


def persist_training_input_sha256(
    db: Session, run: TrainingRun
) -> Tuple[Optional[str], str]:
    """Compute and persist the TrainingRun input integrity hash.

    The returned tuple is ``(sha, integrity_status)``. The persisted
    fields are ``training_input_sha256`` and
    ``input_integrity_status``.
    """
    sha, integrity = compute_training_input_sha256(db, run)
    run.training_input_sha256 = sha
    run.input_integrity_status = integrity
    db.flush()
    return sha, integrity


def verify_model_artifact_chain(
    db: Session,
    run: TrainingRun,
    deployment: Optional[SuitabilityDeployment] = None,
) -> Dict[str, Any]:
    """Read-only validation that the model artifact chain is
    internally consistent.

    Checks (in order):

    - If ``run.artifact_sha256`` is None, ``NO_CONTROLLED_ARTIFACT``
      is returned (cannot verify).
    - The artifact on disk at ``run.artifact_path`` is hashed and
      compared to ``run.artifact_sha256``.
    - If ``deployment`` is supplied, its ``artifact_hash`` is
      compared to ``run.artifact_sha256``.
    """
    summary = {
        "run_id": run.id,
        "model_version": run.model_version,
        "run_artifact_sha256": run.artifact_sha256,
        "actual_artifact_sha256": None,
        "matches_run_sha": False,
        "deployment_artifact_hash": (
            deployment.artifact_hash if deployment is not None else None
        ),
        "matches_deployment": None,
        "status": "NO_CONTROLLED_ARTIFACT",
    }
    if run.artifact_sha256 is None:
        return summary
    if run.artifact_path is None or not os.path.exists(run.artifact_path):
        summary["status"] = "MISSING_FILE"
        return summary
    actual = _sha256_file(run.artifact_path)
    summary["actual_artifact_sha256"] = actual
    summary["matches_run_sha"] = actual == run.artifact_sha256
    if deployment is not None:
        summary["matches_deployment"] = (
            deployment.artifact_hash == run.artifact_sha256
        )
    if not summary["matches_run_sha"]:
        summary["status"] = "MISMATCH"
    elif (
        deployment is not None and not summary["matches_deployment"]
    ):
        summary["status"] = "MISMATCH"
    else:
        summary["status"] = "COMPLETE"
    return summary


# ---------------------------------------------------------------------------
# Test helper: build a complete NATIVE TrainingRun in one call.
# ---------------------------------------------------------------------------


def create_completed_native_run_for_test(
    db: Session,
    *,
    program_id: int,
    occ_id: int,
    env_id: int,
    occ_artifact_sha: Optional[str] = None,
    env_artifact_sha: Optional[str] = None,
    occ_artifact_path: Optional[str] = None,
    env_artifact_path: Optional[str] = None,
    model_artifact_path: Optional[str] = None,
    model_artifact_sha: Optional[str] = None,
) -> TrainingRun:
    """Test helper: build a COMPLETED native TrainingRun with
    dataset links and a controlled artifact. The helper calls
    ``record_training_completion`` with ``skip_validation=False`` so
    the Phase 10E-3 + 10E-4 invariants are enforced. If any input
    dataset lacks an artifact SHA, the helper will raise.
    """
    from suitability_training_run_repository import (
        ORIGIN_NATIVE, ROLE_ENVIRONMENTAL_INPUT, ROLE_TRAINING_OCCURRENCES,
        SuitabilityTrainingSpec, create_training_run, link_training_run_dataset,
        record_training_completion,
    )
    from suitability_training_engine import (
        SuitabilityCandidateResult, SuitabilityTrainingResult,
    )
    from suitability_training_spec import SuitabilityGrid
    from sklearn.linear_model import LogisticRegression

    # Populate artifact fields on the dataset rows if requested.
    occ = (
        db.query(ScientificDataset)
        .filter(ScientificDataset.id == occ_id)
        .one()
    )
    env = (
        db.query(ScientificDataset)
        .filter(ScientificDataset.id == env_id)
        .one()
    )
    if occ_artifact_sha is not None:
        occ.artifact_sha256 = occ_artifact_sha
    if occ_artifact_path is not None:
        occ.artifact_path = occ_artifact_path
    if env_artifact_sha is not None:
        env.artifact_sha256 = env_artifact_sha
    if env_artifact_path is not None:
        env.artifact_path = env_artifact_path
    db.flush()

    grid = SuitabilityGrid(
        grid_size_degrees=0.1, bounds=(-77.5, -77.0, 18.0, 18.5),
        name="g",
    )
    spec = SuitabilityTrainingSpec(
        species="Hyp sp.", species_program_id=program_id,
        geographic_scope="JURISDICTION", region_id=1, jurisdiction_id=1,
        occurrence_dataset_id=occ_id,
        environmental_dataset_ids=(env_id,),
        background_extent_bounds={
            "latitude_min": 9.0, "latitude_max": 28.0,
            "longitude_min": -89.0, "longitude_max": -59.0,
        },
        spatial_block_origin={
            "latitude_origin": 9.0, "longitude_origin": -89.0,
        },
        grid=grid, model_version="hyp-v1",
        feature_version="hyp-env-v1",
        generation_version="hyp-gen-v1",
    )
    run = create_training_run(db, spec)
    link_training_run_dataset(db, run, occ, ROLE_TRAINING_OCCURRENCES)
    link_training_run_dataset(db, run, env, ROLE_ENVIRONMENTAL_INPUT)
    result = SuitabilityTrainingResult(
        spec_snapshot=dataclasses.asdict(spec),
        candidate_results={
            "model_b_physical_habitat": SuitabilityCandidateResult(
                name="model_b_physical_habitat",
                features=("a", "b"),
                algorithm="LogisticRegression", nonlinear=False,
                fold_metrics=[{"roc_auc": 0.7}],
                aggregate={
                    "roc_auc": {"mean": 0.7, "std": 0.0},
                    "average_precision": {"mean": 0.7, "std": 0.0},
                },
                extra={},
            ),
        },
        selected_candidate_name="model_b_physical_habitat",
        selection_rationale={"rule": "test"},
        fitted_model=LogisticRegression(),
        selected_feature_names=("a", "b"),
        training_sample_count=10,
        presence_count=5,
        background_count=5,
        feature_names=("a", "b"),
        dataset_provenance={},
        warnings=[],
        feature_version="hyp-env-v1",
        model_version="hyp-v1",
        generation_version="hyp-gen-v1",
    )
    if model_artifact_path is not None and model_artifact_sha is not None:
        return record_training_completion(
            db, run, result,
            artifact_path=model_artifact_path,
            artifact_sha256=model_artifact_sha,
        )
    return record_training_completion(db, run, result)


__all__ = [
    "INTEGRITY_NOT_COMPUTED",
    "INTEGRITY_PARTIAL",
    "INTEGRITY_COMPLETE",
    "ROLE_TRAINING_OCCURRENCES",
    "ROLE_ENVIRONMENTAL_INPUT",
    "ROLE_VALIDATION_INPUT",
    "find_datasets_used_by_completed_runs",
    "register_dataset_artifact",
    "verify_dataset_artifact",
    "compute_training_input_sha256",
    "persist_training_input_sha256",
    "verify_model_artifact_chain",
    "create_completed_native_run_for_test",
]