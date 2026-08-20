import { useEffect, useState } from "react";
import { getJurisdictionSpeciesIntelligence } from "../services/api";
import { useJurisdiction } from "../geography/JurisdictionContext";

const number = (value) => Number(value || 0).toLocaleString();

function LoadingState() {
  return (
    <div className="rsi-state rsi-state--loading">
      <p>Loading jurisdiction species intelligence…</p>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rsi-state rsi-state--error" role="alert">
      <h2>Jurisdiction species intelligence unavailable</h2>
      <p>{message || "The jurisdiction species intelligence service is currently unavailable."}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="rsi-state__retry">
          Retry
        </button>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rsi-state rsi-state--empty">
      <h2>No canonical species reported yet</h2>
      <p>
        No canonical species identities are currently represented by regional
        observation evidence or configured scientific programs.
      </p>
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

export default function JurisdictionSpeciesPage() {
  const { activeRegion, activeJurisdiction, jurisdiction: metadata } = useJurisdiction();
  const [data, setData] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [errorMessage, setErrorMessage] = useState(null);
  const scopeMissing = !activeRegion || !activeJurisdiction;

  useEffect(() => {
    if (scopeMissing) {
      return undefined;
    }
    let active = true;
    getJurisdictionSpeciesIntelligence(activeRegion, activeJurisdiction)
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoadState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setData(null);
        setErrorMessage(error?.message || "Jurisdiction species intelligence could not be loaded.");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, [activeRegion, activeJurisdiction, scopeMissing]);

  const species = data?.species || [];
  const unresolvedEvidence = data?.unresolved_evidence || [];

  const headerName = metadata?.name || data?.jurisdiction?.name || "Jurisdiction";

  return (
    <div className="rsi-page">
      <header className="rsi-page__header">
        <p className="rsi-page__eyebrow">{headerName} workspace</p>
        <h1 className="rsi-page__title">Species intelligence</h1>
        <p className="rsi-page__subtitle">
          Canonical species identities referenced from regional evidence and
          configured scientific programs. Predictive deployment state for this
          jurisdiction is shown alongside; no jurisdiction inherits another
          jurisdiction's predictive science.
        </p>
      </header>

      {scopeMissing && <ErrorState message="Jurisdiction scope is required." />}
      {!scopeMissing && loadState === "loading" && <LoadingState />}
      {!scopeMissing && loadState === "error" && <ErrorState message={errorMessage} onRetry={() => {
        setLoadState("loading");
        setErrorMessage(null);
        getJurisdictionSpeciesIntelligence(activeRegion, activeJurisdiction)
          .then((payload) => {
            setData(payload);
            setLoadState("ready");
          })
          .catch((error) => {
            setData(null);
            setErrorMessage(error?.message || "Jurisdiction species intelligence could not be loaded.");
            setLoadState("error");
          });
      }} />}
      {!scopeMissing && loadState === "ready" && species.length === 0 && <EmptyState />}

      {loadState === "ready" && species.length > 0 && (
        <ul className="rsi-country-list">
          {species.map((item) => {
            const perJurisdiction = item.per_jurisdiction?.[0] || {};
            const evidence = perJurisdiction.evidence || {};
            const evidenceLabel = evidence.total > 0
              ? `${number(evidence.total)} report${evidence.total === 1 ? "" : "s"} (${number(evidence.verified_or_corrected)} verified)`
              : "No platform evidence recorded";
            return (
              <li key={item.id} className="rsi-country-list__item">
                <div className="rsi-country-list__head">
                  <strong>{item.common_name || item.scientific_name}</strong>
                  <span className="rsi-country-list__scientific">{item.scientific_name}</span>
                </div>
                <p className="rsi-country-list__meta">
                  {evidenceLabel} in {headerName}
                </p>
                <div className="rsi-detail__capabilities">
                  <CapabilityTag
                    label="Species Program"
                    value={perJurisdiction.scientific_program ? "Configured" : "Not configured"}
                    available={perJurisdiction.scientific_program}
                  />
                  <CapabilityTag label="Habitat suitability" value={perJurisdiction.suitability || "Not configured"} available={perJurisdiction.suitability === "Available"} />
                  <CapabilityTag label="Monitoring Priority" value={perJurisdiction.monitoring_priority || "Not configured"} available={perJurisdiction.monitoring_priority === "Available"} />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {loadState === "ready" && unresolvedEvidence.length > 0 && (
        <section className="rsi-unresolved">
          <h3>Unresolved observation evidence</h3>
          <p className="rsi-unresolved__note">
            Scientific names below appear in operational observation evidence
            but do not currently resolve to a canonical Species identity. They
            are retained as unresolved evidence rather than being silently
            remapped.
          </p>
          <ul>
            {unresolvedEvidence.map((item) => (
              <li key={item.scientific_name}>
                <strong>{item.scientific_name}</strong>
                <span>{number(item.evidence?.total)} report{item.evidence?.total === 1 ? "" : "s"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}