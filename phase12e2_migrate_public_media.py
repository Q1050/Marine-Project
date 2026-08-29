"""Additive/idempotent Phase 12E-2 migration."""
import argparse,sqlite3
from sqlalchemy import create_engine
from models import GovernedPublicMedia
def run_migration(connection):
 engine=create_engine("sqlite://",creator=lambda:connection);created=[];added=[]
 if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(GovernedPublicMedia.__tablename__,)).fetchone():GovernedPublicMedia.__table__.create(engine);created.append(GovernedPublicMedia.__tablename__)
 columns={row[1] for row in connection.execute("PRAGMA table_info(observations)")}
 for name,ddl in (("reporter_suggested_taxon_id","INTEGER REFERENCES species(id)"),("reporter_suggested_scientific_name","VARCHAR(512)")):
  if name not in columns:connection.execute(f"ALTER TABLE observations ADD COLUMN {name} {ddl}");added.append(name)
 connection.commit();return {"tables_created":created,"columns_added":added}
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args()
 with sqlite3.connect(args.database) as connection:print(run_migration(connection))
if __name__=="__main__":main()
