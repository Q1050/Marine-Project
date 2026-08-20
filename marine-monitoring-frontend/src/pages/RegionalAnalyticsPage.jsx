import { useEffect, useMemo, useState } from "react";
import { getRegionAnalytics } from "../services/api";

const number = (value) => Number(value || 0).toLocaleString();

function readable(value) {
  return value
    ? String(value).replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
    : "Unavailable";
}

function LoadingState() {
  return (
    <div className="rca-state rca-state--loading">
      <p>Loading Caribbean regional operational analytics…</p>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rca-state rca-state--error" role="alert">
      <h2>Regional analytics unavailable</h2>
      <p>{message || "The regional analytics service is currently unavailable."}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="rca-state__retry">
          Retry
        </button>
      )}
    </div>
  );
}

function OperationalSummary({ data }) {
  const observations = data.observations || {};
  const investigations = data.investigations || {};
  const field = data.field_activity || {};
  return (
    <section className="rca-summary">
      <div className="rca-summary__kpis">
        <Kpi label="Total observations" value={number(observations.total)} sublabel={`${number(observations.confirmed)} confirmed · ${number(observations.corrected)} corrected`} />
        <Kpi label="Reports requiring review" value={number(observations.pending_review)} sublabel={`${number(observations.pending)} pending · ${number(observations.needs_more_review)} needs more`} />
        <Kpi label="Investigations" value={number(investigations.total)} sublabel={`${number(investigations.active)} active · ${number(investigations.completed)} completed`} />
        <Kpi label="Field visits" value={number(field.total)} sublabel={`${number(field.detection_outcomes?.detected)} detected · ${number(field.detection_outcomes?.not_detected)} not detected`} />
      </div>
    </section>
  );
}

function Kpi({ label, value, sublabel }) {
  return (
    <article className="rca-kpi">
      <p className="rca-kpi__label">{label}</p>
      <strong className="rca-kpi__value">{value}</strong>
      {sublabel && <p className="rca-kpi__sublabel">{sublabel}</p>}
    </article>
  );
}

function ActivityBuckets({ data }) {
  const buckets = data?.observation_buckets?.buckets || [];
  if (buckets.length === 0) {
    return (
      <article className="rca-card">
        <h3 className="rca-card__title">Reporting activity over time</h3>
        <p className="rca-empty">No platform reporting activity recorded yet.</p>
      </article>
    );
  }
  const maxTotal = buckets.reduce((max, item) => Math.max(max, item.total), 0);
  return (
    <article className="rca-card">
      <div className="rca-card__head">
        <h3 className="rca-card__title">Platform reporting activity over time</h3>
        <span className="rca-card__meta">
          {data.observation_buckets.strategy === "monthly" ? "Monthly buckets" : "Daily buckets"} · {data.observation_buckets.bucket_count} buckets
        </span>
      </div>
      <p className="rca-card__note">
        Reporting activity reflects observations submitted to the platform. It is not a species population trend.
      </p>
      <ul className="rca-bars rca-bars--activity">
        {buckets.map((bucket) => (
          <li key={bucket.bucket}>
            <div className="rca-bars__head">
              <span>{readable(bucket.bucket)}</span>
              <span className="rca-bars__count">{number(bucket.total)} reports</span>
            </div>
            <div className="rca-bars__track">
              <div
                className="rca-bars__fill rca-bars__fill--total"
                style={{ width: maxTotal > 0 ? `${Math.max(2, (bucket.total / maxTotal) * 100)}%` : "0%" }}
                aria-label={`${bucket.total} total reports`}
              />
              {bucket.verified_or_corrected > 0 && (
                <div
                  className="rca-bars__fill rca-bars__fill--verified"
                  style={{ width: maxTotal > 0 ? `${(bucket.verified_or_corrected / maxTotal) * 100}%` : "0%" }}
                  aria-label={`${bucket.verified_or_corrected} verified or corrected`}
                />
              )}
            </div>
            <p className="rca-bars__caption">
              {number(bucket.verified_or_corrected)} verified · {number(bucket.pending_or_needs_review)} pending review · {number(bucket.ai_supported_only)} AI-supported
            </p>
          </li>
        ))}
      </ul>
      <p className="rca-card__microcopy">
        Period: {data.observation_buckets.earliest} → {data.observation_buckets.latest}
      </p>
    </article>
  );
}

