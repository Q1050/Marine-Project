# Failure and recovery

- **Backend unavailable:** check liveness, structured error logs by correlation ID, configuration validation, storage and database reachability.
- **Database contention:** on PostgreSQL inspect connection pool exhaustion, blocked transactions and worker claims; do not terminate sessions blindly. For SQLite development, stop duplicate writers and retain the 5-second busy timeout—never delete WAL files.
- **Corruption suspected:** stop writes and preserve evidence. For PostgreSQL restore the verified `pg_dump` into a new database and compare; for SQLite preserve DB/WAL/SHM files and run `PRAGMA integrity_check`.
- **Provider unavailable:** keep governed artifacts/state unchanged; retry only bounded transient acquisition work. Health checks intentionally do not call providers.
- **Event repeatedly failing:** inspect safe category/reason, dependency freshness, and attempts. Do not infinitely retry or enable automation to bypass review.
- **Model unavailable:** keep public/governed directories available, mark inference not ready, restore the exact hashed artifact. Never substitute an unreviewed model.
- **Storage full/backup failure:** stop new uploads, preserve newest valid backup, add controlled capacity, then retry. Do not blindly delete scientific artifacts.
- **Failed migration:** stop, preserve DB, diagnose on disposable copy, restore the pre-migration backup if necessary. Never mark the ledger manually.
- **Accidental configuration activation:** deactivate through the governed transition, inspect emitted invalidation event, verify no automatic assessment occurred, and audit the action.
