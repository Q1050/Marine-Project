# Identification corpus governance

Corpus versions move `DRAFT → READY_FOR_REVIEW → APPROVED → FROZEN`; rejection and supersession are explicit terminal alternatives. A corpus records purpose, taxonomic scope, source/provenance configuration, limitations, version, fingerprint, reviewer, and approval reference.

Only approved, training-eligible, valid, distinct assets may be included. Training must consume an approved/frozen version, never a mutable live query. Small pilots may use a `REFERENCE` split and report `BENCHMARK_READY`; they must not pretend to provide an independent train/validation/test evaluation.

Exports contain governed labels, attribution, source references, hashes, grouped split assignments, and a deterministic export fingerprint. Unresolved, excluded, or duplicate assets are omitted.
