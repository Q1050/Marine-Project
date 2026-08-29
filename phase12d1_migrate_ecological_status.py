"""Additive/idempotent Phase 12D-1 ecological-status governance migration."""
import argparse,sqlite3
from sqlalchemy import create_engine
from models import (EcologicalStatusAssertion,EcologicalStatusCandidate,
                    EcologicalStatusPreparation)

def _columns(connection,table):return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
def run_migration(connection):
 engine=create_engine("sqlite://",creator=lambda:connection)
 created=[]
 for model in (EcologicalStatusPreparation,EcologicalStatusCandidate,EcologicalStatusAssertion):
  if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(model.__tablename__,)).fetchone():model.__table__.create(engine);created.append(model.__tablename__)
 added=[];columns=_columns(connection,"species_jurisdiction_status")
 for name,kind in (("status_set_json","TEXT"),("projection_state","VARCHAR(32)"),("projection_fingerprint","VARCHAR(64)"),("source_assertion_ids_json","TEXT")):
  if name not in columns:connection.execute(f"ALTER TABLE species_jurisdiction_status ADD COLUMN {name} {kind}");added.append(name)
 connection.commit();return {"tables_created":created,"projection_columns_added":added}
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args()
 with sqlite3.connect(args.database) as connection:print(run_migration(connection))
if __name__=="__main__":main()
