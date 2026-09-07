# Caribbean Marine Monitor — buildathon summary

## 30 seconds

Caribbean Marine Monitor turns public and partner-submitted marine sightings into reviewable, jurisdiction-scoped intelligence. AI can support identification, but people govern verification, taxonomy, evidence, and public scientific claims. The system keeps occurrence evidence, ecological status, habitat suitability, and anomaly review as separate concepts.

## One minute

An observation enters a jurisdiction queue with its media, location, provenance, AI candidates, and duplicate context. Authorized reviewers confirm, correct, reject, or request more information. Verified reports can later enter a separate governed evidence workflow; they do not automatically become ecological-status evidence. Public directories show only current approved assertions. Scientific models are versioned, their outputs use constrained language, and missing evidence remains visible rather than being replaced by invented certainty.

## Technical view

- React/Vite/Leaflet frontend with public, jurisdiction reviewer, and platform-admin workspaces.
- FastAPI and SQLAlchemy services backed by authoritative PostgreSQL for the pilot.
- Append-only review events and explicit source, artifact, taxonomy, licensing, and jurisdiction provenance.
- Governed scientific datasets, deployments, occurrence evidence, ecological assertions, and anomaly snapshots.
- BioCLIP is an identification-support component; it is not ecological inference.
- Deterministic taxon and artifact fingerprints support review, retry, and audit.

## Scientific safeguards

- Expert verification overrides AI identification.
- Duplicate observations do not become independent ecological evidence.
- Regional taxonomy does not imply jurisdiction presence.
- Occurrence does not imply invasive status.
- Habitat suitability does not imply presence, spread, or invasion probability.
- Empty governed results are valid and explicitly explained.

## Agency value

The platform gives marine agencies one operational path for receiving sightings, assigning human review, preserving evidence, publishing governed species information, and prioritizing monitoring—without collapsing administrative, operational, and scientific authority into one role.

