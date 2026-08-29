import { useEffect, useMemo, useState } from "react";
import { applyAdminEcologicalIngestion, createAdminEcologicalIngestion, getAdminEcologicalIngestion, getAdminEcologicalIngestionRuns, getAdminEcologicalSources, preflightAdminEcologicalArtifact, reviewAdminEcologicalIngestion } from "../../services/api";

const title = (value) => String(value || "").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());

export default function EcologicalSourceIngestionPanel({ jurisdictionId }) {
  const [sources, setSources] = useState([]), [runs, setRuns] = useState([]), [sourceId, setSourceId] = useState(""), [file, setFile] = useState(null), [result, setResult] = useState(null), [selected, setSelected] = useState([]), [error, setError] = useState(null), [busy, setBusy] = useState(false);
  const mapping = useMemo(() => ({ scientific_name: "scientific_name", common_name: "common_name", source_status: "source_status", effective_date: "effective_date", source_record_identifier: "source_record_identifier", jurisdiction: "jurisdiction" }), []);
  const load = () => Promise.all([getAdminEcologicalSources(), getAdminEcologicalIngestionRuns(jurisdictionId)]).then(([sourceData, runData]) => { setSources(sourceData.sources || []); setRuns(runData.runs || []); });
  useEffect(() => { if (jurisdictionId) load().catch((reason) => setError(reason.message)); }, [jurisdictionId]); // eslint-disable-line react-hooks/exhaustive-deps
  async function execute(action) { setBusy(true); setError(null); try { const value = await action(); setResult(value.run || value); if (value.run?.rows) setSelected([]); await load(); } catch (reason) { setError(reason.message); } finally { setBusy(false); } }
  async function review(disposition) { const reference = window.prompt("Review reference:"); if (reference) await execute(() => reviewAdminEcologicalIngestion(result.id, selected, disposition, reference)); }
  const rows = result?.rows || [];
  const eligible = (row) => ["READY", "CONFLICT_WITH_EXISTING_STATUS"].includes(row.preflight_classification);
  return <section className="mt-5 rounded-xl border border-app-border bg-white p-5">
    <h2 className="font-bold">Governed ecological-status sources</h2>
    <p className="mt-1 text-xs text-app-muted">Uploading a source records a source claim for review. It does not change platform-governed ecological status.</p>
    <div className="mt-4 grid gap-4 lg:grid-cols-[220px_1fr]">
      <nav className="space-y-2 text-xs" aria-label="Ecological status administration sections">{["SOURCES", "INGESTION RUNS", "REVIEW QUEUE", "CONFLICTS", "APPLIED STATUS"].map((item) => <div key={item} className="rounded-md border border-app-border bg-slate-50 px-3 py-2 font-bold text-slate-700">{item}</div>)}</nav>
      <div>
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
          <select aria-label="Governed source" value={sourceId} onChange={(event) => setSourceId(event.target.value)} className="rounded-lg border border-app-border px-3 py-2 text-sm"><option value="">Choose active source</option>{sources.filter((item) => item.workflow_status === "ACTIVE").map((item) => <option key={item.id} value={item.id}>{item.source_title} · {item.source_version || "unversioned"}</option>)}</select>
          <input aria-label="CSV or JSON artifact" type="file" accept=".csv,.json,text/csv,application/json" onChange={(event) => setFile(event.target.files?.[0] || null)} className="rounded-lg border border-app-border p-2 text-xs" />
          <button disabled={busy || !sourceId || !file} onClick={() => execute(() => preflightAdminEcologicalArtifact(sourceId, jurisdictionId, file, mapping))} className="rounded-lg border border-teal-700 px-3 py-2 text-xs font-bold text-teal-800 disabled:opacity-40">Preflight</button>
          <button disabled={busy || !sourceId || !file} onClick={() => execute(() => createAdminEcologicalIngestion(sourceId, jurisdictionId, file, mapping))} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Prepare ingestion</button>
        </div>
        <p className="mt-2 text-xs text-app-muted">Accepted controlled artifacts: CSV or JSON, maximum 5 MiB. Field and semantic mappings remain governed source configuration.</p>
        {runs.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{runs.map((run) => <button key={run.id} onClick={() => execute(() => getAdminEcologicalIngestion(run.id))} className="rounded-full border border-app-border px-2 py-1 text-xs">Run {run.id} · {title(run.workflow_status)}</button>)}</div>}
        {result?.counts && <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs">Preflight: {Object.entries(result.counts).map(([key, value]) => `${title(key)} ${value}`).join(" · ")}</p>}
        {rows.length > 0 && <><div className="mt-4 flex flex-wrap gap-2"><button onClick={() => setSelected(rows.filter(eligible).map((row) => row.id))} className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold">Select eligible</button><button disabled={!selected.length || busy} onClick={() => review("APPROVED")} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Approve selected</button><button disabled={!selected.length || busy} onClick={() => review("UNRESOLVED")} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-bold disabled:opacity-40">Mark unresolved</button><button disabled={!selected.length || busy} onClick={() => execute(() => applyAdminEcologicalIngestion(result.id, selected))} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Apply approved</button></div>
          <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-app-border"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr><th className="p-2">Select</th><th>Source claim</th><th>Reconciliation</th><th>Platform governed status</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-t border-app-border"><td className="p-2"><input type="checkbox" disabled={!eligible(row)} checked={selected.includes(row.id)} onChange={() => setSelected((ids) => ids.includes(row.id) ? ids.filter((id) => id !== row.id) : [...ids, row.id])} /></td><td className="p-2"><strong>{row.scientific_name || "Unresolved taxon"}</strong><br />{row.source_status || "No mapped claim"}</td><td className="p-2">{title(row.taxonomy_result)}<br />{title(row.jurisdiction_result)}</td><td className="p-2">{row.proposed_statuses?.map(title).join(" + ") || "No approved mapping"}<br /><span className="text-app-muted">{title(row.review_status)} · {title(row.apply_status)}</span></td></tr>)}</tbody></table></div></>}
      </div>
    </div>
    {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <p className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">Source registration is not scientific approval. Regional or global list membership is not jurisdiction invasive status.</p>
  </section>;
}
