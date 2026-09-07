# Multi-source identification media

Milestone 18 uses a provider-neutral acquisition contract and the existing governed media-asset model. GBIF and Wikimedia Commons retain their own canonical identifiers, upstream references, creators, licenses, attribution, query context, and provider metadata. Provider calls are bounded, delayed, retried with backoff, resumable through fingerprinted acquisition runs, and idempotent.

Commons is queried only through the official MediaWiki API. Search context is not taxonomic proof: Commons candidates enter `REVIEW_REQUIRED` taxonomy linkage and cannot be approved without human review. Exact SHA-256 and perceptual duplicate checks run across all providers; uncertain perceptual matches are never merged automatically.

Identification media does not establish regional or jurisdiction occurrence, ecology, invasiveness, suitability, or anomaly evidence.
