"""Explicit PostgreSQL restore into a new, empty database."""
import argparse,hashlib,os,subprocess
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url

def restore(backup:Path,target_url:str,expected_sha256:str):
    if make_url(target_url).get_backend_name()!="postgresql":raise ValueError("Target must be PostgreSQL")
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=expected_sha256:raise ValueError("Backup SHA-256 mismatch; restore refused")
    engine=create_engine(target_url)
    if inspect(engine).get_table_names():raise ValueError("Restore target must be a new empty database")
    url=make_url(target_url);env=os.environ.copy()
    if url.password:env["PGPASSWORD"]=url.password
    command=["pg_restore","--host",url.host or "localhost","--port",str(url.port or 5432),"--username",url.username or "postgres","--dbname",url.database,"--no-owner","--no-privileges",str(backup)]
    try:subprocess.run(command,env=env,check=True,capture_output=True,text=True,timeout=1800)
    except (OSError,subprocess.SubprocessError) as exc:raise RuntimeError(f"PostgreSQL restore failed: {type(exc).__name__}") from None
    with engine.connect() as c:c.execute(text("SELECT 1"))
    return {"status":"RESTORED","target_backend":"postgresql","backup_sha256":expected_sha256}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("backup",type=Path);p.add_argument("--target",required=True);p.add_argument("--sha256",required=True);p.add_argument("--confirm",action="store_true");a=p.parse_args()
    if not a.confirm:raise SystemExit("Restore requires --confirm and an empty target database.")
    print(restore(a.backup,a.target,a.sha256))
