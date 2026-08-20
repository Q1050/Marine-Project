import { useEffect, useMemo, useState } from "react";
import { getRegionSpeciesIntelligence } from "../services/api";

const number = (value) => Number(value || 0).toLocaleString();

function LoadingState() {
  return (
    <div className="rsi-state rsi-state--loading">
      <p>Loading regional species intelligence…</p>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rsi-state rsi-state--error" role="alert">
      <h2>Regional species intelligence unavailable</h2>
      <p>{message || "The regional species intelligence service is currently unavailable."}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="rsi-state__retry">
          Retry
        </button>
      )}
    </div>
  );
}

function EmptyState({ hasUnresolved }) {
  return (
    <div className="rsi-state rsi-state--empty">
      <h2>No canonical species reported yet</h2>
      <p>
        No canonical species identities are currently represented by regional
        observation evidence or configured scientific programs in this region.
      </p>
      {hasUnresolved && (
        <p className="rsi-state__hint">
          Unresolved observation evidence is reported separately below.
        </p>
      )}
    </div>
  );
}

function CapabilityTag({ label, value, available }) {
  return (
    <span className={`rsi-capability ${available ? "rsi-capability--available" : "rsi-capability--unavailable"}`}>
      {label}: {value}
    </span>
  );
}

function SpeciesListItem({ item, isSelected, onSelect }) {
  const evidenceTotal = item.evidence?.total ?? 0;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`rsi-list-item ${isSelected ? "rsi-list-item--selected" : ""}`}
      >
        <div className="rsi-list-item__head">
          <strong>{item.common_name || item.scientific_name}</strong>
          <span className="rsi-list-item__scientific">{item.scientific_name}</span>
        </div>
        <div className="rsi-list-item__meta">
          <span>
            <strong>{number(evidenceTotal)}</strong> reports
          </span>
          <span>
            <strong>{number(item.jurisdictions_with_evidence || 0)}</strong> jurisdiction
            {item.jurisdictions_with_evidence === 1 ? "" : "s"} with evidence
          </span>
          <span>
            <strong>{number(item.scientific_programs?.length || 0)}</strong> scientific program
            {(item.scientific_programs?.length || 0) === 1 ? "" : "s"}
          </span>
        </div>
      </button>
    </li>
  );
}

