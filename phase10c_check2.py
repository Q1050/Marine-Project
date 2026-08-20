import json, sqlite3
conn = sqlite3.connect('marine_observations.db')
state = json.loads(conn.execute('SELECT evidence_state_json FROM next_area_snapshot_generations WHERE id = 2').fetchone()[0])
print('evidence_state_json length:', len(state))
print('observation IDs in baseline:', sorted([item['id'] for item in state]))
print()
print('Current observations with Pterois volitans:')
for r in conn.execute('SELECT id, species, verified_species, identification_status, verification_status, created_at, verified_at FROM observations WHERE species = :s OR verified_species = :s', {'s': 'Pterois volitans'}).fetchall():
    print(' ', r)
print()
print('Baseline keys per record:')
for k in state[0].keys():
    print(' ', k)