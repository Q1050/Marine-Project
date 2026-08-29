# Corpus storage and retention

PostgreSQL is the metadata system of record. It stores canonical identities, hashes, source references, workflow/audit state, applicability, and compact normalized records. Large source artifacts, imagery, and model files are not stored as database blobs.

`ArtifactReference` supplies SHA-256 identity, media type, size, provider, source reference, availability, and either a controlled local path or an external URI. API responses must not expose internal filesystem paths. This abstraction permits future S3-compatible object storage without changing scientific identities.

Recommended production policy:

1. Hash bytes before parsing or persistence.
2. Keep originals immutable; normalized derivatives receive their own fingerprints.
3. Restrict formats and sizes and parse defensively.
4. Back up PostgreSQL plus the external artifact inventory.
5. Retain superseded scientific versions and audit relationships.
6. Monitor missing objects, hash mismatches, storage growth, retry queues, and backup restores.

Milestone 16 does not relocate existing artifacts or expand production storage.
