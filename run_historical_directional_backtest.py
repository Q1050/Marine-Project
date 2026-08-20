import json
from pathlib import Path

from database import SessionLocal
from historical_directional_backtest_service import HistoricalDirectionalBacktestService


def main():
    database = SessionLocal()
    try:
        result = HistoricalDirectionalBacktestService().run(database)
    finally:
        database.close()
    output = Path("directional_connectivity_backtest_glorys_v1.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
