import json

from shapely.geometry import Point, shape

from models import Jurisdiction, JurisdictionBoundary, Region


class JurisdictionResolutionService:
    """Database-portable resolver; the service boundary can later use PostGIS."""

    @staticmethod
    def validate_coordinates(latitude, longitude):
        if not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90.")
        if not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180.")

    def resolve(self, db, latitude, longitude):
        self.validate_coordinates(latitude, longitude)
        point = Point(longitude, latitude)
        boundaries = (
            db.query(JurisdictionBoundary)
            .join(Jurisdiction)
            .join(Region)
            .filter(
                JurisdictionBoundary.status == "ACTIVE",
                JurisdictionBoundary.boundary_type == "MARINE_MONITORING",
                Jurisdiction.status == "ACTIVE",
                Region.status == "ACTIVE",
            )
            .all()
        )
        matches = []
        for boundary in boundaries:
            geometry = shape(json.loads(boundary.geometry_json))
            if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                continue
            if geometry.covers(point):
                matches.append(boundary)

        if not matches:
            return {"status": "NO_CONFIGURED_JURISDICTION", "region": None, "jurisdiction": None, "boundary": None, "resolution_method": "BOUNDARY_COVERS"}

        jurisdiction_ids = {item.jurisdiction_id for item in matches}
        if len(jurisdiction_ids) > 1:
            return {
                "status": "AMBIGUOUS",
                "region": None,
                "jurisdiction": None,
                "boundary": None,
                "resolution_method": "BOUNDARY_COVERS",
                "candidates": [self._match_payload(item) for item in matches],
            }

        boundary = matches[0]
        payload = self._match_payload(boundary)
        return {
            "status": "RESOLVED",
            "region": payload["region"],
            "jurisdiction": payload["jurisdiction"],
            "boundary": payload["boundary"],
            "resolution_method": "BOUNDARY_COVERS",
            "jurisdiction_id": boundary.jurisdiction_id,
        }

    @staticmethod
    def _match_payload(boundary):
        jurisdiction = boundary.jurisdiction
        return {
            "region": {"id": jurisdiction.region.id, "name": jurisdiction.region.name, "slug": jurisdiction.region.slug},
            "jurisdiction": {"id": jurisdiction.id, "name": jurisdiction.name, "slug": jurisdiction.slug, "country_code": jurisdiction.country_code},
            "boundary": {
                "id": boundary.id,
                "boundary_type": boundary.boundary_type,
                "source": boundary.source,
                "source_version": boundary.source_version,
                "source_reference": boundary.source_reference,
            },
        }
