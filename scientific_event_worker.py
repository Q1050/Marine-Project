import argparse,time
from database import SessionLocal
from platform_config import settings
from production_operations import EventWorker

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--once",action="store_true");parser.add_argument("--poll-seconds",type=float,default=5);args=parser.parse_args()
    if not settings.event_worker_enabled:raise SystemExit("EVENT_WORKER_ENABLED is false; worker refused to start.")
    while True:
        with SessionLocal() as db:
            worker=EventWorker(db);worker.recover_abandoned();row=worker.process_one()
        if args.once:break
        if not row:time.sleep(args.poll_seconds)
if __name__=="__main__":main()
