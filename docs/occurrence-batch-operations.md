# Occurrence batch operations

Occurrence batches are durable, idempotent region-scoped collections of jurisdiction × taxon × governed-source items. Preparation records deterministic configuration and per-item readiness. Blocked items remain visible.

Workers are disabled by default. Manual workers claim eligible items using a lease and, on PostgreSQL, `FOR UPDATE SKIP LOCKED`. Claims have tokens, retry counts, provider errors, completion metadata, and scoped summaries. A retry never bypasses occurrence-source, taxonomy, jurisdiction, licensing, or scientific-readiness gates.

This foundation does not start bulk acquisition and never converts acquired occurrences into ecological status.
