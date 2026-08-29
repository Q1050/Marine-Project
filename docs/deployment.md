# Controlled pilot deployment

## Prerequisites and environment

Use Python 3.12+, Node 22+, PostgreSQL 17, or Docker Compose. Copy `.env.example` to `.env`; set `APP_ENV=PILOT`, a strong `AUTH_SECRET`, a `postgresql+psycopg` `DATABASE_URL`, HTTPS frontend/backend origins, and persistent upload/artifact/backup paths. Never commit `.env`. Production-like startup refuses missing secrets, missing origins, localhost origins, or contradictory automation gates.

Install `requirements-pilot.txt` plus the appropriate CPU/GPU PyTorch build. Build the frontend with `VITE_API_BASE_URL`. The recurring scientific/model artifacts must exist under the configured persistent artifact path.

## Initialize and upgrade

Run `python migration_manager.py` before starting the API. It initializes required schema and records deterministic migration versions. Run it again to confirm `applied: []`. A fresh install creates schema and the legacy system bootstrap geography described in `init_db.py`; it does not create observations, governed assertions, anomaly configurations, reviewers, or thresholds.

For an upgrade: stop writes, run `python backup_database.py`, copy the database, run migrations twice on the copy, validate, then run once against the live database. Never skip a failed migration.

## Start

Backend: `uvicorn api:app --host 0.0.0.0 --port 8000 --proxy-headers`.

Frontend: `npm ci && npm run build`; serve `dist/` through HTTPS. Worker: explicitly set `EVENT_WORKER_ENABLED=true`, then `python scientific_event_worker.py`. This does not enable scientific evaluation: the global and reviewed configuration gates must independently permit it.

Docker: set `POSTGRES_PASSWORD`, then run `docker compose up --build`. The worker is an explicit profile: `docker compose --profile worker up`. Keep `postgres_data` and `pilot_data` backed up; rebuilding containers does not replace either volume.

## Health, backup, restore, rollback

Use `/health/live` for process liveness and `/health/ready` for database, migration, controlled storage, and configuration readiness. Admin status is `/admin/system/status`.

Create a backup with `python backup_database.py`. PostgreSQL uses `pg_dump` custom format; the runtime image includes PostgreSQL client tools. Restore PostgreSQL only into a new empty database with `python postgres_restore.py BACKUP --target $env:TARGET_DATABASE_URL --sha256 HASH --confirm`. SQLite restore retains its existing script. Rerun migrations and health checks afterward.

Rollback application containers/code first. Restore data only when a migration/data failure requires it; do not use restore as ordinary deployment rollback.

## Persistent storage and proxy

Persist PostgreSQL data, private uploads, scientific/provider artifacts, and backups independently of container filesystems. Terminate TLS at a trusted reverse proxy, preserve `X-Request-ID`, and forward scheme/host safely. PostgreSQL is now the authoritative pilot backend. SQLite remains supported for lightweight local development and tests; the final production SQLite snapshot is immutable rollback evidence and is not an application or dual-write target.

For the local controlled pilot, PostgreSQL data resides in the named Docker
volume `marine_pilot_postgres_data`. The API obtains `DATABASE_URL`, auth
secret, and approved CORS origin from operator environment configuration; no
database password is committed. Start PostgreSQL before the API, require
`pg_isready`, then verify `/health/live` and `/health/ready`. The scientific
event worker remains off unless its independent governed enablement is
explicitly approved.

Troubleshooting is in `failure-recovery.md`.
