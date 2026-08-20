import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import SessionLocal
from environmental_feature_service import EnvironmentalFeatureService
from init_db import initialize_database
from models import (
    PredictionTrainingEnvironmentalFeature,
    PredictionTrainingOccurrence,
)
from prediction_training_occurrence_service import DEFAULT_SCIENTIFIC_NAME


FEATURE_FIELDS = (
    "sst", "salinity", "depth",
    "sst_source", "salinity_source", "depth_source",
    "sst_distance_km", "salinity_distance_km", "depth_distance_km",
    "sst_sampling_method", "salinity_sampling_method", "depth_sampling_method",
    "depth_quality_flag",
)


def enrich(scientific_name, force=False, workers=6, location_only=False):
    initialize_database()
    db = SessionLocal()
    # Short per-request timeouts keep this bulk, resumable job progressing
    # when one provider is degraded; unavailable measurements remain null.
    service = EnvironmentalFeatureService(timeout=3)
    if location_only:
        # This recovery mode is for completing rows when remote gridded
        # providers are degraded; exact ETOPO remains enabled and misses stay null.
        service.nearest_fallbacks_enabled = False
    try:
        occurrences = db.query(PredictionTrainingOccurrence).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name
        ).order_by(PredictionTrainingOccurrence.id).all()
        existing_ids = {
            value for (value,) in db.query(
                PredictionTrainingEnvironmentalFeature.prediction_training_occurrence_id
            ).all()
        }
        pending = [
            occurrence for occurrence in occurrences
            if force or occurrence.id not in existing_ids
        ]

        dated_sample = next(
            (occurrence for occurrence in pending if occurrence.event_date),
            None,
        )
        if dated_sample is not None and not location_only:
            try:
                health_value = service._get_sst(
                    round(dated_sample.latitude, 6),
                    round(dated_sample.longitude, 6),
                    dated_sample.event_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                if health_value is None:
                    service.daily_provider_enabled = False
                    print(
                        "Daily CoastWatch health check returned no usable value; "
                        "bulk daily sampling disabled for this run.",
                        flush=True,
                    )
            except Exception as error:
                service.daily_provider_enabled = False
                print(
                    "Daily CoastWatch health check failed; preserving SST as null "
                    f"and using independent fallbacks where available: {error}",
                    flush=True,
                )

        pending_values = [
            (
                occurrence.id,
                occurrence.latitude,
                occurrence.longitude,
                occurrence.event_date,
            )
            for occurrence in pending
        ]

        def lookup(occurrence):
            occurrence_id, latitude, longitude, event_date = occurrence
            try:
                return occurrence_id, event_date, service.get_features(
                    latitude,
                    longitude,
                    None if location_only else event_date,
                ), None
            except Exception as error:
                return occurrence_id, event_date, None, str(error)

        processed = 0
        failures = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(lookup, occurrence) for occurrence in pending_values]
            for future in as_completed(futures):
                occurrence_id, event_date, values, error = future.result()
                if error is not None:
                    failures += 1
                    continue
                values.pop("errors", None)
                feature = db.query(PredictionTrainingEnvironmentalFeature).filter(
                    PredictionTrainingEnvironmentalFeature
                    .prediction_training_occurrence_id == occurrence_id
                ).one_or_none()
                if feature is None:
                    feature = PredictionTrainingEnvironmentalFeature(
                        prediction_training_occurrence_id=occurrence_id
                    )
                    db.add(feature)
                for field in FEATURE_FIELDS:
                    setattr(feature, field, values.get(field))
                feature.feature_date = event_date
                processed += 1
                if processed % 25 == 0:
                    db.commit()
                    print(f"Processed {processed}/{len(pending)}", flush=True)
        db.commit()

        features = db.query(PredictionTrainingEnvironmentalFeature).join(
            PredictionTrainingOccurrence,
            PredictionTrainingOccurrence.id
            == PredictionTrainingEnvironmentalFeature.prediction_training_occurrence_id,
        ).filter(
            PredictionTrainingOccurrence.scientific_name == scientific_name
        ).all()
        sampling = {
            name: dict(Counter(
                getattr(feature, f"{name}_sampling_method") for feature in features
            ))
            for name in ("sst", "salinity", "depth")
        }
        return {
            "species": scientific_name,
            "historical_records": len(occurrences),
            "already_enriched": len(occurrences) - len(pending),
            "processed": processed,
            "failed": failures,
            "enriched_records": len(features),
            "sst_available": sum(feature.sst is not None for feature in features),
            "salinity_available": sum(feature.salinity is not None for feature in features),
            "depth_available": sum(feature.depth is not None for feature in features),
            "complete": sum(
                feature.sst is not None
                and feature.salinity is not None
                and feature.depth is not None
                for feature in features
            ),
            "sampling": sampling,
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--location-only",
        action="store_true",
        help=(
            "Retrieve location-based depth while leaving date-based SST and "
            "salinity null when their providers are unavailable."
        ),
    )
    args = parser.parse_args()
    summary = enrich(
        DEFAULT_SCIENTIFIC_NAME,
        args.force,
        args.workers,
        args.location_only,
    )
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
