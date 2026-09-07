import { useEffect, useState } from "react";
import { getJurisdictionSpeciesIntelligence } from "../services/api";
import { useJurisdiction } from "../geography/JurisdictionContext";

const value = (input) => input || "Not configured";

export default function AgencySciencePage({ view }) {
  const { activeRegion, activeJurisdiction, jurisdiction } = useJurisdiction();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    getJurisdictionSpeciesIntelligence(activeRegion, activeJurisdiction).then((payload) => active && setData(payload)).catch((reason) => active && setError(reason?.message || "Scientific status is unavailable."));
    return () => { active = false; };
  }, [activeRegion, activeJurisdiction]);
  const name = jurisdiction?.name || data?.jurisdiction?.name || "Jurisdiction";
  if (error) return <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>;
  if (!data) return <p className="text-sm text-app-muted">Loading {name} scientific status…</p>;
  if (view === "early-warning") return <div className="mx-auto max-w-[1100px] space-y-5"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">{name} operational science</p><h1 className="mt-1 text-3xl font-bold">Early warning</h1><p className="mt-2 text-sm text-app-muted">Read-only jurisdiction status. Scientific assessment and configuration controls remain platform-governed.</p></header><section className="rounded-xl border border-app-border bg-white p-6"><h2 className="text-xl font-bold">No governed early-warning assessments are currently available</h2><p className="mt-2 text-sm text-app-muted">Automatic scientific evaluation is disabled. Assessments require the configured scientific workflow; no warning or anomaly status is inferred from observations alone.</p><dl className="mt-5 grid gap-3 sm:grid-cols-2"><Status label="Governed assessments" value="0"/><Status label="Automatic scientific evaluation" value="Disabled"/></dl></section></div>;
  return <div className="mx-auto max-w-[1100px] space-y-5"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">{name} operational science</p><h1 className="mt-1 text-3xl font-bold">Scientific readiness</h1><p className="mt-2 text-sm text-app-muted">Read-only jurisdiction readiness from configured species programs and deployments.</p></header>{(data.species || []).map((species) => {const scoped=species.per_jurisdiction?.[0]||{},evidence=scoped.evidence||species.evidence||{};return <section key={species.id} className="rounded-xl border border-app-border bg-white p-6"><div><h2 className="text-xl font-bold">{species.common_name||species.scientific_name}</h2><em className="text-sm text-app-muted">{species.scientific_name}</em></div><dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><Status label="Species program" value={scoped.scientific_program?"Configured":"Not configured"}/><Status label="Habitat suitability" value={value(scoped.suitability)}/><Status label="Monitoring priority" value={value(scoped.monitoring_priority)}/><Status label={`${name} reports`} value={String(evidence.total||0)}/><Status label="Verified or corrected" value={String(evidence.verified_or_corrected||0)}/><Status label="Automatic scientific evaluation" value="Disabled"/></dl></section>})}{(data.species||[]).length===0&&<section className="rounded-xl border border-app-border bg-white p-6 text-sm text-app-muted">No configured jurisdiction species readiness is currently available.</section>}</div>;
}

function Status({ label, value: status }) {return <div className="rounded-lg bg-slate-50 p-4"><dt className="text-[10px] font-bold uppercase tracking-wide text-app-muted">{label}</dt><dd className="mt-1 text-sm font-bold text-app-text">{status}</dd></div>}
