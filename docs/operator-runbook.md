# Operator runbook

- Inspect `/health/live`, `/health/ready`, then Admin → System. A readiness failure is actionable; do not bypass it.
- Provision a pilot user through Admin → Users or the explicit bootstrap CLI in the correct environment. Grant operational or scientific jurisdiction access separately. Organization metadata never grants authority.
- Revoke a grant or deactivate the user immediately when access ends; existing bearer sessions stop authorizing inactive users.
- Inspect durable events in Early Warning/System. Manual processing and retries are platform-admin operations. Retry only `RETRYABLE`/eligible failed work; never reinterpret a scientific conflict as infrastructure failure.
- Create and verify a managed backup before migrations and at the configured operational cadence. PostgreSQL backup requires `pg_dump`; restore targets a new empty database. Check storage and protect the newest valid backup. Retention defaults to 14 and is configurable.
- Review pilot feedback in the admin console. It must not contain passwords, tokens, or private evidence.
- Shut down safely: stop worker, stop new writes/API, create backup, then stop services.
- Automatic anomaly evaluation is two-key controlled: global environment gate plus an active reviewed configuration. Default is off.
