import argparse

from database import SessionLocal
from environmental_feature_service import (
    DEPTH_SOURCE,
    SALINITY_CLIMATOLOGY_SOURCE,
    SALINITY_SOURCE,
    SST_SOURCE,
    EnvironmentalFeatureService,
)
from historical_occurrence_service import (
    DEFAULT_SCIENTIFIC_NAME,
)
from init_db import initialize_database
from models import (
    HistoricalEnvironmentalFeature,
    HistoricalOccurrence,
)


def enrich(scientific_name, force=False):
    initialize_database()
    db = SessionLocal()
    feature_service = EnvironmentalFeatureService()

    summary = {
        "species": scientific_name,
        "historical_records": 0,
        "already_enriched": 0,
        "processed": 0,
        "sst_available": 0,
        "salinity_available": 0,
        "depth_available": 0,
        "incomplete": 0,
        "failed": 0,
        "sst_failures": 0,
        "salinity_failures": 0,
        "depth_failures": 0,
    }

    try:
        occurrences = (
            db.query(HistoricalOccurrence)
            .filter(
                HistoricalOccurrence.scientific_name
                == scientific_name
            )
            .order_by(HistoricalOccurrence.id)
            .all()
        )
        summary["historical_records"] = len(occurrences)
        occurrence_ids = [
            occurrence.id for occurrence in occurrences
        ]
        existing = {
            feature.historical_occurrence_id: feature
            for feature in (
                db.query(HistoricalEnvironmentalFeature)
                .filter(
                    HistoricalEnvironmentalFeature
                    .historical_occurrence_id.in_(
                        occurrence_ids
                    )
                )
                .all()
                if occurrence_ids else []
            )
        }

        for occurrence in occurrences:
            feature = existing.get(occurrence.id)

            if feature is not None and not force:
                summary["already_enriched"] += 1
                continue

            try:
                values = feature_service.get_features(
                    occurrence.latitude,
                    occurrence.longitude,
                    occurrence.event_date,
                )
                errors = values.pop("errors", {})

                if feature is None:
                    feature = HistoricalEnvironmentalFeature(
                        historical_occurrence_id=occurrence.id
                    )
                    db.add(feature)

                for field, value in values.items():
                    setattr(feature, field, value)

                feature.feature_date = occurrence.event_date
                db.commit()
                summary["processed"] += 1

                available_fields = 0

                for field in ("sst", "salinity", "depth"):
                    if values[field] is not None:
                        summary[f"{field}_available"] += 1
                        available_fields += 1

                    if field in errors:
                        summary[f"{field}_failures"] += 1

                if available_fields < 3:
                    summary["incomplete"] += 1

                if errors:
                    summary["failed"] += 1
            except Exception:
                db.rollback()
                summary["failed"] += 1

        persisted_features = (
            db.query(
                HistoricalEnvironmentalFeature,
                HistoricalOccurrence,
            )
            .join(
                HistoricalOccurrence,
                HistoricalOccurrence.id
                == HistoricalEnvironmentalFeature
                .historical_occurrence_id,
            )
            .filter(
                HistoricalOccurrence.scientific_name
                == scientific_name
            )
            .all()
        )
        summary["sst_available"] = sum(
            feature.sst is not None
            for feature, _ in persisted_features
        )
        summary["salinity_available"] = sum(
            feature.salinity is not None
            for feature, _ in persisted_features
        )
        summary["depth_available"] = sum(
            feature.depth is not None
            for feature, _ in persisted_features
        )
        summary["incomplete"] = sum(
            any(value is None for value in (
                feature.sst,
                feature.salinity,
                feature.depth,
            ))
            for feature, _ in persisted_features
        )
        summary["sampling"] = {
            feature_name: {
                method.lower(): sum(
                    getattr(
                        feature,
                        f"{feature_name}_sampling_method",
                    ) == method
                    for feature, _ in persisted_features
                )
                for method in (
                    "EXACT",
                    "NEAREST_VALID",
                    "MISSING",
                )
            }
            for feature_name in (
                "sst",
                "salinity",
                "depth",
            )
        }
        summary["deepest_records"] = [
            {
                "historical_occurrence_id": occurrence.id,
                "latitude": occurrence.latitude,
                "longitude": occurrence.longitude,
                "event_date": occurrence.event_date,
                "depth": feature.depth,
                "sampling_method": (
                    feature.depth_sampling_method
                ),
                "sampling_distance_km": (
                    feature.depth_distance_km
                ),
                "quality_flag": feature.depth_quality_flag,
            }
            for feature, occurrence in sorted(
                (
                    item for item in persisted_features
                    if item[0].depth is not None
                ),
                key=lambda item: item[0].depth,
                reverse=True,
            )[:10]
        ]
    finally:
        db.close()

    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh features that are already persisted.",
    )
    args = parser.parse_args()
    summary = enrich(
        DEFAULT_SCIENTIFIC_NAME,
        force=args.force,
    )

    print(f"Species: {summary['species']}")
    print(
        "Historical records: "
        f"{summary['historical_records']}"
    )
    print(
        "Already enriched: "
        f"{summary['already_enriched']}"
    )
    print(f"Processed: {summary['processed']}")
    print(f"SST available: {summary['sst_available']}")
    print(
        "Salinity available: "
        f"{summary['salinity_available']}"
    )
    print(f"Depth available: {summary['depth_available']}")
    print(f"Incomplete: {summary['incomplete']}")
    print(f"Failed: {summary['failed']}")
    print(f"SST lookup failures: {summary['sst_failures']}")
    print(
        "Salinity lookup failures: "
        f"{summary['salinity_failures']}"
    )
    print(
        "Depth lookup failures: "
        f"{summary['depth_failures']}"
    )
    print(f"SST source: {SST_SOURCE}")
    print(f"Salinity source: {SALINITY_SOURCE}")
    print(
        "Salinity fallback source: "
        f"{SALINITY_CLIMATOLOGY_SOURCE}"
    )
    print(f"Depth source: {DEPTH_SOURCE}")

    for feature_name in ("sst", "salinity", "depth"):
        counts = summary["sampling"][feature_name]
        print(f"{feature_name.upper()} sampling:")
        print(f"  Exact: {counts['exact']}")
        print(
            "  Nearest-valid: "
            f"{counts['nearest_valid']}"
        )
        print(f"  Missing: {counts['missing']}")

    print("Deepest 10 historical occurrence points:")

    for record in summary["deepest_records"]:
        print(
            f"  {record['historical_occurrence_id']} | "
            f"{record['latitude']}, {record['longitude']} | "
            f"{record['event_date']} | "
            f"{record['depth']} m | "
            f"{record['sampling_method']} | "
            f"{record['sampling_distance_km']} km | "
            f"{record['quality_flag']}"
        )


if __name__ == "__main__":
    main()
