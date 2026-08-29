from database import SessionLocal
from production_operations import create_backup
if __name__=="__main__":
    with SessionLocal() as db:print(create_backup(db))
