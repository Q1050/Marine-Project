# Milestone 13D Closure

The closure completes the human-operated early-warning workflow without enabling production automation.

Platform administrators can manage explicitly scoped Scientific Early-Warning Reviewer grants, inspect and transition anomaly configuration versions, and inspect/process controlled events. Operational observation reviewers remain separate and cannot configure or scientifically disposition anomaly assessments.

Configurations default to `DESCRIPTIVE_ONLY`. Trigger rules require governed rule identity/version metadata and limitations. Approved spatial and temporal rules may suggest review, but signals remain independent and no weighted anomaly score exists. Insufficient temporal coverage is descriptive and never implies absence or first occurrence.

The assessment map provides toggles for the selected observation, active marine boundary, governed occurrence baseline, verified non-duplicate observations, and environmental suitability. Suitability cells are loaded only through the active jurisdiction/taxon deployment. Public-display approval is irrelevant to authorized internal scientific use; inactive or mismatched deployments are excluded.

Successful occurrence-evidence apply, scientific deployment lifecycle changes, configuration activation/replacement, and expert verification emit deterministic events. Dry runs, review, failed/no-op applies, training, and public-display changes do not emit scientific dependency events. Processing stales only current matching jurisdiction/taxon assessments and never rewrites history.

Scientific claims are protected by a SQLite partial unique index allowing one `ASSIGNED` row per assessment. Reassignment first closes the prior assignment, preserving history. There is no scheduler, queue worker, Celery, Redis, or background daemon. Milestone 14 may consume the explicit event-processing contract; production automatic evaluation remains disabled.

Production received schema/index changes only. No anomaly examples, rules, reviewers, assessments, or events were seeded.
