import json

from database import SessionLocal
from next_area_backtest_service import NextAreaBacktestService


def main():
    db = SessionLocal()
    try:
        print(json.dumps(NextAreaBacktestService().run(db), indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
