"""Additive Milestone 19 media taxonomy-evidence history."""
from sqlalchemy import inspect
from models import IdentificationMediaTaxonomyEvidence, IdentificationMediaTaxonomyResolution

VERSION = "020-media-taxonomy-resolution-v1"
TABLES = (IdentificationMediaTaxonomyEvidence, IdentificationMediaTaxonomyResolution)


def migrate(bind):
    existing = set(inspect(bind).get_table_names())
    created = []
    for model in TABLES:
        if model.__tablename__ not in existing:
            model.__table__.create(bind=bind, checkfirst=True)
            created.append(model.__tablename__)
    return {"tables_created": created}
