# Caribbean scientific corpus foundation

The corpus is a governed catalog and work projection, not a claim that a taxon occurs in a jurisdiction. PostgreSQL stores normalized identities, workflow state, audit references, hashes, and applicability. Source artifacts and media remain hash-addressed external or controlled-local objects.

## Intake and lifecycle

Administrators may validate pasted scientific names, CSV, or JSON (maximum 10,000 candidates / 5 MB). Inputs normalize to the existing regional manifest contract and receive a deterministic content fingerprint. Existing provider resolution, synonym/rank handling, per-item review, partial apply, retry, and manifest-run audit remain authoritative. Validation and preflight perform no scientific writes.

Applied regional taxa can be viewed through the jurisdiction × taxon readiness matrix. Its categorical dimensions are taxonomy, occurrence, ecology, public directory, imagery, identification corpus, environmental covariates, suitability, and early warning. There is no overall score or percentage.

Taxonomic display groups (fish, algae/seaweed, crustaceans, molluscs, cnidarians, echinoderms, other) are derived only from governed authoritative lineage. `OTHER` also covers insufficient lineage and is not a biological assertion.

## Current production scope

Milestone 16 adds infrastructure and projections only. It does not bulk-populate taxa, acquire imagery, train models, apply occurrence candidates, or create ecological assertions. Existing reviewed/applied taxa remain the only populated corpus.

