from sqlalchemy import inspect
from models import IdentificationMediaReviewEvent,IdentificationBenchmarkRun,OccurrenceAcquisitionBatch,OccurrenceAcquisitionBatchItem
VERSION="017-real-media-operations-v1";TABLES=(IdentificationMediaReviewEvent,IdentificationBenchmarkRun,OccurrenceAcquisitionBatch,OccurrenceAcquisitionBatchItem)
def migrate(bind):
 existing=set(inspect(bind).get_table_names());created=[]
 for model in TABLES:
  if model.__tablename__ not in existing:model.__table__.create(bind=bind,checkfirst=True);created.append(model.__tablename__)
 return {"tables_created":created}