function SpeciesDetail({ species, jurisdictionMeta }) {
  const evidence = species.evidence || {};
  const perJurisdiction = species.per_jurisdiction || [];
  const scientificPrograms = species.scientific_programs || [];
  const suitabilityDeployments = species.suitability_deployments || [];
  const priorityGenerations = species.monitoring_priority_generations || [];

  return (
    <article className="rsi-detail">
      <header className="rsi-detail__header">
        <p className="rsi-detail__eyebrow">Canonical species identity</p>
        <h2>{species.scientific_name}</h2>
        {species.common_name && species.common_name !== species.scientific_name && (
          <p className="rsi-detail__common">{species.common_name}</p>
        )}
      </header>

      <section className="rsi-detail__section">
        <h3>Regional platform evidence</h3>
        <dl className="rsi-detail__grid">
          <Stat label="Total reports" value={number(evidence.total)} />
          <Stat label="Verified or corrected" value={number(evidence.verified_or_corrected)} />
          <Stat label="AI-supported pending" value={number(evidence.ai_supported)} />
          <Stat label="Pending review" value={number(evidence.pending_review)} />
        </dl>
        <p className="rsi-detail__note">
          {evidence.total > 0
            ? `${number(evidence.total)} regional report${evidence.total === 1 ? "" : "s"} on file across the region's jurisdictions.`
            : "No regional platform evidence recorded for this species yet."}
        </p>
      </section>

      <section className="rsi-detail__section">
        <h3>Jurisdiction coverage</h3>
        <ul className="rsi-detail__jurisdictions">
          {perJurisdiction.map((item) => {
            const jurisdictionInfo = item.jurisdiction || jurisdictionMeta.get(item.jurisdiction_id);
            const ev = item.evidence || {};
            const jurisdictionName = jurisdictionInfo?.name || "Unknown";
            const evidenceLabel = ev.total > 0
              ? `${number(ev.total)} report${ev.total === 1 ? "" : "s"} (${number(ev.verified_or_corrected)} verified)`
              : "No platform evidence recorded";
            return (
              <li key={item.jurisdiction_id} className="rsi-detail__jurisdiction">
                <div className="rsi-detail__jurisdiction-head">
                  <strong>{jurisdictionName}</strong>
                  <span className="rsi-detail__jurisdiction-meta">{evidenceLabel}</span>
                </div>
                <div className="rsi-detail__capabilities">
                  <CapabilityTag label="Species Program" value={item.scientific_program ? "Configured" : "Not configured"} available={item.scientific_program} />
                  <CapabilityTag label="Habitat suitability" value={item.suitability} available={item.suitability === "Available"} />
                  <CapabilityTag label="Monitoring Priority" value={item.monitoring_priority} available={item.monitoring_priority === "Available"} />
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {scientificPrograms.length > 0 && (
        <section className="rsi-detail__section">
          <h3>Configured scientific programs</h3>
          <ul className="rsi-detail__programs">
            {scientificPrograms.map((program) => (
              <li key={program.id}>
                <strong>{program.jurisdiction?.name || "Unknown jurisdiction"}</strong>
                <span>{program.common_name || "No common name"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(suitabilityDeployments.length > 0 || priorityGenerations.length > 0) && (
        <section className="rsi-detail__section">
          <h3>Predictive deployment summary</h3>
          <ul className="rsi-detail__deployments">
            {suitabilityDeployments.map((dep) => (
              <li key={dep.id}>
                Suitability deployment: <code>{dep.model_version}</code>
                {dep.jurisdiction_id ? ` (jurisdiction ${dep.jurisdiction_id})` : ""}
              </li>
            ))}
            {priorityGenerations.map((gen) => (
              <li key={gen.id}>
                Monitoring Priority generation #{gen.id}
                {gen.jurisdiction_id ? ` (jurisdiction ${gen.jurisdiction_id})` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rsi-detail__section">
        <h3>Scientific status</h3>
        <p className="rsi-detail__status-note">
          Predictive scientific deployments are jurisdiction-specific.
          Regional species evidence does not represent a Caribbean-wide
          suitability or abundance model.
        </p>
      </section>
    </article>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function UnresolvedEvidence({ items }) {
  if (!items || items.length === 0) {
    return null;
  }
  return (
    <section className="rsi-unresolved">
      <h3>Unresolved observation evidence</h3>
      <p className="rsi-unresolved__note">
        The scientific names below appear in operational observation evidence but
        do not currently resolve to a canonical Species identity. They are
        retained here as unresolved evidence rather than being silently
        remapped.
      </p>
      <ul>
        {items.map((item) => (
          <li key={item.scientific_name}>
            <strong>{item.scientific_name}</strong>
            <span>{number(item.evidence?.total)} report{item.evidence?.total === 1 ? "" : "s"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function RegionalSpeciesIntelligencePage() {
  const [data, setData] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [errorMessage, setErrorMessage] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    getRegionSpeciesIntelligence("caribbean")
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoadState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setData(null);
        setErrorMessage(error?.message || "Regional species intelligence could not be loaded.");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  const reload = () => {
    setLoadState("loading");
    setErrorMessage(null);
    let active = true;
    getRegionSpeciesIntelligence("caribbean")
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoadState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setData(null);
        setErrorMessage(error?.message || "Regional species intelligence could not be loaded.");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  };

  const species = useMemo(() => data?.species || [], [data]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return species;
    return species.filter((item) =>
      item.scientific_name.toLowerCase().includes(needle)
      || (item.common_name && item.common_name.toLowerCase().includes(needle))
    );
  }, [species, query]);

  const selected = useMemo(() => {
    if (filtered.length === 0) return null;
    const explicit = filtered.find((item) => item.id === selectedId);
    return explicit || filtered[0];
  }, [filtered, selectedId]);

  const jurisdictionMeta = useMemo(() => {
    if (!data?.species) return {};
    const map = {};
    for (const item of data.species) {
      for (const pj of item.per_jurisdiction || []) {
        if (pj.jurisdiction) {
          map[pj.jurisdiction_id] = pj.jurisdiction;
        }
      }
    }
    return map;
  }, [data]);

  const unresolvedEvidence = data?.unresolved_evidence || [];

  return (
    <div className="rsi-page">
      <header className="rsi-page__header">
        <p className="rsi-page__eyebrow">Caribbean regional monitoring</p>
        <h1 className="rsi-page__title">Regional Species Intelligence</h1>
        <p className="rsi-page__subtitle">
          Canonical species identity, operational observation evidence, and
          jurisdiction-specific scientific deployment coverage across the
          configured Caribbean jurisdictions.
        </p>
      </header>

      {loadState === "loading" && <LoadingState />}
      {loadState === "error" && (
        <ErrorState message={errorMessage} onRetry={reload} />
      )}
      {loadState === "ready" && species.length === 0 && (
        <EmptyState hasUnresolved={unresolvedEvidence.length > 0} />
      )}

      {loadState === "ready" && species.length > 0 && (
        <div className="rsi-workspace">
          <aside className="rsi-list-panel">
            <label className="rsi-search">
              <span className="rsi-search__label">Search species</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Pterois volitans, Lionfish…"
                className="rsi-search__input"
              />
            </label>
            <p className="rsi-list-panel__count">
              {filtered.length} of {species.length} canonical species
            </p>
            <ul className="rsi-list" role="listbox">
              {filtered.map((item) => (
                <SpeciesListItem
                  key={item.id}
                  item={item}
                  isSelected={item.id === selectedId}
                  onSelect={() => setSelectedId(item.id)}
                />
              ))}
              {filtered.length === 0 && (
                <li className="rsi-list-empty">
                  No species match this filter.
                </li>
              )}
            </ul>
          </aside>
          <section className="rsi-detail-panel">
            {selected ? (
              <SpeciesDetail species={selected} jurisdictionMeta={jurisdictionMeta} />
            ) : (
              <p className="rsi-detail-empty">
                Select a species from the list to view canonical identity,
                regional evidence, and jurisdiction deployment coverage.
              </p>
            )}
          </section>
        </div>
      )}

      {loadState === "ready" && unresolvedEvidence.length > 0 && (
        <UnresolvedEvidence items={unresolvedEvidence} />
      )}
    </div>
  );
}