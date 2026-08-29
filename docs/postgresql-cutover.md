# Controlled PostgreSQL pilot cutover

## Current pilot state

The controlled pilot cutover completed on 2026-08-28. PostgreSQL 17 is the
single authoritative application database. The final SQLite snapshot is
read-only rollback evidence and must not receive application writes or be used
as a dual-write target.

The local pilot PostgreSQL service uses the persistent Docker volume
`marine_pilot_postgres_data`. Credentials and `DATABASE_URL` are stored outside
Git in the operator environment. Verify the service with `docker ps`,
`pg_isready`, `/health/live`, and `/health/ready`; readiness must report
`database_backend: postgresql` and both migration versions current.

1. Schedule a maintenance window and announce write unavailability.
2. Stop API workers and all writes; confirm one authoritative database only.
3. Create a final SQLite online backup and SHA-256; retain it read-only.
4. Copy persistent uploads and artifacts without changing references.
5. Create a new empty PostgreSQL database and run the migration rehearsal command.
6. Require all table counts/fingerprints, FKs, sequences, indexes, and artifact hashes to pass.
7. Run the migration manager twice; second run must be a no-op.
8. Change the single authoritative `DATABASE_URL` to PostgreSQL. Never dual-write.
9. Start backend and worker; verify liveness/readiness, public reads, login, admin authorization, operational/scientific queues and event claims.
10. Re-enable access gradually and monitor errors, pool usage and queue state.
11. Retain the cutover SQLite snapshot and migration manifest for rollback.

## Rollback

Before any PostgreSQL writes, rollback is simply: stop services, restore the previous `DATABASE_URL`, verify the retained SQLite hash, start and smoke-test.

After PostgreSQL accepts writes, never switch back blindly: stop writes and reconcile PostgreSQL-only changes first. Preserve both databases and investigate offline. Dual writes are prohibited.

The retained SQLite snapshot is never deleted during ordinary PostgreSQL
operation. Rollback requires an explicit write freeze and hash verification;
PostgreSQL-only writes must never be merged automatically.
