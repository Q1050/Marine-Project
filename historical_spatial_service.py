from collections import defaultdict
from datetime import datetime, timezone, timedelta
from math import floor

from sqlalchemy import func

from geographic_utils import haversine_km
from models import HistoricalOccurrence


class HistoricalSpatialService:

    def __init__(self, grid_size=0.1):
        self.grid_size = grid_size

    def _grid_cell(self, latitude, longitude):
        latitude_cell = (
            floor(latitude / self.grid_size)
            * self.grid_size
        )
        longitude_cell = (
            floor(longitude / self.grid_size)
            * self.grid_size
        )

        return (
            round(latitude_cell, 4),
            round(longitude_cell, 4),
        )

    @staticmethod
    def classify_occurrence_concentration(
        total_records,
    ):
        if total_records == 0:
            return "NONE"

        if total_records == 1:
            return "SPARSE"

        if total_records <= 4:
            return "MODERATE"

        return "STRONG"

    @staticmethod
    def classify_historical_location_context(
        nearest_historical_record_km,
    ):
        if nearest_historical_record_km is None:
            return "NO_HISTORICAL_DATA"

        if nearest_historical_record_km <= 10:
            return "WITHIN_HISTORICAL_AREA"

        if nearest_historical_record_km <= 50:
            return "NEAR_HISTORICAL_AREA"

        return "OUTSIDE_HISTORICAL_AREA"

    @staticmethod
    def _species_query(db, scientific_name):
        return db.query(HistoricalOccurrence).filter(
            func.lower(
                HistoricalOccurrence.scientific_name
            ) == scientific_name.lower()
        )

    def aggregate(self, db, scientific_name):
        occurrences = self._species_query(
            db,
            scientific_name,
        ).all()
        now = datetime.now(timezone.utc).replace(
            tzinfo=None
        )
        cutoffs = {
            "records_past_1_year": (
                now - timedelta(days=365)
            ),
            "records_past_3_years": (
                now - timedelta(days=365 * 3)
            ),
            "records_past_5_years": (
                now - timedelta(days=365 * 5)
            ),
        }
        cells = defaultdict(
            lambda: {
                "total_records": 0,
                "locations": set(),
                "dates": [],
                "records_past_1_year": 0,
                "records_past_3_years": 0,
                "records_past_5_years": 0,
            }
        )

        for occurrence in occurrences:
            cell = self._grid_cell(
                occurrence.latitude,
                occurrence.longitude,
            )
            data = cells[cell]
            data["total_records"] += 1
            data["locations"].add((
                round(occurrence.latitude, 3),
                round(occurrence.longitude, 3),
            ))

            event_date = occurrence.event_date

            if event_date is None:
                continue

            if event_date.tzinfo is not None:
                event_date = event_date.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)

            data["dates"].append(event_date)

            for field, cutoff in cutoffs.items():
                if event_date >= cutoff:
                    data[field] += 1

        serialized_cells = []

        for (latitude, longitude), data in cells.items():
            dates = data["dates"]
            serialized_cells.append({
                "latitude": round(
                    latitude + self.grid_size / 2,
                    4,
                ),
                "longitude": round(
                    longitude + self.grid_size / 2,
                    4,
                ),
                "grid_size": self.grid_size,
                "total_records": data["total_records"],
                "unique_locations": len(
                    data["locations"]
                ),
                "earliest_record": (
                    min(dates).isoformat()
                    if dates else None
                ),
                "latest_record": (
                    max(dates).isoformat()
                    if dates else None
                ),
                "records_past_1_year": data[
                    "records_past_1_year"
                ],
                "records_past_3_years": data[
                    "records_past_3_years"
                ],
                "records_past_5_years": data[
                    "records_past_5_years"
                ],
                "occurrence_concentration": (
                    self.classify_occurrence_concentration(
                        data["total_records"]
                    )
                ),
            })

        serialized_cells.sort(
            key=lambda cell: cell["total_records"],
            reverse=True,
        )

        return {
            "species": scientific_name,
            "grid_size": self.grid_size,
            "total_records": len(occurrences),
            "cells": serialized_cells,
        }

    def get_location_context(
        self,
        db,
        scientific_name,
        latitude,
        longitude,
    ):
        if not -90 <= latitude <= 90:
            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        if not -180 <= longitude <= 180:
            raise ValueError(
                "Longitude must be between -180 and 180."
            )

        occurrences = self._species_query(
            db,
            scientific_name,
        ).all()

        if not occurrences:
            nearest_record_km = None
            nearest_cell_km = None
        else:
            nearest_record_km = min(
                haversine_km(
                    latitude,
                    longitude,
                    occurrence.latitude,
                    occurrence.longitude,
                )
                for occurrence in occurrences
            )
            cell_centers = {
                (
                    round(
                        cell_latitude
                        + self.grid_size / 2,
                        4,
                    ),
                    round(
                        cell_longitude
                        + self.grid_size / 2,
                        4,
                    ),
                )
                for cell_latitude, cell_longitude in (
                    self._grid_cell(
                        occurrence.latitude,
                        occurrence.longitude,
                    )
                    for occurrence in occurrences
                )
            }
            nearest_cell_km = min(
                haversine_km(
                    latitude,
                    longitude,
                    cell_latitude,
                    cell_longitude,
                )
                for cell_latitude, cell_longitude
                in cell_centers
            )

        return {
            "species": scientific_name,
            "latitude": latitude,
            "longitude": longitude,
            "nearest_historical_record_km": (
                round(nearest_record_km, 3)
                if nearest_record_km is not None
                else None
            ),
            "nearest_historical_cell_km": (
                round(nearest_cell_km, 3)
                if nearest_cell_km is not None
                else None
            ),
            "historical_location_context": (
                self.classify_historical_location_context(
                    nearest_record_km
                )
            ),
        }
