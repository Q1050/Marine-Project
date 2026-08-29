"""Portable invariants required by the PostgreSQL pilot schema."""
from sqlalchemy import inspect,text
from database import engine
from models import JurisdictionBoundary,NextAreaSnapshotGeneration,OccurrenceCandidateRecord,ScientificDataset,Species

VERSION="015-postgresql-portability-v1"

def migrate(bind=engine):
    changes=[];dialect=bind.dialect.name
    for table in (JurisdictionBoundary.__table__,Species.__table__,NextAreaSnapshotGeneration.__table__):
        for index in table.indexes:
            before={item["name"] for item in inspect(bind).get_indexes(table.name)}
            index.create(bind=bind,checkfirst=True)
            if index.name not in before:changes.append(index.name)
    if dialect=="postgresql":
        with bind.begin() as connection:
            connection.execute(text("ALTER TABLE scientific_datasets ALTER COLUMN source_version TYPE VARCHAR(128)"))
            connection.execute(text("ALTER TABLE occurrence_candidate_records ALTER COLUMN review_status TYPE VARCHAR(32)"))
    return changes

if __name__=="__main__":print({"version":VERSION,"changes":migrate()})
