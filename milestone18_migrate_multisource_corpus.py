"""Additive Milestone 18 corpus-planning schema."""
from sqlalchemy import inspect
from models import IdentificationCorpusPlan, IdentificationCorpusPlanTaxon

VERSION = "018-multisource-corpus-plan-v1"
TABLES = (IdentificationCorpusPlan, IdentificationCorpusPlanTaxon)

def migrate(bind):
    existing = set(inspect(bind).get_table_names())
    created = []
    for model in TABLES:
        if model.__tablename__ not in existing:
            model.__table__.create(bind=bind, checkfirst=True)
            created.append(model.__tablename__)
    return {"tables_created": created}
