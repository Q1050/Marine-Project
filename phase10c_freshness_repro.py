import shutil, pathlib, sqlite3, json, os, sys
src = pathlib.Path('marine_observations.db')
test_path = pathlib.Path('phase5g_check_fresh.db')
if test_path.exists():
    test_path.unlink()
shutil.copy(src, test_path)

import init_db
import database

test_engine = __import__('sqlalchemy').create_engine(
    f'sqlite:///{test_path}',
    connect_args={'check_same_thread': False},
)
database.engine = test_engine
init_db.engine = test_engine

init_db.initialize_database()

conn = sqlite3.connect(test_path)
print('=== State of the isolated DB after migration ===')
print('historical_occurrences with dataset_id IS NOT NULL:',
      conn.execute('SELECT COUNT(*) FROM historical_occurrences WHERE dataset_id IS NOT NULL').fetchone())
print()
print('Snapshot generations:')
for r in conn.execute('SELECT id, status, is_active, evidence_state_json IS NULL FROM next_area_snapshot_generations ORDER BY id').fetchall():
    print(' ', r)
print()
print('Baseline for gen 2:')
state = json.loads(conn.execute('SELECT evidence_state_json FROM next_area_snapshot_generations WHERE id = 2').fetchone()[0])
print(' observation IDs:', sorted([item['id'] for item in state]))
print(' first record fields:', list(state[0].keys()))
print()
print('Current observations with Pterois volitans:')
for r in conn.execute("SELECT id, identification_status, verification_status, decision, priority, created_at, verified_at FROM observations WHERE species = 'Pterois volitans'").fetchall():
    print(' ', r)
conn.close()

# Now use the same path the test uses to call the freshness endpoint
sys.path.insert(0, '.')
import api
import species_jurisdiction_ecology
from next_area_prediction_service import NextAreaPredictionService
from database import SessionLocal

session = SessionLocal()
svc = NextAreaPredictionService()
result = svc.freshness(session, scientific_name='Pterois volitans', prediction_version='pterois-volitans-next-area-v1', jurisdiction_id=1)
session.close()
print()
print('Freshness call result:')
print(json.dumps(result, indent=2, default=str))

# Extract details
print()
print('reasons:', result.get('reasons'))
print('relevant_changes_since_generation:', result.get('relevant_changes_since_generation'))