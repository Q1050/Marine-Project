"""Acquire the controlled Phase 11C-8 ECOREEF validation artifact."""

import argparse
import json

from database import SessionLocal
from ecoreef_validation_acquisition import acquire_records, write_artifact
from models import Jurisdiction, JurisdictionBoundary


def main(args):
    db = SessionLocal()
    try:
        jurisdiction = db.query(Jurisdiction).filter_by(slug=args.jurisdiction_slug).one()
        boundary = db.query(JurisdictionBoundary).filter_by(
            jurisdiction_id=jurisdiction.id, status="ACTIVE"
        ).one()
        artifact = acquire_records(
            session=db, target_species=args.species, jurisdiction=jurisdiction,
            boundary=boundary,
        )
        path, file_sha = write_artifact(artifact, args.output)
        return {
            "artifact_path": str(path), "artifact_file_sha256": file_sha,
            "content_fingerprint": artifact.content_fingerprint,
            "source_record_count": artifact.source_record_count,
            "survey_event_count": artifact.survey_event_count,
            "unique_spatial_location_count": artifact.unique_spatial_location_count,
            "independence_status": artifact.independence_status,
            "role": artifact.role,
        }
    finally:
        db.close()


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--species", default="Pterois volitans")
    result.add_argument("--jurisdiction-slug", default="jamaica")
    result.add_argument("--output", default=(
        "artifacts/experimental_validation/"
        "ecoreef-pterois-volitans-jamaica-2026-08-21.json"
    ))
    return result


if __name__ == "__main__":
    print(json.dumps(main(parser().parse_args()), indent=2, sort_keys=True))
