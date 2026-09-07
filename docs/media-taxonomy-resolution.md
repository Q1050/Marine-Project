# Media taxonomy resolution

Media taxonomy evidence is append-only and separate from human resolution. The MediaWiki adapter records the Commons page identity, structured metadata, external attribution links, retrieval time, limitations, and a deterministic fingerprint. Repeating acquisition is idempotent.

A Commons search result, filename, category, description, attribution, or visual resemblance can help locate evidence but is not automatically governed species identification. External names are reconciled against the existing `Species` target; genus-only, different-species, ambiguous, or conflicting evidence cannot silently become `Pterois volitans`.

Only a platform administrator can record a final resolution, with persisted evidence and a concise reason. `CONFIRMED_TARGET_TAXON` updates corpus eligibility; other conclusions preserve exclusion or taxonomy-review status. Original media review events, evidence rows, and resolution rows remain append-only.

Media identification is not jurisdiction occurrence evidence, ecological status, or invasive status.
