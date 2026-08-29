"""Phase 11C-3 isolated candidate geographic-baseline experiments."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from math import floor
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPoint, Point, mapping, shape

from anomaly_evidence_readiness import dataset_is_jurisdiction_compatible
from scientific_applicability_domain import EvidenceRole
from anomaly_repository import canonical_json
from geographic_utils import haversine_km
from models import HistoricalOccurrence, Jurisdiction, JurisdictionBoundary, ScientificDataset


EXPERIMENT_METHOD_VERSION = "geographic-candidate-experiment-v1"


@dataclass(frozen=True)
class ExperimentPoint:
    latitude: float
    longitude: float
    event_date: str | None
    source: str
    source_occurrence_ids: tuple[int, ...]


@dataclass(frozen=True)
class ExperimentVariant:
    species: str
    jurisdiction_id: int
    name: str
    source_dataset_ids: tuple[int, ...]
    points: tuple[ExperimentPoint, ...]
    source_occurrence_ids: tuple[int, ...]
    excluded_occurrence_ids: tuple[int, ...]
    grouped_occurrence_ids: tuple[int, ...]
    transformation_method: str
    boundary_provenance_json: str
    configuration_json: str
    input_fingerprint: str


@dataclass(frozen=True)
class ExperimentResult:
    species: str
    jurisdiction_id: int
    source_dataset_ids: tuple[int, ...]
    dataset_variant: str
    method: str
    method_version: str
    configuration_json: str
    configuration_sha256: str
    record_count: int
    unique_coordinate_count: int
    grouped_event_count: int
    output_json: str
    provenance_json: str
    input_fingerprint: str
    result_fingerprint: str
    limitations: tuple[str, ...]


class GeographicBaselineExperiment:
    def __init__(self, session, species: str, jurisdiction_id: int, dataset_ids):
        self.session = session
        self.species = species
        self.jurisdiction_id = jurisdiction_id
        self.dataset_ids = tuple(sorted(set(int(item) for item in dataset_ids)))

    def create_variants(self) -> dict[str, ExperimentVariant]:
        jurisdiction = self.session.get(Jurisdiction, self.jurisdiction_id)
        if jurisdiction is None:
            raise LookupError(f"Jurisdiction {self.jurisdiction_id} was not found")
        datasets = self._authorized_datasets(jurisdiction)
        authorized_ids = tuple(dataset.id for dataset in datasets)
        rows = self.session.query(HistoricalOccurrence).filter(
            HistoricalOccurrence.dataset_id.in_(authorized_ids),
            HistoricalOccurrence.scientific_name == self.species,
        ).order_by(HistoricalOccurrence.id).all() if authorized_ids else []
        boundary = self._boundary()
        geometry = None if boundary is None else shape(json.loads(boundary.geometry_json))
        inside_rows = rows if geometry is None else [
            row for row in rows if geometry.covers(Point(row.longitude, row.latitude))
        ]
        return {
            "FULL_SOURCE": self._variant("FULL_SOURCE", rows, rows, boundary, False, authorized_ids),
            "JURISDICTION_RECONCILED": self._variant(
                "JURISDICTION_RECONCILED", inside_rows, rows, boundary, False, authorized_ids
            ),
            "EVENT_GROUPED": self._variant("EVENT_GROUPED", rows, rows, boundary, True, authorized_ids),
            "JURISDICTION_RECONCILED_EVENT_GROUPED": self._variant(
                "JURISDICTION_RECONCILED_EVENT_GROUPED", inside_rows, rows, boundary, True, authorized_ids
            ),
        }

    def analyze_variant(self, variant: ExperimentVariant, grid_resolutions) -> list[ExperimentResult]:
        resolutions = tuple(float(value) for value in grid_resolutions)
        if not resolutions or any(value <= 0 for value in resolutions):
            raise ValueError("At least one positive explicit grid resolution is required")
        loo = self._leave_one_out(variant.points)
        envelope = self._envelope(variant.points)
        convex = self._convex_envelope(variant.points)
        quantiles = self._distance_summary(loo)
        grid = {
            self._format_resolution(resolution): self._grid_summary(variant.points, resolution)
            for resolution in resolutions
        }
        configurations = {
            "NEAREST_EVIDENCE_DISTRIBUTION": {},
            "OBSERVED_ENVELOPE": {},
            "DOCUMENTED_CONVEX_ENVELOPE": {"geometry_coordinates": "longitude_latitude"},
            "DISTANCE_QUANTILE_CANDIDATE": {
                "quantiles": [0.5, 0.75, 0.9, 0.95],
                "interpretation": "descriptive_statistics_only",
            },
            "OCCUPIED_CELL_SENSITIVITY": {"grid_resolutions_degrees": list(resolutions)},
        }
        outputs = {
            "NEAREST_EVIDENCE_DISTRIBUTION": {
                "held_out": loo,
                "summary": self._distance_summary(loo),
                "self_exclusion": True,
            },
            "OBSERVED_ENVELOPE": envelope,
            "DOCUMENTED_CONVEX_ENVELOPE": convex,
            "DISTANCE_QUANTILE_CANDIDATE": quantiles,
            "OCCUPIED_CELL_SENSITIVITY": grid,
        }
        return [
            self._result(variant, method, configurations[method], outputs[method])
            for method in outputs
        ]

    @staticmethod
    def write_artifact(result: ExperimentResult, directory) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{result.dataset_variant.lower()}__{result.method.lower()}.json"
        path.write_text(canonical_json(asdict(result)), encoding="utf-8")
        return path

    def _authorized_datasets(self, jurisdiction):
        datasets = self.session.query(ScientificDataset).filter(
            ScientificDataset.id.in_(self.dataset_ids),
            ScientificDataset.status == "ACTIVE",
            ScientificDataset.dataset_type.ilike("%OCCURRENCE%"),
        ).order_by(ScientificDataset.id).all() if self.dataset_ids else []
        return [
            dataset for dataset in datasets
            if self._matches_species(dataset)
            and dataset_is_jurisdiction_compatible(
                dataset, jurisdiction, self.session, EvidenceRole.GEOGRAPHIC_EVIDENCE
            )
        ]

    def _matches_species(self, dataset):
        if dataset.species_program_record is not None:
            return dataset.species_program_record.scientific_name == self.species
        if dataset.species_record is not None:
            return dataset.species_record.scientific_name == self.species
        return False

    def _boundary(self):
        rows = self.session.query(JurisdictionBoundary).filter(
            JurisdictionBoundary.jurisdiction_id == self.jurisdiction_id,
            JurisdictionBoundary.status == "ACTIVE",
            JurisdictionBoundary.boundary_type == "MARINE_MONITORING",
        ).order_by(JurisdictionBoundary.id).all()
        if len(rows) != 1:
            raise ValueError("Exactly one active jurisdiction monitoring boundary is required")
        return rows[0]

    def _variant(self, name, selected_rows, all_rows, boundary, grouped, authorized_ids):
        groups = {}
        for row in selected_rows:
            event_date = None if row.event_date is None else row.event_date.isoformat()
            key = (
                row.latitude, row.longitude, event_date, row.source
            ) if grouped else (row.id,)
            groups.setdefault(key, []).append(row)
        points = []
        grouped_ids = []
        for key in sorted(groups, key=lambda value: canonical_json(value)):
            members = sorted(groups[key], key=lambda row: row.id)
            source_ids = tuple(row.id for row in members)
            if len(source_ids) > 1:
                grouped_ids.extend(source_ids[1:])
            first = members[0]
            points.append(ExperimentPoint(
                latitude=first.latitude,
                longitude=first.longitude,
                event_date=None if first.event_date is None else first.event_date.isoformat(),
                source=first.source,
                source_occurrence_ids=source_ids,
            ))
        selected_ids = tuple(sorted(row.id for row in selected_rows))
        all_ids = tuple(sorted(row.id for row in all_rows))
        boundary_provenance = {
            "id": boundary.id,
            "source": boundary.source,
            "source_version": boundary.source_version,
            "source_reference": boundary.source_reference,
            "geometry_hash": boundary.geometry_hash,
            "geometry_content_sha256": hashlib.sha256(
                boundary.geometry_json.encode("utf-8")
            ).hexdigest(),
        }
        configuration = {
            "boundary_reconciled": "RECONCILED" in name,
            "event_grouping": "EXACT_COORDINATE_EVENT_DATE_SOURCE" if grouped else "NONE",
        }
        payload = {
            "species": self.species,
            "jurisdiction_id": self.jurisdiction_id,
            "variant": name,
            "source_dataset_ids": list(authorized_ids),
            "points": [asdict(point) for point in points],
            "source_occurrence_ids": list(selected_ids),
            "excluded_occurrence_ids": sorted(set(all_ids) - set(selected_ids)),
            "boundary": boundary_provenance,
            "configuration": configuration,
        }
        return ExperimentVariant(
            species=self.species,
            jurisdiction_id=self.jurisdiction_id,
            name=name,
            source_dataset_ids=authorized_ids,
            points=tuple(points),
            source_occurrence_ids=selected_ids,
            excluded_occurrence_ids=tuple(sorted(set(all_ids) - set(selected_ids))),
            grouped_occurrence_ids=tuple(sorted(grouped_ids)),
            transformation_method=(
                "BOUNDARY_COVERS + EXACT_COORDINATE_EVENT_DATE_SOURCE"
                if grouped and "RECONCILED" in name else
                "EXACT_COORDINATE_EVENT_DATE_SOURCE" if grouped else
                "BOUNDARY_COVERS" if "RECONCILED" in name else "NONE"
            ),
            boundary_provenance_json=canonical_json(boundary_provenance),
            configuration_json=canonical_json(configuration),
            input_fingerprint=hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _leave_one_out(points):
        output = []
        for index, held_out in enumerate(points):
            candidates = [point for candidate_index, point in enumerate(points) if candidate_index != index]
            nearest = None
            if candidates:
                nearest = min(
                    haversine_km(
                        held_out.latitude, held_out.longitude,
                        candidate.latitude, candidate.longitude,
                    )
                    for candidate in candidates
                )
            output.append({
                "held_out_source_occurrence_ids": list(held_out.source_occurrence_ids),
                "remaining_candidate_event_count": len(candidates),
                "nearest_distance_km": None if nearest is None else round(nearest, 6),
            })
        return output

    @staticmethod
    def _distance_summary(held_out):
        values = [row["nearest_distance_km"] for row in held_out if row["nearest_distance_km"] is not None]
        if not values:
            return {key: None for key in ("minimum_km", "median_km", "mean_km", "q75_km", "q90_km", "q95_km", "maximum_km")}
        return {
            "minimum_km": min(values),
            "median_km": statistics.median(values),
            "mean_km": statistics.mean(values),
            "q75_km": float(np.quantile(values, 0.75)),
            "q90_km": float(np.quantile(values, 0.90)),
            "q95_km": float(np.quantile(values, 0.95)),
            "maximum_km": max(values),
        }

    @staticmethod
    def _envelope(points):
        if not points:
            return {"minimum_latitude": None, "maximum_latitude": None, "minimum_longitude": None, "maximum_longitude": None, "width_degrees": None, "height_degrees": None}
        latitudes = [point.latitude for point in points]
        longitudes = [point.longitude for point in points]
        minimum_latitude, maximum_latitude = min(latitudes), max(latitudes)
        minimum_longitude, maximum_longitude = min(longitudes), max(longitudes)
        return {
            "minimum_latitude": minimum_latitude, "maximum_latitude": maximum_latitude,
            "minimum_longitude": minimum_longitude, "maximum_longitude": maximum_longitude,
            "width_degrees": maximum_longitude - minimum_longitude,
            "height_degrees": maximum_latitude - minimum_latitude,
        }

    @staticmethod
    def _convex_envelope(points):
        geometry = MultiPoint([(point.longitude, point.latitude) for point in points]).convex_hull if points else MultiPoint([])
        return {
            "geometry": mapping(geometry),
            "geometry_type": geometry.geom_type,
            "planar_area_square_degrees": geometry.area,
            "interpretation": "documented_convex_envelope_only",
        }

    @staticmethod
    def _format_resolution(value):
        return format(value, ".10g")

    @classmethod
    def _grid_summary(cls, points, resolution):
        def cell(point):
            return (
                round(floor(point.latitude / resolution) * resolution + resolution / 2, 10),
                round(floor(point.longitude / resolution) * resolution + resolution / 2, 10),
            )
        occupied = sorted({cell(point) for point in points})
        held_out_distances = []
        for index, point in enumerate(points):
            remaining_cells = sorted({cell(candidate) for candidate_index, candidate in enumerate(points) if candidate_index != index})
            if remaining_cells:
                held_out_distances.append(min(
                    haversine_km(point.latitude, point.longitude, latitude, longitude)
                    for latitude, longitude in remaining_cells
                ))
        return {
            "grid_resolution_degrees": resolution,
            "occupied_cell_count": len(occupied),
            "occupied_cell_centers": [list(item) for item in occupied],
            "leave_one_out_nearest_cell_distance_summary": cls._distance_summary([
                {"nearest_distance_km": round(value, 6)} for value in held_out_distances
            ]),
        }

    def _result(self, variant, method, configuration, output):
        configuration_json = canonical_json(configuration)
        configuration_sha = hashlib.sha256(configuration_json.encode("utf-8")).hexdigest()
        output_json = canonical_json(output)
        provenance = {
            "method": method,
            "method_version": EXPERIMENT_METHOD_VERSION,
            "dataset_variant": variant.name,
            "input_fingerprint": variant.input_fingerprint,
            "configuration_sha256": configuration_sha,
            "boundary": json.loads(variant.boundary_provenance_json),
            "source_dataset_ids": list(variant.source_dataset_ids),
            "experimental_only": True,
        }
        provenance_json = canonical_json(provenance)
        result_fingerprint = hashlib.sha256(canonical_json({
            "provenance": provenance, "output": output
        }).encode("utf-8")).hexdigest()
        return ExperimentResult(
            species=variant.species, jurisdiction_id=variant.jurisdiction_id,
            source_dataset_ids=variant.source_dataset_ids, dataset_variant=variant.name,
            method=method, method_version=EXPERIMENT_METHOD_VERSION,
            configuration_json=configuration_json, configuration_sha256=configuration_sha,
            record_count=len(variant.source_occurrence_ids),
            unique_coordinate_count=len({(point.latitude, point.longitude) for point in variant.points}),
            grouped_event_count=len(variant.points), output_json=output_json,
            provenance_json=provenance_json, input_fingerprint=variant.input_fingerprint,
            result_fingerprint=result_fingerprint,
            limitations=(
                "Experimental descriptive artifact; not a production baseline.",
                "No output is an anomaly threshold or biological range.",
                "Occurrence sampling effort and absence remain unmodelled.",
                "Concave/alpha hull is deferred pending explicit parameter study.",
            ),
        )


__all__ = [
    "GeographicBaselineExperiment", "ExperimentVariant", "ExperimentPoint",
    "ExperimentResult", "EXPERIMENT_METHOD_VERSION",
]
