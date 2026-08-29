# Milestone 14 productionization audit

Before Milestone 14, local development worked but deployment values were hardcoded, API import eagerly initialized model/storage, health was shallow, migrations were phase scripts without a ledger, events had manual processing but no bounded worker, and backups were ad-hoc copies. Authentication already used scrypt hashes, hashed bearer tokens, expiry, inactive-user checks and backend jurisdiction guards. Private observation images already used an authorized route and no `/uploads` static mount remained. Reporter tokens are hashed.

Milestone 14 adds the environment contract, production validation, SQLite pilot pragmas, migration ledger, structured request logs/error envelope, health/readiness/status, controlled worker claim/retry/recovery, managed backup/restore, upload signature/size validation, rate limits, DEMO isolation, containers and operating documentation.

Remaining deployment limitations: bearer tokens are browser session storage rather than secure HttpOnly cookies (therefore CSRF is not the primary token transport risk, but XSS hardening remains important); rate limits are process-local; inference remains eagerly loaded; no OIDC/SSO, external log aggregation, metrics backend, off-host backup scheduler, malware scanner, or PostgreSQL HA is included. These are explicit pilot constraints, not hidden production claims.
