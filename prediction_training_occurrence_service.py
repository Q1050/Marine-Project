from collections import Counter
from datetime import datetime, timezone
import hashlib
from math import floor
from statistics import median

from models import PredictionTrainingOccurrence
from regional_evidence_provider import REQUEST_SIZE, RegionalEvidenceProvider


DEFAULT_SCIENTIFIC_NAME = "Pterois volitans"
TRAINING_REGION_NAME = "Caribbean"
GRID_SIZE = 0.1

# Prototype training extent: the Caribbean basin and connected nearshore waters.
# It is deliberately broader than Jamaica (-78.6..-75.9, 16.9..18.7), which
# remains the initial monitoring/deployment geography.
CARIBBEAN_GEOMETRY = (
    "POLYGON ((-89 9, -89 28, -59 28, -59 9, -89 9))"
)


class PredictionTrainingOccurrenceService:

    def __init__(self, provider=None):
        self.provider = provider or RegionalEvidenceProvider()

    @staticmethod
    def _clean_value(value):
        if value is None or (isinstance(value, float) and value != value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_event_date(record):
        value = record.get("eventDate")
        if value:
            value = str(value).split("/", 1)[0]
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                return parsed
            except (TypeError, ValueError):
                pass
        try:
            return datetime(
                int(record.get("year")),
                int(record.get("month") or 1),
                int(record.get("day") or 1),
            )
        except (TypeError, ValueError):
            return None

    def _deduplication_key(self, record):
        occurrence_id = self._clean_value(record.get("occurrenceID"))
        if occurrence_id:
            return f"occurrence:{occurrence_id}"
        raw_id = self._clean_value(record.get("id"))
        if raw_id:
            return f"obis:{raw_id}"
        fingerprint = "|".join(
            str(record.get(key) or "")
            for key in (
                "scientificName",
                "decimalLatitude",
                "decimalLongitude",
                "eventDate",
                "datasetName",
            )
        )
        return "fingerprint:" + hashlib.sha256(fingerprint.encode()).hexdigest()

    def _retrieve(self, taxon_id):
        records = []
        offset = 0
        total = None
        while total is None or offset < total:
            total, page = self.provider.query_occurrences(
                taxon_id,
                CARIBBEAN_GEOMETRY,
                size=REQUEST_SIZE,
                offset=offset,
            )
            total = int(total)
            if not page:
                break
            records.extend(page)
            offset += len(page)
        return total or 0, records

    @staticmethod
    def _grid_key(latitude, longitude):
        return (
            floor(latitude / GRID_SIZE) * GRID_SIZE,
            floor(longitude / GRID_SIZE) * GRID_SIZE,
        )

    def import_occurrences(self, db, scientific_name=DEFAULT_SCIENTIFIC_NAME):
        taxon = self.provider.resolve_taxon(scientific_name)
        taxon_id = self.provider.get_taxon_id(taxon) if taxon else None
        if taxon_id is None:
            raise ValueError(f"Could not resolve OBIS taxon: {scientific_name}")

        source_total, source_records = self._retrieve(taxon_id)
        clean_records = self.provider.clean_occurrences(source_records).to_dict(
            orient="records"
        )

        source_unique = {}
        for record in clean_records:
            key = self._deduplication_key(record)
            source_unique.setdefault(key, record)

        canonical = {}
        coordinate_date_seen = set()
        coordinate_date_duplicates = 0
        for key, record in source_unique.items():
            event_date = self._parse_event_date(record)
            latitude = float(record["decimalLatitude"])
            longitude = float(record["decimalLongitude"])
            if event_date is not None:
                coordinate_date_key = (
                    scientific_name.lower(),
                    round(latitude, 6),
                    round(longitude, 6),
                    event_date.isoformat(),
                )
                if coordinate_date_key in coordinate_date_seen:
                    coordinate_date_duplicates += 1
                    continue
                coordinate_date_seen.add(coordinate_date_key)

            canonical[key] = {
                "scientific_name": scientific_name,
                "taxon_id": int(taxon_id),
                "latitude": latitude,
                "longitude": longitude,
                "event_date": event_date,
                "occurrence_id": self._clean_value(record.get("occurrenceID")),
                "raw_source_id": self._clean_value(record.get("id")),
                "dataset_name": self._clean_value(
                    record.get("datasetName") or record.get("datasetTitle")
                ),
                "basis_of_record": self._clean_value(record.get("basisOfRecord")),
                "country_or_region": self._clean_value(
                    record.get("country")
                    or record.get("countryCode")
                    or record.get("waterBody")
                ),
                "source": "OBIS",
                "deduplication_key": key,
            }

        existing = {
            key for (key,) in db.query(PredictionTrainingOccurrence.deduplication_key)
            .filter(PredictionTrainingOccurrence.source == "OBIS")
            .all()
        }
        new_rows = [
            PredictionTrainingOccurrence(**values)
            for key, values in canonical.items()
            if key not in existing
        ]
        db.add_all(new_rows)
        db.commit()

        values = list(canonical.values())
        dates = sorted(v["event_date"] for v in values if v["event_date"])
        years = Counter(str(value.year) for value in dates)
        regions = Counter(v["country_or_region"] or "UNKNOWN" for v in values)
        coordinates = {(v["latitude"], v["longitude"]) for v in values}
        coordinate_dates = {
            (v["latitude"], v["longitude"], v["event_date"])
            for v in values
            if v["event_date"] is not None
        }
        grids = Counter(self._grid_key(v["latitude"], v["longitude"]) for v in values)
        strongest_key, strongest_count = grids.most_common(1)[0] if grids else (None, 0)

        return {
            "species": scientific_name,
            "training_region": TRAINING_REGION_NAME,
            "training_geometry": CARIBBEAN_GEOMETRY,
            "taxon_id": int(taxon_id),
            "total_source_records": source_total,
            "source_records_returned": len(source_records),
            "records_passing_obis_quality_filters": len(clean_records),
            "usable_records": len(values),
            "new_records_inserted": len(new_rows),
            "existing_records_skipped": len(values) - len(new_rows),
            "source_level_duplicates_removed": len(clean_records) - len(source_unique),
            "coordinate_date_duplicates_removed": coordinate_date_duplicates,
            "unique_occurrence_ids": len(
                {v["occurrence_id"] for v in values if v["occurrence_id"]}
            ),
            "unique_coordinates": len(coordinates),
            "unique_coordinate_date_combinations": len(coordinate_dates),
            "dated_records": len(dates),
            "date_range": {
                "earliest": dates[0].date().isoformat() if dates else None,
                "latest": dates[-1].date().isoformat() if dates else None,
            },
            "records_by_year": dict(sorted(years.items())),
            "records_by_country_or_region": dict(regions.most_common()),
            "occupied_grid_cells": len(grids),
            "strongest_cell": {
                "latitude": strongest_key[0] if strongest_key else None,
                "longitude": strongest_key[1] if strongest_key else None,
                "records": strongest_count,
            },
            "median_records_per_occupied_cell": median(grids.values()) if grids else 0,
        }
