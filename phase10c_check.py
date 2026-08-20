import sqlite3
conn = sqlite3.connect('marine_observations.db')
print('Snapshot generations:')
for r in conn.execute("SELECT id, status, is_active, scientific_name, prediction_version, generated_at, evidence_state_json IS NULL as evidence_state_null, evidence_state_json FROM next_area_snapshot_generations ORDER BY id").fetchall():
    print(' ', r)
print()
print('Sample Observation rows (json-like fields):')
for r in conn.execute("SELECT id, species, verified_species, identification_status, verification_status, decision, priority, created_at, verified_at, is_possible_duplicate, duplicate_of_observation_id FROM observations ORDER BY id LIMIT 5").fetchall():
    print(' ', r)
print()
print('Historical occurrences sample first 3:')
for r in conn.execute("SELECT id, scientific_name, taxon_id, source, imported_at, dataset_id, deduplication_key FROM historical_occurrences ORDER BY id LIMIT 3").fetchall():
    print(' ', r)
print()
print('Archived database init time:')
import datetime
for r in conn.execute("SELECT id, slug, created_at, updated_at FROM scientific_datasets ORDER BY id").fetchall():
    print(' ', r[:3], '|', r[3])
print()
print('Hash of HistoricalOccurrence row representations matches for Phase 10C link?')
import hashlib
for r in conn.execute("SELECT id, scientific_name, latitude, longitude, source, dataset_name, imported_at, dataset_id FROM historical_occurrences ORDER BY id LIMIT 5").fetchall():
    hasher = hashlib.sha256()
    for v in r:
        hasher.update(str(v).encode())
    print(' ', r[0], 'hash:', hasher.hexdigest()[:16])