"""Additive/idempotent visual-corpus schema migration."""
from sqlalchemy import inspect
from models import (IdentificationCorpus, IdentificationCorpusInclusion,
    IdentificationMediaAcquisitionRun, IdentificationMediaAsset, IdentificationMediaSource)

VERSION="016-governed-visual-corpus-v1"
TABLES=(IdentificationMediaSource,IdentificationCorpus,IdentificationMediaAsset,IdentificationCorpusInclusion,IdentificationMediaAcquisitionRun)

def migrate(bind):
 existing=set(inspect(bind).get_table_names());created=[]
 for model in TABLES:
  if model.__tablename__ not in existing:
   model.__table__.create(bind=bind,checkfirst=True);created.append(model.__tablename__)
 return {"tables_created":created}
