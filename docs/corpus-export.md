# Controlled corpus export

The exporter produces a deterministic manifest outside PostgreSQL containing corpus identity/version, governed taxon labels, split, artifact identity, source/provider identity, attribution/license, supplied biological metadata, event/specimen identity, provenance semantics, and export fingerprint.

Excluded or license-unresolved assets are omitted. Re-running unchanged corpus state produces the same manifest fingerprint. Export consumers must verify referenced object hashes before use. Export is preparation for model development; it does not trigger training or deployment.

