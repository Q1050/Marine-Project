# Scientific source strategy

Provider roles are deliberately separated:

- WoRMS is the preferred authoritative marine taxonomic identity and lineage resolver.
- OBIS is the existing governed marine occurrence acquisition interface; provider and upstream dataset provenance remain distinct.
- Jurisdiction agencies and reviewed scientific publications are required for jurisdiction ecological-status claims.
- Governed media requires item-level creator, license, attribution, and stable source reference.
- Environmental/model datasets require explicit applicability for their scientific role.

Aggregators are transport/discovery mechanisms, not automatic scientific authorities. A source must be registered, scoped, licensed, versioned, and reviewed for the claim it will support. Acquisition failures are retryable workflow failures; they do not alter previously approved science.

Priority should favor authoritative identity first, then jurisdiction occurrence, jurisdiction ecology, public media, identification-corpus metadata, and only afterward independently governed modeling or early-warning prerequisites.

