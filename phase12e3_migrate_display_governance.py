"""Additive/idempotent public-display governance migration."""
import argparse,sqlite3
FIELDS=(("public_display_status","VARCHAR(24) NOT NULL DEFAULT 'NOT_APPROVED'"),("public_display_approval_reference","VARCHAR(256)"),("public_display_approved_by_user_id","INTEGER REFERENCES users(id)"),("public_display_approved_at","DATETIME"),("public_display_revoked_at","DATETIME"),("public_display_limitations_json","TEXT NOT NULL DEFAULT '[]'"))
def run_migration(connection):
 columns={row[1] for row in connection.execute("PRAGMA table_info(suitability_deployments)")};added=[]
 for name,definition in FIELDS:
  if name not in columns:connection.execute(f"ALTER TABLE suitability_deployments ADD COLUMN {name} {definition}");added.append(name)
 connection.commit();return {"columns_added":added}
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--database",default="marine_observations.db");args=parser.parse_args()
 with sqlite3.connect(args.database) as connection:print(run_migration(connection))
if __name__=="__main__":main()
