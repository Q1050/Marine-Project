import json

from database import SessionLocal
from habitat_suitability_v3_service import HabitatSuitabilityV3Service
from init_db import initialize_database


def main():
    initialize_database()
    db = SessionLocal()
    try:
        print(json.dumps(HabitatSuitabilityV3Service().train(db), indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
