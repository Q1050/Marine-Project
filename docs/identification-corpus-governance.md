# Identification corpus governance

A versioned corpus plan binds a region, governed taxa, taxonomic groups, provider preferences, per-taxon targets, license/quality/duplicate policies, provenance, limitations, and a deterministic fingerprint. Plans reject taxa not already approved in `RegionalTaxonRegistry`; a future 100–300 taxon target is capacity planning, not a fabricated registry.

Assets require explicit approval before corpus inclusion. Frozen corpus membership binds asset hashes, labels, licenses, attribution, duplicate groups, reviewer state, and deterministic split definitions. Related event/specimen/hash/perceptual groups stay within one split. Small or weak corpora return `SPLIT_NOT_RECOMMENDED`/review-required semantics rather than forcing evaluation.
