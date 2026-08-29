# SQLite to PostgreSQL migration

1. Stop writes and create a final consistent SQLite backup.
2. Hash and copy the SQLite file; never migrate from the actively written file.
3. Create an empty PostgreSQL database.
4. Dry-run:

```powershell
python migrate_sqlite_to_postgres.py --source 'sqlite:///backups/source-copy.db' --target $env:TARGET_DATABASE_URL --dry-run
```

5. Migrate and write a safe manifest:

```powershell
python migrate_sqlite_to_postgres.py --source 'sqlite:///backups/source-copy.db' --target $env:TARGET_DATABASE_URL --manifest 'backups/postgres-migration-manifest.json'
python migration_manager.py
python migration_manager.py
```

The tool requires a persistent SQLite source and `postgresql+psycopg` target, refuses any populated target, preserves primary keys/nulls/text JSON/timestamps/hashes, handles the governed occurrence candidate/evidence cycle explicitly, copies in FK dependency order, resets every PostgreSQL sequence, compares every table count and canonical row fingerprint, and checks validated foreign keys. Credentials are removed from the manifest.

The source copy used in the controlled rehearsal had SHA-256 `DB5694227F0DDED2C3FB3C1D80CC003552C5FD1AE1CD2E13950E890788287C8B`. All 77 tables matched. The extra PostgreSQL migration-ledger row for `015-postgresql-portability-v1` is an intentional infrastructure difference after running the current migration manager.

Private media and artifact files are not embedded in the database migration. Copy persistent upload/artifact storage separately while preserving relative references and hashes.
