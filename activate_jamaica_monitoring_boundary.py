from pathlib import Path

from database import SessionLocal
from init_db import initialize_database
from jurisdiction_boundary_ingestion import activate_jamaica_boundary, load_jamaica_geometry


SOURCE_PATH = Path(__file__).parent / "data" / "jurisdiction_boundaries" / "marine-regions-v12-jamaica-wfs-source.geojson"


def vertex_count(geometry):
    if geometry.geom_type == "Polygon":
        return len(geometry.exterior.coords) + sum(len(ring.coords) for ring in geometry.interiors)
    return sum(vertex_count(component) for component in geometry.geoms)


if __name__ == "__main__":
    initialize_database()
    geometry, _ = load_jamaica_geometry(SOURCE_PATH)
    with SessionLocal() as db:
        boundary, inserted, properties = activate_jamaica_boundary(db, SOURCE_PATH)
        print(f"Action: {'INSERTED' if inserted else 'UNCHANGED'}")
        print(f"Boundary ID: {boundary.id}")
        print(f"Source: {boundary.source}")
        print(f"Version: {boundary.source_version}")
        print(f"MRGID: {properties['mrgid']}")
        print(f"Geometry: {geometry.geom_type}")
        print(f"Bounds: {geometry.bounds}")
        print(f"Components: {len(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else 1}")
        print(f"Vertices: {vertex_count(geometry)}")
        print(f"Geometry SHA-256: {boundary.geometry_hash}")

