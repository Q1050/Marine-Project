from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from cache_glorys_historical_currents import DATES, REQUESTED_DEPTH_M
from database import SessionLocal
from geographic_utils import haversine_km
from models import HistoricalOccurrence, HabitatSuitabilityV3GridCell, PredictionTrainingOccurrence
from next_area_backtest_service import NextAreaBacktestService
from ocean_current_service import OceanCurrentLookupService, sha256_file


def nearest_valid_distance(metadata, latitude, longitude):
    with netcdf_file(metadata["cache_file"], "r", mmap=False) as dataset:
        latitudes = dataset.variables["latitude"].data.copy()
        longitudes = dataset.variables["longitude"].data.copy()
        u = dataset.variables["u"].data.copy()
        v = dataset.variables["v"].data.copy()
    valid = np.isfinite(u) & np.isfinite(v)
    return min(
        haversine_km(latitude, longitude, float(latitudes[i]), float(longitudes[j]))
        for i, j in zip(*np.where(valid))
    )


def main():
    cache_root = Path("current_data/copernicus/glorys12v1/daily")
    metadata = {}
    validation = []
    for path in sorted(cache_root.rglob("*.nc.metadata.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        cache_file = Path(item["cache_file"])
        valid_checksum = cache_file.exists() and sha256_file(cache_file) == item["checksum"]
        metadata[item["represented_date"]] = item
        validation.append({
            "date": item["represented_date"], "checksum_valid": valid_checksum,
            "temporal_representation": item["temporal_representation"],
            "depth_m": item["source_depth_m"], "grid_shape": item["grid_shape"],
            "valid_vectors": item["valid_ocean_cells"],
            "masked_vectors": item["masked_or_missing_cells"],
            "latitude_resolution_degrees": item["latitude_resolution_degrees"],
            "longitude_resolution_degrees": item["longitude_resolution_degrees"],
            "actual_extent": item["actual_returned_extent"],
            "units": {"u": item["u_units"], "v": item["v_units"]},
        })

    database = SessionLocal()
    service = NextAreaBacktestService()
    lookup = OceanCurrentLookupService()
    try:
        historical = database.query(HistoricalOccurrence).filter(
            HistoricalOccurrence.scientific_name == "Pterois volitans",
            HistoricalOccurrence.event_date.is_not(None),
        ).order_by(HistoricalOccurrence.event_date, HistoricalOccurrence.id).all()
        rows = database.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == "Pterois volitans",
            PredictionTrainingOccurrence.event_date.is_not(None),
        ).order_by(PredictionTrainingOccurrence.event_date, PredictionTrainingOccurrence.id).all()
        clean = service._deduplicate(rows)
        grid = database.query(HabitatSuitabilityV3GridCell).filter(
            HabitatSuitabilityV3GridCell.scientific_name == "Pterois volitans",
            HabitatSuitabilityV3GridCell.model_version == "pterois-volitans-suitability-v3",
            HabitatSuitabilityV3GridCell.prediction_status == "SCORED",
        ).all()
        grid_ids = {cell.grid_cell_id for cell in grid}
        domain = [row for row in clean if service.grid_cell_id(row.latitude, row.longitude) in grid_ids]

        def current_status(row):
            return lookup.get_current(
                row.latitude, row.longitude, service._aware(row.event_date),
                REQUESTED_DEPTH_M, provider="COPERNICUS_MARINE",
            )

        historical_results = [(row, current_status(row)) for row in historical]
        domain_results = [(row, current_status(row)) for row in domain]

        masked = defaultdict(list)
        for row, current in domain_results:
            if current["status"] == "MISSING_PROVIDER_VALUE":
                masked[service.grid_cell_id(row.latitude, row.longitude)].append(row)
        masked_report = []
        for cell, affected in sorted(masked.items()):
            distances = []
            for row in affected:
                item = metadata[row.event_date.date().isoformat()]
                distances.append(nearest_valid_distance(item, row.latitude, row.longitude))
            masked_report.append({
                "grid_cell_id": cell, "records": len(affected),
                "dates": sorted({row.event_date.date().isoformat() for row in affected}),
                "coordinates": sorted({(row.latitude, row.longitude) for row in affected}),
                "nearest_valid_distance_km": {
                    "minimum": min(distances), "median": float(np.median(distances)), "maximum": max(distances),
                },
            })

        windows = []
        minimum_year = min(row.event_date.year for row in domain)
        maximum_year = max(row.event_date.year for row in domain)
        for cutoff_year in range(minimum_year, maximum_year):
            cutoff = datetime(cutoff_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            evaluation_end = datetime(min(cutoff_year + 2, maximum_year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            sources, future, occupied, future_cells, future_new = service.partition_window(domain, cutoff, evaluation_end)
            if not sources or len(future) < 2 or not future_new:
                continue
            source_results = [(row, current_status(row)) for row in sources]
            valid = [row for row, current in source_results if current["status"] == "VALID"]
            cell_counts = Counter(service.grid_cell_id(row.latitude, row.longitude) for row in sources)
            windows.append({
                "cutoff": cutoff.date().isoformat(),
                "evaluation_start": f"{cutoff_year + 1}-01-01",
                "evaluation_end": evaluation_end.date().isoformat(),
                "source_records": len(sources),
                "unique_source_dates": len({row.event_date.date() for row in sources}),
                "unique_source_cells": len(cell_counts),
                "maximum_records_from_one_source_cell": max(cell_counts.values()),
                "sources_with_cached_dates": sum(row.event_date.date().isoformat() in metadata for row in sources),
                "sources_with_valid_direct_currents": len(valid),
                "valid_source_dates": len({row.event_date.date() for row in valid}),
                "valid_source_cells": len({service.grid_cell_id(row.latitude, row.longitude) for row in valid}),
                "future_records": len(future),
                "future_occupied_cells": len(future_cells),
                "future_new_cells": len(future_new),
                "future_new_cell_ids": sorted(future_new),
            })

        report = {
            "provider": "COPERNICUS_MARINE",
            "dataset_id": "cmems_mod_glo_phy_my_0.083deg_P1D-m",
            "depth_m": REQUESTED_DEPTH_M,
            "temporal_representation": "DAILY_MEAN",
            "cache": {
                "partitions": len(metadata), "dates": sorted(metadata),
                "netcdf_bytes": sum(Path(item["cache_file"]).stat().st_size for item in metadata.values()),
                "total_bytes_with_metadata": sum(
                    Path(item["cache_file"]).stat().st_size
                    + Path(item["cache_file"] + ".metadata.json").stat().st_size
                    for item in metadata.values()
                ),
                "validation": validation,
            },
            "historical_occurrence_baseline": {
                "records": len(historical),
                "unique_dates": len({row.event_date.date() for row in historical}),
                "occupied_cells": len({service.grid_cell_id(row.latitude, row.longitude) for row in historical}),
                "records_with_cached_dates": sum(row.event_date.date().isoformat() in metadata for row in historical),
                "records_with_valid_direct_currents": sum(current["status"] == "VALID" for _, current in historical_results),
                "records_masked": sum(current["status"] == "MISSING_PROVIDER_VALUE" for _, current in historical_results),
                "records_without_cached_dates": sum(current["status"] == "NOT_CACHED" for _, current in historical_results),
                "unique_dates_with_valid_currents": len({row.event_date.date() for row, current in historical_results if current["status"] == "VALID"}),
                "unique_cells_with_valid_currents": len({service.grid_cell_id(row.latitude, row.longitude) for row, current in historical_results if current["status"] == "VALID"}),
            },
            "evaluation_domain": {
                "records": len(domain), "unique_dates": len({row.event_date.date() for row in domain}),
                "occupied_cells": len({service.grid_cell_id(row.latitude, row.longitude) for row in domain}),
                "records_with_cached_dates": sum(row.event_date.date().isoformat() in metadata for row in domain),
                "records_with_valid_direct_currents": sum(current["status"] == "VALID" for _, current in domain_results),
                "records_masked": sum(current["status"] == "MISSING_PROVIDER_VALUE" for _, current in domain_results),
                "unique_dates_with_valid_currents": len({row.event_date.date() for row, current in domain_results if current["status"] == "VALID"}),
                "unique_cells_with_valid_currents": len({service.grid_cell_id(row.latitude, row.longitude) for row, current in domain_results if current["status"] == "VALID"}),
            },
            "masked_source_cells": masked_report,
            "candidate_windows": windows,
        }
    finally:
        database.close()
    output = Path("expanded_glorys_coverage_audit.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