function JurisdictionComparison({ data }) {
  const jurisdictions = data?.jurisdictions || [];
  const maxObservations = jurisdictions.reduce((max, item) => Math.max(max, item.observations?.total || 0), 0);
  return (
    <article className="rca-card">
      <h3 className="rca-card__title">Jurisdiction comparison</h3>
      {jurisdictions.length === 0 ? (
        <p className="rca-empty">No jurisdictions are currently configured.</p>
      ) : (
        <ul className="rca-jurisdiction-grid">
          {jurisdictions.map((item) => (
            <li key={item.jurisdiction.slug} className="rca-jurisdiction">
              <div className="rca-jurisdiction__head">
                <strong>{item.jurisdiction.name}</strong>
                <span className="rca-jurisdiction__meta">
                  {item.observations.total === 0
                    ? "No platform observations recorded"
                    : `${number(item.observations.total)} observation${item.observations.total === 1 ? "" : "s"}`}
                </span>
              </div>
              <dl className="rca-jurisdiction__grid">
                <Stat label="Verified or corrected" value={item.observations.confirmed + item.observations.corrected} />
                <Stat label="Pending review" value={item.observations.pending + item.observations.needs_more_review} />
                <Stat label="Investigations" value={`${item.investigations.active} / ${item.investigations.total}`} />
                <Stat label="Field visits" value={number(item.field_visits.total)} />
                <Stat label="Operational boundary" value={item.operational_boundary_configured ? "Configured" : "Not configured"} />
                <Stat label="Participating organizations" value={item.participating_organizations ? "Available" : "Not configured"} />
                <Stat label="Jurisdiction manager" value={item.jurisdiction_managers ? "Available" : "Not configured"} />
                <Stat label="Species program" value={item.scientific_programs_configured ? "Available" : "Not configured"} />
                <Stat label="Habitat suitability" value={item.habitat_suitability} />
                <Stat label="Monitoring Priority" value={item.monitoring_priority} />
              </dl>
              {maxObservations > 0 && (
                <div className="rca-bars__track" aria-hidden="true">
                  <div
                    className="rca-bars__fill rca-bars__fill--total"
                    style={{ width: `${(item.observations.total / maxObservations) * 100}%` }}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{typeof value === "number" ? number(value) : value}</dd>
    </div>
  );
}

function SpeciesAnalytics({ data }) {
  const species = data?.species || [];
  if (species.length === 0) {
    return (
      <article className="rca-card">
        <h3 className="rca-card__title">Species evidence across the region</h3>
        <p className="rca-empty">No species observations are currently recorded.</p>
      </article>
    );
  }
  const maxEvidence = species.reduce((max, item) => Math.max(max, item.total_observations), 0);
  return (
    <article className="rca-card">
      <div className="rca-card__head">
        <h3 className="rca-card__title">Species evidence across the region</h3>
        <span className="rca-card__meta">{species.length} species · anchored on canonical identities</span>
      </div>
      <p className="rca-card__note">{data.note}</p>
      <ol className="rca-species-list">
        {species.map((item) => (
          <li key={item.scientific_name}>
            <div className="rca-species-list__head">
              <strong>{item.common_name || item.scientific_name}</strong>
              <span className="rca-species-list__scientific">{item.scientific_name}</span>
            </div>
            <div className="rca-species-list__meta">
              <span>
                <strong>{number(item.total_observations)}</strong> report{item.total_observations === 1 ? "" : "s"}
              </span>
              <span>
                <strong>{number(item.verified_or_corrected)}</strong> verified or corrected
              </span>
              <span>
                <strong>{number(item.ai_supported)}</strong> AI-supported
              </span>
              <span>
                <strong>{number(item.jurisdictions_with_evidence)}</strong> jurisdiction{item.jurisdictions_with_evidence === 1 ? "" : "s"} with evidence
              </span>
            </div>
            <div className="rca-bars__track" aria-hidden="true">
              <div
                className="rca-bars__fill rca-bars__fill--total"
                style={{ width: maxEvidence > 0 ? `${(item.total_observations / maxEvidence) * 100}%` : "0%" }}
              />
              <div
                className="rca-bars__fill rca-bars__fill--verified"
                style={{ width: maxEvidence > 0 ? `${(item.verified_or_corrected / maxEvidence) * 100}%` : "0%" }}
              />
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}

function ReviewWorkload({ data }) {
  const total = data?.total || 0;
  if (total === 0) {
    return (
      <article className="rca-card">
        <h3 className="rca-card__title">Review workload</h3>
        <p className="rca-empty">No platform observations currently require review.</p>
      </article>
    );
  }
  const byJurisdiction = data?.by_jurisdiction || [];
  const max = byJurisdiction.reduce((acc, item) => Math.max(acc, item.total), 0);
  return (
    <article className="rca-card">
      <div className="rca-card__head">
        <h3 className="rca-card__title">Review workload</h3>
        <span className="rca-card__meta">{number(total)} reports awaiting review</span>
      </div>
      <p className="rca-card__note">Operational workload metric. Not a scientific interpretation.</p>
      <ul className="rca-bars">
        {byJurisdiction.map((item) => (
          <li key={item.jurisdiction}>
            <div className="rca-bars__head">
              <span>{item.jurisdiction_name}</span>
              <span className="rca-bars__count">{number(item.total)} reports</span>
            </div>
            <div className="rca-bars__track">
              <div
                className="rca-bars__fill rca-bars__fill--pending"
                style={{ width: max > 0 ? `${(item.total / max) * 100}%` : "0%" }}
              />
            </div>
            <p className="rca-bars__caption">
              {number(item.pending)} pending · {number(item.needs_more_review)} needs more review
            </p>
          </li>
        ))}
      </ul>
    </article>
  );
}

function InvestigationAnalytics({ data }) {
  const total = data?.total || 0;
  if (total === 0) {
    return (
      <article className="rca-card">
        <h3 className="rca-card__title">Investigations</h3>
        <p className="rca-empty">No investigations are currently recorded across the region.</p>
      </article>
    );
  }
  return (
    <article className="rca-card">
      <h3 className="rca-card__title">Investigations</h3>
      <ul className="rca-state-grid">
        <StateChip label="Planned" value={data.planned} />
        <StateChip label="In progress" value={data.in_progress} />
        <StateChip label="Completed" value={data.completed} />
        <StateChip label="Cancelled" value={data.cancelled} />
        <StateChip label="Active (planned + in progress)" value={data.active} highlight />
        <StateChip label="Total" value={data.total} highlight />
      </ul>
    </article>
  );
}

function FieldActivity({ data }) {
  const total = data?.total || 0;
  const detection = data?.detection_outcomes || {};
  if (total === 0 && detection.total === 0) {
    return (
      <article className="rca-card">
        <h3 className="rca-card__title">Field activity</h3>
        <p className="rca-empty">No field visits have been recorded across the region yet.</p>
      </article>
    );
  }
  return (
    <article className="rca-card">
      <h3 className="rca-card__title">Field activity</h3>
      <ul className="rca-state-grid">
        <StateChip label="Submitted" value={data.submitted} />
        <StateChip label="Draft" value={data.draft} />
        <StateChip label="Total visits" value={data.total} highlight />
        <StateChip label="Detected" value={detection.detected} />
        <StateChip label="Not detected" value={detection.not_detected} />
        <StateChip label="Inconclusive" value={detection.inconclusive} />
      </ul>
      {data.non_detection_interpretation && (
        <p className="rca-card__microcopy">{data.non_detection_interpretation}</p>
      )}
    </article>
  );
}

function StateChip({ label, value, highlight }) {
  return (
    <li className={`rca-state-chip ${highlight ? "rca-state-chip--highlight" : ""}`}>
      <span>{label}</span>
      <strong>{number(value)}</strong>
    </li>
  );
}

function OperationalCoverage({ data }) {
  const items = [
    { label: "Configured jurisdictions", value: data.configured_jurisdictions || 0 },
    { label: "With operational boundaries", value: data.jurisdictions_with_boundaries || 0 },
    { label: "With participating organizations", value: data.jurisdictions_with_organizations || 0 },
    { label: "With jurisdiction managers", value: data.jurisdictions_with_managers || 0 },
    { label: "With species programs", value: data.jurisdictions_with_species_programs || 0 },
    { label: "With habitat suitability", value: data.jurisdictions_with_suitability || 0 },
    { label: "With Monitoring Priority", value: data.jurisdictions_with_monitoring_priority || 0 },
  ];
  return (
    <article className="rca-card">
      <h3 className="rca-card__title">Operational coverage</h3>
      <p className="rca-card__note">
        Configuration/readiness information. Not a synthetic readiness score.
      </p>
      <ul className="rca-coverage-grid">
        {items.map((item) => (
          <li key={item.label}>
            <span>{item.label}</span>
            <strong>{number(item.value)}</strong>
          </li>
        ))}
      </ul>
    </article>
  );
}

export default function RegionalAnalyticsPage() {
  const [data, setData] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [errorMessage, setErrorMessage] = useState(null);

  const reload = () => {
    let active = true;
    setLoadState("loading");
    setErrorMessage(null);
    getRegionAnalytics("caribbean")
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoadState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setData(null);
        setErrorMessage(error?.message || "Regional analytics could not be loaded.");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  };

  useEffect(() => {
    let active = true;
    getRegionAnalytics("caribbean")
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoadState("ready");
      })
      .catch((error) => {
        if (!active) return;
        setData(null);
        setErrorMessage(error?.message || "Regional analytics could not be loaded.");
        setLoadState("error");
      });
    return () => {
      active = false;
    };
  }, []);

  const summary = useMemo(() => data || null, [data]);
  const jurisdictionCount = useMemo(() => data?.jurisdictions?.length || 0, [data]);

  return (
    <div className="rca-page">
      <header className="rca-page__header">
        <p className="rca-page__eyebrow">Caribbean regional monitoring</p>
        <h1 className="rca-page__title">Regional operational analytics</h1>
        <p className="rca-page__subtitle">
          Reporting activity, review workload, investigations, and field
          activity aggregated regionally across {jurisdictionCount} configured
          jurisdiction{jurisdictionCount === 1 ? "" : "s"}. Predictive
          scientific values are intentionally excluded; there is no
          Caribbean-wide prediction model.
        </p>
      </header>

      {loadState === "loading" && <LoadingState />}
      {loadState === "error" && <ErrorState message={errorMessage} onRetry={reload} />}
      {loadState === "ready" && summary && (
        <>
          <OperationalSummary data={summary} />
          <section className="rca-grid">
            <ActivityBuckets data={summary.activity} />
            <JurisdictionComparison data={summary} />
            <SpeciesAnalytics data={summary.species_evidence} />
            <ReviewWorkload data={summary.review_workload} />
            <InvestigationAnalytics data={summary.investigations} />
            <FieldActivity data={summary.field_activity} />
            <OperationalCoverage data={summary.operational_coverage} />
          </section>
        </>
      )}
    </div>
  );
}