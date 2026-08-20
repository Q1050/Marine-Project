import sqlite3

conn = sqlite3.connect("marine_observations.db")

row = conn.execute(
    """
    SELECT acquisition_manifest_json
    FROM scientific_datasets
    WHERE slug = ?
    """,
    ("pterois-volitans-jamaica-obis-iNaturalist-2025-08",),
).fetchone()

print(row)
 