# PostgreSQL support

PostgreSQL 17 with psycopg 3 is the preferred pilot, staging, and future production database. SQLite remains supported for development, disposable tests, lightweight demos, and rollback snapshots.

Configure only through `DATABASE_URL`:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://marine_app:SECRET@localhost:5432/marine_monitoring'
```

The application never returns or logs this URL. PostgreSQL uses `pool_pre_ping` with configurable pool size, overflow and timeout. SQLite alone receives foreign-key, busy-timeout and WAL pragmas.

## Windows development

Docker Compose is recommended:

```powershell
$env:POSTGRES_PASSWORD = '<local secret>'
docker compose up postgres
```

Alternatively install PostgreSQL 17 and its client tools natively, create a dedicated non-superuser/database, then set `DATABASE_URL`. Native installation is optional.

## Data compatibility

IDs, booleans, nulls, text-backed canonical JSON, hashes, and scientific timestamps are preserved. Existing timestamp columns remain `TIMESTAMP WITHOUT TIME ZONE`; all system timestamps are interpreted and written as UTC. Scientific occurrence/event dates are not timezone-shifted. A future timezone-type conversion requires a separate reviewed migration.

PostgreSQL enforces declared string lengths that SQLite did not. The portability audit widened `scientific_datasets.source_version` to 128 and `occurrence_candidate_records.review_status` to 32 to accommodate existing valid state.

Partial unique indexes preserve one active boundary, one active scientific assignment, one active/building next-area generation per program/version, and unique non-null Aphia identity.

Large model checkpoints, media, raw datasets and image corpora remain in governed artifact/object storage. PostgreSQL stores metadata, references, provenance and hashes only.
