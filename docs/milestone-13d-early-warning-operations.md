# Early-warning operations and scientific review

Early-warning evaluation is a downstream, conservative scientific-review aid. It does not establish invasive status, occurrence probability, range expansion, threat, or ecological impact. Operational observation review confirms identity; scientific early-warning review interprets governed context. Those permissions and workflows are separate.

Jurisdiction scientific reviewers receive explicit, revocable jurisdiction grants. They can inspect, claim, and disposition assessments only within those jurisdictions. Platform administrators manage grants and anomaly configurations. Scientific reviewers cannot approve taxonomy, occurrence evidence, ecological status, or model deployments through this workflow.

Configurations are jurisdiction × taxon scoped and move through `DRAFT`, `READY_FOR_REVIEW`, `APPROVED`, and `ACTIVE`, with `REJECTED`, `DEACTIVATED`, and `SUPERSEDED` terminal/history states. `DESCRIPTIVE_ONLY` is the safe default. No threshold is seeded in production. Once approved, scientific fields cannot be silently edited; a replacement version is required.

Expert confirmation/correction records an idempotent scientific domain event. Events retain processing attempts and can be pending, processing, processed, retryable, failed, or skipped. The production automatic-evaluation switch is false. When disabled, processing records `SKIPPED` and creates no assessment. An enabled switch is meaningful only on an active reviewed configuration.

Baseline, suitability-deployment, and configuration changes use jurisdiction × taxon scoped invalidation. Existing assessments become stale; they are not overwritten, and no Caribbean-wide synchronous reevaluation occurs. Re-evaluation creates a new immutable snapshot and retains superseded history.

The internal map shows only the selected verified observation, governed occurrence evidence, verified non-duplicate platform observations, and active jurisdiction boundary. Suitability remains contextual and is never used to reject an observation. The map and review history are protected institutional data and are not added to public APIs.

Production remains intentionally empty for anomaly assessments, configurations, reviewer grants, assignments, and scientific events after migration. The existing observations are not evaluated to populate a demo.

The 13D Closure adds platform-admin screens for scientific reviewer grants, configuration lifecycle/history, and controlled events. The internal map now has explicit observation, boundary, governed-baseline, verified-observation, and deployment-scoped suitability layers. Operational observation review shows eligibility and current scientific context without granting scientific disposition authority.

Reviewed temporal rules use an explicit `rule_id`, `rule_version`, minimum dated-evidence requirement, and days-since-latest-record rule. Missing or insufficient dates cannot trigger review. No recent governed record never means absence or first occurrence.

Governed occurrence apply, scientific suitability deployment changes, anomaly configuration activation, and expert verification emit deterministic domain events only after meaningful successful state changes. Event processing remains manual and production automatic evaluation remains disabled. A partial unique database index guarantees one active scientific assignment per assessment.
