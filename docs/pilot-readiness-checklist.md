# Pilot readiness checklist

| Area | State | Evidence / limitation |
|---|---|---|
| Security | PASS | Backend role/jurisdiction guards; private media route; upload signature/size checks; configurable pilot rate limits. Single-process limiter is a scaling limitation. |
| Data | PASS | Production counts/hash verified separately; controlled persistent paths. |
| Authorization | PASS | Operational, scientific, and platform-admin authorities remain separate. |
| Backup | PASS | SQLite online backup, SHA-256, integrity check, retention, explicit restore. Off-host scheduling remains operator responsibility. |
| Observability | PASS | Correlation IDs, structured request logs, readiness/liveness, admin status. No external metrics/APM backend. |
| Scientific governance | PASS | Global and reviewed per-configuration automation gates; no default configs. |
| Public UX | PASS | Governed public flow and explicit submission semantics; browser/device matrix remains pilot validation work. |
| Reviewer UX | PASS | Operational and scientific workflows exist with jurisdiction boundaries. |
| Demo | PASS | Separate DEMO database bootstrap/reset refuses production path. Full institutional rehearsal still required. |
| Deployment | PASS | Environment contract, Docker composition, persistent volume, reverse-proxy guidance. |
| Feedback | PASS | Reviewer submission and admin read workflow exists; lightweight disposition lifecycle is limited. |
