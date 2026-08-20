import json

from database import Base, SessionLocal, engine
from habitat_suitability_v3_grid_service import HabitatSuitabilityV3GridService


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print(json.dumps(HabitatSuitabilityV3GridService().generate(db), indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
