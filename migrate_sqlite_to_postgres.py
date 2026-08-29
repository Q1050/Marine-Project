import argparse,json
from pathlib import Path
from postgres_migration import migrate_sqlite_to_postgres

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--source",required=True);p.add_argument("--target",required=True);p.add_argument("--dry-run",action="store_true");p.add_argument("--manifest",type=Path);a=p.parse_args()
    try:print(json.dumps(migrate_sqlite_to_postgres(a.source,a.target,a.dry_run,a.manifest),indent=2,default=str))
    except Exception as exc:raise SystemExit(f"Migration failed: {type(exc).__name__}: {exc}") from None
