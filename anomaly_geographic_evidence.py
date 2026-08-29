"""Phase 11C-2 generic descriptive geographic occurrence evidence.

The result describes documented evidence only. It contains no range, rarity,
novelty, anomaly, or ecological-connectivity interpretation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from math import floor

from shapely.geometry import Point, shape
from sqlalchemy.orm import Session

from anomaly_evidence_readiness import (
    DuplicateState,
    IdentitySource,
    dataset_is_jurisdiction_compatible,
    resolve_observation_identity,
)
from anomaly_repository import canonical_json
from geographic_utils import haversine_km
from models import HistoricalOccurrence, JurisdictionBoundary, Observation, ScientificDataset
from scientific_applicability_domain import EvidenceRole
from scientific_dataset_applicability import applicability_dependency, authorized_applicability


GEOGRAPHIC_EVIDENCE_METHOD_VERSION = "descriptive-geographic-evidence-v1"
DISTANCE_METRIC_DESCRIPTION = (
    "straight-line great-circle distance to documented occurrence evidence"
)


@dataclass(frozen=True)
class GeographicEvidenceResult:
    observation_id: int
    jurisdiction_id: int | None
    evaluated_species: str | None
    identity_source: str
    duplicate_state: str
    contributes_independent_evidence: bool
    evidence_availability: str
    occurrence_dataset_ids: tuple[int, ...]
    historical_record_count: int
    nearest_occurrence_distance_km: float | None
    nearest_occurrence_id: int | None
    distance_metric_description: str
    grid_resolution_degrees: float
    occupied_cell_count: int
    nearest_occupied_cell_distance_km: float | None
    nearest_occupied_cell_latitude: float | None
    nearest_occupied_cell_longitude: float | None
    inside_documented_occurrence_envelope: bool | None
    historical_min_latitude: float | None
    historical_max_latitude: float | None
    historical_min_longitude: float | None
    historical_max_longitude: float | None
    jurisdiction_boundary_membership: str
    boundary_id: int | None
    records_inside_jurisdiction_boundary: int | None
    records_outside_jurisdiction_boundary: int | None
    boundary_reconciliation_status: str
    records_with_dates: int
    records_without_dates: int
    earliest_historical_record: str | None
    latest_historical_record: str | None
    provenance_json: str
    limitations: tuple[str, ...]
    dependency_fingerprint: str

    def as_dict(self) -> dict:
        value = asdict(self)
        value["occurrence_dataset_ids"] = list(self.occurrence_dataset_ids)
        value["limitations"] = list(self.limitations)
        return value


class GeographicEvidenceService:
    def __init__(self, session: Session, grid_resolution_degrees: float):
        if grid_resolution_degrees <= 0:
            raise ValueError("grid_resolution_degrees must be positive")
        self.session = session
        self.grid_resolution_degrees = float(grid_resolution_degrees)

    def evaluate_observation(self, observation_id: int) -> GeographicEvidenceResult:
        observation = self.session.get(Observation, observation_id)
        if observation is None:
            raise LookupError(f"Observation {observation_id} was not found")
        identity = resolve_observation_identity(observation)
        jurisdiction = observation.jurisdiction
        boundary, boundary_status = self._resolve_boundary(observation.jurisdiction_id)
        duplicate_state = (
            DuplicateState.DUPLICATE_OF_OBSERVATION
            if observation.duplicate_of_observation_id is not None
            else DuplicateState.POSSIBLE_DUPLICATE
            if observation.is_possible_duplicate
            else DuplicateState.NOT_DUPLICATE
        )
        contributes = duplicate_state is DuplicateState.NOT_DUPLICATE

        datasets = self._authorized_datasets(identity, jurisdiction)
        dataset_ids = tuple(dataset.id for dataset in datasets)
        occurrences = []
        if dataset_ids:
            occurrences = (
                self.session.query(HistoricalOccurrence)
                .filter(
                    HistoricalOccurrence.dataset_id.in_(dataset_ids),
                    HistoricalOccurrence.scientific_name == identity.species,
                )
                .order_by(HistoricalOccurrence.id)
                .all()
            )

        nearest_distance, nearest_id = self._nearest_occurrence(observation, occurrences)
        cells = self._occupied_cells(occurrences)
        cell_distance, cell_latitude, cell_longitude = self._nearest_cell(observation, cells)
        extent = self._extent(occurrences)
        envelope_membership = None
        if extent is not None:
            envelope_membership = (
                extent[0] <= observation.latitude <= extent[1]
                and extent[2] <= observation.longitude <= extent[3]
            )

        boundary_membership = "UNKNOWN"
        inside_count = outside_count = None
        reconciliation = boundary_status
        if boundary is not None:
            geometry = shape(json.loads(boundary.geometry_json))
            boundary_membership = (
                "INSIDE_OR_ON_BOUNDARY"
                if geometry.covers(Point(observation.longitude, observation.latitude))
                else "OUTSIDE"
            )
            inside_count = sum(
                geometry.covers(Point(row.longitude, row.latitude)) for row in occurrences
            )
            outside_count = len(occurrences) - inside_count
            reconciliation = (
                "NO_RECORDS" if not occurrences
                else "ALL_RECORDS_INSIDE_OR_ON_BOUNDARY" if outside_count == 0
                else "RECORDS_OUTSIDE_BOUNDARY_PRESENT"
            )

        dates = sorted(row.event_date for row in occurrences if row.event_date is not None)
        limitations = [
            "Distances are descriptive great-circle measurements, not ecological connectivity.",
            "The coordinate envelope describes documented records and is not a biological range.",
            "Occurrence-record absence does not establish biological absence.",
            "Record density and boundary reconciliation may reflect sampling and acquisition methods.",
        ]
        if identity.source is IdentitySource.UNRESOLVED:
            limitations.append("Species identity is unresolved; no occurrence datasets were authorized.")
        if boundary is None:
            limitations.append("A single active jurisdiction boundary was not available.")
        if outside_count:
            limitations.append("Some authorized dataset records fall outside the active jurisdiction boundary; none were deleted or excluded.")

        occurrence_digest_payload = [
            {
                "id": row.id,
                "dataset_id": row.dataset_id,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "event_date": None if row.event_date is None else row.event_date.isoformat(),
                "occurrence_id": row.occurrence_id,
                "deduplication_key": row.deduplication_key,
            }
            for row in occurrences
        ]
        occurrence_digest = hashlib.sha256(
            canonical_json(occurrence_digest_payload).encode("utf-8")
        ).hexdigest()
        dataset_provenance = [
            {
                "id": dataset.id,
                "slug": dataset.slug,
                "scope": dataset.geographic_scope_type,
                "region_id": dataset.region_id,
                "jurisdiction_id": dataset.jurisdiction_id,
                "source_name": dataset.source_name,
                "source_version": dataset.source_version,
                "artifact_sha256": dataset.artifact_sha256,
                "applicability": applicability_dependency(
                    authorized_applicability(
                        self.session, dataset.id, jurisdiction.id,
                        EvidenceRole.GEOGRAPHIC_EVIDENCE,
                    )
                    if (dataset.geographic_scope_type or "").upper() in {"REGION", "GLOBAL"}
                    else None
                ),
            }
            for dataset in datasets
        ]
        boundary_provenance = None if boundary is None else {
            "id": boundary.id,
            "boundary_type": boundary.boundary_type,
            "source": boundary.source,
            "source_version": boundary.source_version,
            "source_reference": boundary.source_reference,
            "geometry_hash": boundary.geometry_hash,
            "geometry_content_sha256": hashlib.sha256(
                boundary.geometry_json.encode("utf-8")
            ).hexdigest(),
        }
        provenance = {
            "method_version": GEOGRAPHIC_EVIDENCE_METHOD_VERSION,
            "observation": {
                "id": observation.id,
                "jurisdiction_id": observation.jurisdiction_id,
                "latitude": observation.latitude,
                "longitude": observation.longitude,
            },
            "evaluated_species": identity.species,
            "identity_source": identity.source.value,
            "duplicate_state": duplicate_state.value,
            "occurrence_datasets": dataset_provenance,
            "historical_record_count": len(occurrences),
            "occurrence_evidence_sha256": occurrence_digest,
            "boundary": boundary_provenance,
            "grid_resolution_degrees": self.grid_resolution_degrees,
            "distance_metric": DISTANCE_METRIC_DESCRIPTION,
        }
        provenance_json = canonical_json(provenance)
        fingerprint = hashlib.sha256(provenance_json.encode("utf-8")).hexdigest()

        return GeographicEvidenceResult(
            observation_id=observation.id,
            jurisdiction_id=observation.jurisdiction_id,
            evaluated_species=identity.species,
            identity_source=identity.source.value,
            duplicate_state=duplicate_state.value,
            contributes_independent_evidence=contributes,
            evidence_availability=(
                "UNRESOLVED_IDENTITY" if identity.species is None
                else "AVAILABLE" if occurrences
                else "UNAVAILABLE"
            ),
            occurrence_dataset_ids=dataset_ids,
            historical_record_count=len(occurrences),
            nearest_occurrence_distance_km=(
                None if nearest_distance is None else round(nearest_distance, 6)
            ),
            nearest_occurrence_id=nearest_id,
            distance_metric_description=DISTANCE_METRIC_DESCRIPTION,
            grid_resolution_degrees=self.grid_resolution_degrees,
            occupied_cell_count=len(cells),
            nearest_occupied_cell_distance_km=(
                None if cell_distance is None else round(cell_distance, 6)
            ),
            nearest_occupied_cell_latitude=cell_latitude,
            nearest_occupied_cell_longitude=cell_longitude,
            inside_documented_occurrence_envelope=envelope_membership,
            historical_min_latitude=None if extent is None else extent[0],
            historical_max_latitude=None if extent is None else extent[1],
            historical_min_longitude=None if extent is None else extent[2],
            historical_max_longitude=None if extent is None else extent[3],
            jurisdiction_boundary_membership=boundary_membership,
            boundary_id=None if boundary is None else boundary.id,
            records_inside_jurisdiction_boundary=inside_count,
            records_outside_jurisdiction_boundary=outside_count,
            boundary_reconciliation_status=reconciliation,
            records_with_dates=len(dates),
            records_without_dates=len(occurrences) - len(dates),
            earliest_historical_record=None if not dates else dates[0].isoformat(),
            latest_historical_record=None if not dates else dates[-1].isoformat(),
            provenance_json=provenance_json,
            limitations=tuple(limitations),
            dependency_fingerprint=fingerprint,
        )

    def _authorized_datasets(self, identity, jurisdiction):
        if identity.species is None or jurisdiction is None:
            return []
        datasets = self.session.query(ScientificDataset).filter(
            ScientificDataset.status == "ACTIVE",
            ScientificDataset.dataset_type.ilike("%OCCURRENCE%"),
        ).order_by(ScientificDataset.id).all()
        return [
            dataset for dataset in datasets
            if self._dataset_matches_species(dataset, identity.species)
            and dataset_is_jurisdiction_compatible(
                dataset, jurisdiction, self.session, EvidenceRole.GEOGRAPHIC_EVIDENCE
            )
        ]

    @staticmethod
    def _dataset_matches_species(dataset, species):
        if dataset.species_program_record is not None:
            return dataset.species_program_record.scientific_name == species
        if dataset.species_record is not None:
            return dataset.species_record.scientific_name == species
        return False

    def _resolve_boundary(self, jurisdiction_id):
        if jurisdiction_id is None:
            return None, "NO_JURISDICTION"
        rows = self.session.query(JurisdictionBoundary).filter(
            JurisdictionBoundary.jurisdiction_id == jurisdiction_id,
            JurisdictionBoundary.status == "ACTIVE",
            JurisdictionBoundary.boundary_type == "MARINE_MONITORING",
        ).order_by(JurisdictionBoundary.id).all()
        if not rows:
            return None, "NO_ACTIVE_BOUNDARY"
        if len(rows) > 1:
            return None, "AMBIGUOUS_ACTIVE_BOUNDARY"
        return rows[0], "BOUNDARY_AVAILABLE"

    @staticmethod
    def _nearest_occurrence(observation, occurrences):
        if not occurrences:
            return None, None
        ranked = sorted(
            (
                haversine_km(
                    observation.latitude, observation.longitude,
                    row.latitude, row.longitude,
                ),
                row.id,
            )
            for row in occurrences
        )
        return ranked[0]

    def _occupied_cells(self, occurrences):
        resolution = self.grid_resolution_degrees
        return sorted({
            (
                round(floor(row.latitude / resolution) * resolution + resolution / 2, 10),
                round(floor(row.longitude / resolution) * resolution + resolution / 2, 10),
            )
            for row in occurrences
        })

    @staticmethod
    def _nearest_cell(observation, cells):
        if not cells:
            return None, None, None
        ranked = sorted(
            (
                haversine_km(
                    observation.latitude, observation.longitude, latitude, longitude
                ),
                latitude,
                longitude,
            )
            for latitude, longitude in cells
        )
        return ranked[0]

    @staticmethod
    def _extent(occurrences):
        if not occurrences:
            return None
        latitudes = [row.latitude for row in occurrences]
        longitudes = [row.longitude for row in occurrences]
        return min(latitudes), max(latitudes), min(longitudes), max(longitudes)


__all__ = [
    "GeographicEvidenceService", "GeographicEvidenceResult",
    "GEOGRAPHIC_EVIDENCE_METHOD_VERSION", "DISTANCE_METRIC_DESCRIPTION",
]
