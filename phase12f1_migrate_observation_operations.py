"""Additive/idempotent operational observation workflow migration."""
import argparse,sqlite3
from sqlalchemy import create_engine
from models import ObservationOperationalCase,ObservationOperationalEvent
def run_migration(connection):
 engine=create_engine("sqlite://",creator=lambda:connection);created=[]
 for model in (ObservationOperationalCase,ObservationOperationalEvent):
  if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(model.__tablename__,)).fetchone():model.__table__.create(engine);created.append(model.__tablename__)
 connection.commit();return {"tables_created":created}
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args()
 with sqlite3.connect(args.database) as connection:print(run_migration(connection))
if __name__=="__main__":main()
