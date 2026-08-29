# Identification-media source governance

Media providers use a distinct registry from occurrence and public-display sources. Registration preserves provider, transport, documentation, license model, attribution requirements, access method, scopes, provider/configuration versions, provenance, limitations, and a deterministic fingerprint.

Lifecycle is `READY_FOR_REVIEW → APPROVED → ACTIVE`, with rejected, deactivated, and superseded outcomes. Only active sources may create candidates. Search-engine results are not governed sources. Provider asset IDs make acquisition idempotent; paginated adapters must respect provider rate limits and retain immutable acquisition manifests.

A large acquisition must first register and review the source, validate item-level licensing, run a bounded dry run, inspect normalized candidates, enable controlled workers, monitor failure/retry queues, and only then increase page/batch limits.

