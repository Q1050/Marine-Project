# Corpus review workflow

Platform administrators can filter candidates by taxon, provider, license, and review state, inspect controlled thumbnails and provenance, and record `APPROVED`, `EXCLUDED`, `TAXONOMY_REVIEW_REQUIRED`, `DUPLICATE`, or `NEEDS_REVIEW`. Every action adds an append-only review event. Approval is blocked by unresolved taxonomy, restricted licensing, invalid media, or duplicate status.

Bulk approval must apply the same row-level gates and explicit confirmation. Acquired media is never automatically approved. Existing GBIF assets remain awaiting review.
