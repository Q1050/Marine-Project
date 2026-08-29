# Caribbean scientific scaling

The platform deliberately keeps five questions separate:

1. **Regional taxon** — a reviewed taxon belongs in the Caribbean catalog. This does not say that it occurs in every Caribbean jurisdiction.
2. **Jurisdiction occurrence** — governed records support that a taxon was recorded within one jurisdiction's reviewed boundary. This does not establish persistence, ecological status, or invasiveness.
3. **Jurisdiction ecological status** — an approved, jurisdiction-authoritative source supports one or more ecological classifications. Status never transfers from another jurisdiction or from regional reputation.
4. **Model readiness** — independently governed training, environmental, geographic, evaluation, and deployment prerequisites exist. Readiness does not trigger training and suitability does not confirm presence.
5. **Anomaly readiness** — descriptive prerequisites exist for later assessment. Readiness does not mean that an anomaly exists and does not run anomaly processing.

The Platform Administration → Scientific readiness workspace exposes a paginated jurisdiction × taxon matrix, a regional inventory, categorical reasons, and a read-only scientific work queue. It has no “approve all” action and computes no percentage readiness score.

## Onboarding an authoritative Jamaica invasive marine species list

Use this workflow only after receiving a traceable source from an agency or research provider.

1. Preserve the original document or CSV/JSON artifact without editing it. Record its organization, title, version/date, canonical reference, license/reuse terms, and limitations.
2. In **Ecological status → Sources**, register the source with `JURISDICTION_SPECIFIC` scope for Jamaica. Registration is not scientific approval.
3. Review and approve the source registration, its asserted semantics, and the explicit mapping from source categories to platform statuses. List membership is not `INVASIVE` unless the source category explicitly means invasive and that mapping is reviewed.
4. Upload the controlled CSV/JSON artifact and inspect its SHA-256, parser result, column mapping, warnings, and normalized fingerprint. Do not upload executable content or rely on filenames as identity.
5. Run preflight. Review taxonomy, jurisdiction, semantic, duplicate, and conflict outcomes row by row. Unknown taxa must go through the existing taxonomy candidate workflow; they are not silently created.
6. Resolve governed taxonomy, then rerun/re-evaluate affected ecological rows. Regional catalog inclusion still does not establish Jamaica presence or status.
7. Approve only eligible rows. Preserve conflicts from legitimate sources rather than voting or overwriting.
8. Apply selected approved rows. Application is idempotent and produces immutable jurisdiction assertions with source/artifact/run provenance.
9. Inspect the Jamaica current projection and public directory. Only current, approved, jurisdiction-authoritative, non-conflicting assertions may appear publicly.
10. Verify Bahamas, Barbados, and other jurisdictions remain unchanged. A Jamaica list never becomes a Caribbean-wide list.

Removal from a later list version is a review requirement, not automatic eradication or reversal. The legacy `INVASIVE / legacy-unverified` Pterois value remains excluded until a real authoritative assertion is reviewed and applied.
