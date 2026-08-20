import json
from pathlib import Path

from coastal_current_sensitivity_service import CoastalCurrentSensitivityService
from database import SessionLocal


def main():
    database = SessionLocal()
    try:
        report = CoastalCurrentSensitivityService().run_sensitivity(database)
    finally:
        database.close()
    output = Path("coastal_nearest_valid_sensitivity_glorys_v1.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
