from datetime import datetime, timezone
import hashlib

from models import HistoricalOccurrence
from regional_evidence_provider import (
    REQUEST_SIZE,
    RegionalEvidenceProvider,
)


DEFAULT_SCIENTIFIC_NAME = "Pterois volitans"

# Jamaica-focused prototype extent, including nearshore waters.
JAMAICA_GEOMETRY = (
    "POLYGON (("
    "-78.6 16.9, "
    "-78.6 18.7, "
    "-75.9 18.7, "
    "-75.9 16.9, "
    "-78.6 16.9"
    "))"
)


class HistoricalOccurrenceService:

    def __init__(self, provider=None):
        self.provider = (
            provider
            or RegionalEvidenceProvider()
        )

    @staticmethod
    def _clean_value(value):
        if value is None:
            return None

        if isinstance(value, float) and value != value:
            return None

        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_event_date(record):
        value = record.get("eventDate")

        if value:
            value = str(value).split("/", 1)[0]

            try:
                parsed = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )

                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(
                        timezone.utc
                    ).replace(tzinfo=None)

                return parsed
            except (TypeError, ValueError):
                pass

        try:
            year = int(record.get("year"))
            month = int(record.get("month") or 1)
            day = int(record.get("day") or 1)
            return datetime(year, month, day)
        except (TypeError, ValueError):
            return None

    def _deduplication_key(self, record):
        occurrence_id = self._clean_value(
            record.get("occurrenceID")
        )

        if occurrence_id:
            return f"occurrence:{occurrence_id}"

        raw_source_id = self._clean_value(
            record.get("id")
        )

        if raw_source_id:
            return f"obis:{raw_source_id}"

        fingerprint = "|".join([
            self._clean_value(
                record.get("scientificName")
            ) or "",
            str(record.get("decimalLatitude")),
            str(record.get("decimalLongitude")),
            self._clean_value(
                record.get("eventDate")
            ) or "",
            self._clean_value(
                record.get("datasetName")
            ) or "",
        ])
        return "fingerprint:" + hashlib.sha256(
            fingerprint.encode("utf-8")
        ).hexdigest()

    def _retrieve_occurrences(
        self,
        taxon_id,
        geometry,
    ):
        records = []
        offset = 0
        total = None

        while total is None or offset < total:
            page_total, page = (
                self.provider.query_occurrences(
                    taxon_id,
                    geometry,
                    size=REQUEST_SIZE,
                    offset=offset,
                )
            )
            total = int(page_total)

            if not page:
                break

            records.extend(page)
            offset += len(page)

        return total or 0, records

    def backfill(
        self,
        db,
        scientific_name=DEFAULT_SCIENTIFIC_NAME,
    ):
        taxon = self.provider.resolve_taxon(
            scientific_name
        )

        if taxon is None:
            raise ValueError(
                f"Could not resolve OBIS taxon: {scientific_name}"
            )

        taxon_id = self.provider.get_taxon_id(taxon)

        if taxon_id is None:
            raise ValueError(
                f"OBIS taxon has no usable ID: {scientific_name}"
            )

        retrieved_total, raw_records = (
            self._retrieve_occurrences(
                taxon_id,
                JAMAICA_GEOMETRY,
            )
        )
        clean_frame = self.provider.clean_occurrences(
            raw_records
        )
        clean_records = clean_frame.to_dict(
            orient="records"
        )

        normalized = {}

        for record in clean_records:
            key = self._deduplication_key(record)
            event_date = self._parse_event_date(record)
            normalized[key] = {
                "scientific_name": scientific_name,
                "taxon_id": int(taxon_id),
                "latitude": float(
                    record["decimalLatitude"]
                ),
                "longitude": float(
                    record["decimalLongitude"]
                ),
                "event_date": event_date,
                "basis_of_record": self._clean_value(
                    record.get("basisOfRecord")
                ),
                "dataset_name": self._clean_value(
                    record.get("datasetName")
                    or record.get("datasetTitle")
                ),
                "occurrence_id": self._clean_value(
                    record.get("occurrenceID")
                ),
                "raw_source_id": self._clean_value(
                    record.get("id")
                ),
                "source": "OBIS",
                "deduplication_key": key,
            }

        existing_keys = {
            key
            for (key,) in (
                db.query(
                    HistoricalOccurrence.deduplication_key
                )
                .filter(
                    HistoricalOccurrence.source == "OBIS"
                )
                .all()
            )
        }

        new_records = [
            HistoricalOccurrence(**values)
            for key, values in normalized.items()
            if key not in existing_keys
        ]

        db.add_all(new_records)
        db.commit()

        dates = sorted(
            values["event_date"]
            for values in normalized.values()
            if values["event_date"] is not None
        )

        return {
            "species": scientific_name,
            "taxon_id": int(taxon_id),
            "obis_records_retrieved": retrieved_total,
            "clean_records": len(normalized),
            "new_records_inserted": len(new_records),
            "duplicates_skipped": (
                len(normalized) - len(new_records)
            ),
            "records_with_dates": len(dates),
            "earliest_date": (
                dates[0].isoformat()
                if dates else None
            ),
            "latest_date": (
                dates[-1].isoformat()
                if dates else None
            ),
        }
