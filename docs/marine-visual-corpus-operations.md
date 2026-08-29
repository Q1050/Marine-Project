# Marine visual-corpus operations

Safe acquisition sequence:

1. Register, review, and activate a scientifically credible source.
2. Confirm API terms, item-level licenses, attribution, rate limits, and scopes.
3. Create a small deterministic acquisition run for governed taxa.
4. Claim work through database leases; never enable uncontrolled workers.
5. Preserve the provider manifest and identifiers.
6. Hash bytes, validate decoding/format/dimensions, and store through the object abstraction.
7. Detect provider-ID, event/specimen, and SHA-256 duplicates; retain rather than delete them.
8. Review licensing, taxonomy, quality, and biological metadata.
9. Approve individual eligible assets and inspect taxon diversity.
10. Create a versioned corpus, deterministic grouped split, and reproducible export.

PostgreSQL stores metadata. Local controlled storage is supported for pilots; logical keys and hashes allow later S3-compatible storage. Internal keys are never public. Monitor lease expiry, retries, corrupt objects, hash mismatches, license changes, source deactivation, duplicate rates, storage growth, and restore tests.
