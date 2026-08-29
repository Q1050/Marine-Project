import argparse
from pathlib import Path
from production_operations import restore_backup
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("backup",type=Path);p.add_argument("--target",type=Path,required=True);p.add_argument("--sha256",required=True);p.add_argument("--confirm",action="store_true");a=p.parse_args()
    if not a.confirm:raise SystemExit("Restore requires --confirm after writes are stopped.")
    print(restore_backup(a.backup,a.target,a.sha256))
