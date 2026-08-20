import json

from database import SessionLocal
from environmental_feature_expansion_service import EnvironmentalFeatureExpansionService
from init_db import initialize_database


def main():
    initialize_database()
    db = SessionLocal()
    try:
        result = EnvironmentalFeatureExpansionService().enrich(db)
        print(json.dumps(result, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
