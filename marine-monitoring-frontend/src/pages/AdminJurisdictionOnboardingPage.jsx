import { useCallback, useEffect, useMemo, useState } from "react";
import {
  applyOnboardingBatch, applyOnboardingPreparation, approveOnboardingPreparation,
  getAdminJurisdiction, getAdminRegions, getOnboardingPreparation,
  getRegionOnboardingInventory, prepareRegionJurisdictions,
} from "../services/api";
import { canApplyJurisdiction, canPrepareJurisdiction, scientificStateDescription, selectableJurisdictions } from "../utils/adminOnboarding";

const label = (value) => String(value || "Unavailable").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());

export default function AdminJurisdictionOnboardingPage() {
  const [regions, setRegions] = useState([]);
  const [regionId, setRegionId] = useState("");
  const [inventory, setInventory] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAdminRegions().then((result) => {
      setRegions(result.regions || []);
      setRegionId((current) => current || String(result.regions?.[0]?.id || ""));
    }).catch((error) => setMessage({ type: "error", text: error.message }));
  }, []);

  const loadInventory = useCallback(async () => {
    if (!regionId) return;
    setLoading(true);
    try {
      const result = await getRegionOnboardingInventory(regionId);
      setInventory(result.results || []);
      setSelected(new Set());
    } catch (error) {
      setMessage({ type: "error", text: error.message });
    } finally {
      setLoading(false);
    }
  }, [regionId]);

  useEffect(() => {
    if (!regionId) return undefined;
    let active = true;
    getRegionOnboardingInventory(regionId).then((result) => {
      if (!active) return;
      setInventory(result.results || []); setSelected(new Set()); setLoading(false);
    }).catch((error) => {
      if (!active) return;
      setMessage({ type: "error", text: error.message }); setLoading(false);
    });
    return () => { active = false; };
  }, [regionId]);

  const selectedRows = useMemo(() => inventory.filter((item) => selected.has(item.canonical_identifier)), [inventory, selected]);
  const selectedPrepare = selectedRows.filter(canPrepareJurisdiction);
  const selectedApply = selectedRows.filter(canApplyJurisdiction);

  function toggle(item) {
    if (!canPrepareJurisdiction(item) && !canApplyJurisdiction(item)) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(item.canonical_identifier)) next.delete(item.canonical_identifier); else next.add(item.canonical_identifier);
      return next;
    });
  }

  async function prepareSelected() {
    if (!selectedPrepare.length || busy) return;
    setBusy("prepare"); setMessage(null);
    try {
      const result = await prepareRegionJurisdictions(regionId, selectedPrepare.map((item) => item.canonical_identifier));
      const failures = result.results?.filter((item) => !["READY", "READY_FOR_REVIEW"].includes(item.status)) || [];
      setMessage({ type: failures.length ? "warning" : "success", text: failures.length ? `${failures.length} preparation request(s) require attention.` : `${selectedPrepare.length} jurisdiction preparation(s) are ready for review.` });
      await loadInventory();
    } catch (error) { setMessage({ type: "error", text: error.message }); }
    finally { setBusy(""); }
  }

  async function openItem(item) {
    setBusy(`detail-${item.canonical_identifier}`); setMessage(null);
    try {
      const result = item.preparation_id ? await getOnboardingPreparation(item.preparation_id) : item.jurisdiction_id ? await getAdminJurisdiction(item.jurisdiction_id) : null;
      setDetail(result ? { ...result, inventoryStatus: item.status } : { ...item, inventoryOnly: true });
    } catch (error) { setMessage({ type: "error", text: error.message }); }
    finally { setBusy(""); }
  }

  async function approve() {
    if (!detail?.id || busy) return;
    if (!window.confirm(`Approve geographic onboarding for ${detail.jurisdiction}?\n\nProvider: ${detail.boundary_provider}\nManifest: ${detail.manifest_fingerprint}\n\nThis does not configure species science.`)) return;
    const reference = window.prompt("Enter an approval reference for the audit record:", `admin-console-${new Date().toISOString()}`);
    if (!reference) return;
    setBusy("approve");
    try {
      const result = await approveOnboardingPreparation(detail.id, detail.manifest_fingerprint, reference);
      setDetail(result); setMessage({ type: "success", text: `${result.jurisdiction} approved. Apply remains a separate action.` }); await loadInventory();
    } catch (error) { setMessage({ type: "error", text: error.message }); }
    finally { setBusy(""); }
  }

  async function applyOne() {
    if (!detail?.id || busy || !window.confirm(`Apply the approved geographic onboarding for ${detail.jurisdiction}? This creates or activates its jurisdiction boundary but no scientific state.`)) return;
    setBusy("apply");
    try {
      const result = await applyOnboardingPreparation(detail.id);
      setMessage({ type: "success", text: `${result.jurisdiction}: ${result.status}. Jurisdiction ${result.jurisdiction_id}, boundary ${result.boundary_id}, audit ${result.onboarding_record_id}.` });
      setDetail(null); await loadInventory();
    } catch (error) { setMessage({ type: "error", text: error.message }); }
    finally { setBusy(""); }
  }

  async function applySelected() {
    if (!selectedApply.length || busy || !window.confirm(`Apply ${selectedApply.length} individually approved jurisdiction onboarding operation(s)? Each jurisdiction uses a separate backend transaction.`)) return;
    setBusy("batch");
    try {
      const result = await applyOnboardingBatch(selectedApply.map((item) => item.preparation_id));
      setMessage({ type: "results", results: result.results || [] }); await loadInventory();
    } catch (error) { setMessage({ type: "error", text: error.message }); }
    finally { setBusy(""); }
  }

  const eligible = selectableJurisdictions(inventory);
  return <div className="mx-auto max-w-[1500px]">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="text-xs font-bold uppercase tracking-[.15em] text-teal-700">Platform administration</p><h1 className="mt-1 text-3xl font-bold">Jurisdiction onboarding</h1><p className="mt-2 max-w-3xl text-sm text-app-muted">Controlled geographic onboarding. Geographic configuration never grants scientific readiness or shared regional science.</p></div>
      <label className="text-xs font-bold text-slate-600">Region<select aria-label="Region" value={regionId} onChange={(event) => { setLoading(true); setRegionId(event.target.value); }} className="mt-1 block min-w-56 rounded-lg border border-app-border bg-white px-3 py-2 text-sm font-normal text-app-text">{regions.map((region) => <option key={region.id} value={region.id}>{region.name}</option>)}</select></label>
    </header>
    {message && <Feedback message={message} />}
    <div className="mt-5 flex flex-wrap items-center gap-2 rounded-xl border border-app-border bg-white p-3">
      <button disabled={!eligible.length || busy} onClick={() => setSelected(new Set(eligible.map((item) => item.canonical_identifier)))} className="rounded-lg border border-app-border px-3 py-2 text-sm font-bold disabled:opacity-40">Select eligible</button>
      <button disabled={!selectedPrepare.length || busy} onClick={prepareSelected} className="rounded-lg bg-teal-700 px-3 py-2 text-sm font-bold text-white disabled:opacity-40">{busy === "prepare" ? "Preparing…" : `Prepare selected${selectedPrepare.length ? ` (${selectedPrepare.length})` : ""}`}</button>
      <button disabled={!selectedApply.length || busy} onClick={applySelected} className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-bold text-white disabled:opacity-40">{busy === "batch" ? "Applying…" : `Apply selected${selectedApply.length ? ` (${selectedApply.length})` : ""}`}</button>
      <span className="ml-auto text-xs text-app-muted">Blocked and review-required entries cannot be selected.</span>
    </div>
    <section className="mt-4 overflow-hidden rounded-xl border border-app-border bg-white">
      {loading ? <div className="p-12 text-center text-sm text-app-muted">Loading governed inventory…</div> : <div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-left text-sm"><thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="w-10 p-3"></th><th className="p-3">Jurisdiction</th><th className="p-3">Identity</th><th className="p-3">Type</th><th className="p-3">Geographic / workflow state</th><th className="p-3">Scientific state</th><th className="p-3">Action</th></tr></thead><tbody className="divide-y divide-app-border">{inventory.map((item) => { const selectable = canPrepareJurisdiction(item) || canApplyJurisdiction(item); return <tr key={`${item.canonical_identifier_scheme}-${item.canonical_identifier}`} className="hover:bg-slate-50/70"><td className="p-3"><input aria-label={`Select ${item.jurisdiction}`} type="checkbox" disabled={!selectable || busy} checked={selected.has(item.canonical_identifier)} onChange={() => toggle(item)} /></td><td className="p-3 font-semibold">{item.jurisdiction}<p className="mt-1 text-xs font-normal text-app-muted">{item.reason ? label(item.reason) : "Governed regional inventory"}</p></td><td className="p-3"><span className="font-mono text-xs">{item.canonical_identifier}</span><p className="text-[11px] text-app-muted">{item.canonical_identifier_scheme}</p></td><td className="p-3 text-xs">{label(item.jurisdiction_type)}</td><td className="p-3"><StateBadge value={item.status} /></td><td className="p-3"><StateBadge value={item.scientific_state || "SCIENTIFICALLY_EMPTY"} science /></td><td className="p-3"><button disabled={busy} onClick={() => openItem(item)} className="font-bold text-teal-700 disabled:opacity-40">{item.preparation_id ? "Review" : item.jurisdiction_id ? "View state" : "View reason"}</button></td></tr>; })}</tbody></table></div>}
    </section>
    {detail && <DetailDrawer detail={detail} busy={busy} onClose={() => setDetail(null)} onApprove={approve} onApply={applyOne} />}
  </div>;
}

function StateBadge({ value, science = false }) {
  const tone = value === "APPROVED" || value === "READY" || value === "READY_FOR_REVIEW" || value === "CONFIGURED" ? "bg-teal-50 text-teal-700" : value === "ALREADY_ONBOARDED" || value === "APPLIED" ? "bg-blue-50 text-blue-700" : value === "BLOCKED" || value === "CONFLICT" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800";
  return <div><span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-bold ${tone}`}>{label(value)}</span>{science && value === "SCIENTIFICALLY_EMPTY" && <p className="mt-1 text-[11px] text-app-muted">{scientificStateDescription(value)}</p>}</div>;
}

function DetailDrawer({ detail, busy, onClose, onApprove, onApply }) {
  const preparation = Boolean(detail.manifest_fingerprint);
  return <div className="fixed inset-0 z-[1800] flex justify-end bg-slate-950/35"><aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wide text-teal-700">{preparation ? "Onboarding preparation" : "Jurisdiction state"}</p><h2 className="mt-1 text-2xl font-bold">{detail.jurisdiction || detail.name}</h2></div><button onClick={onClose} className="rounded-lg border border-app-border px-3 py-2" aria-label="Close">×</button></div>
    {preparation ? <><DetailSection title="Identity" rows={[["Identifier", `${detail.canonical_identifier_scheme} · ${detail.canonical_identifier}`], ["Jurisdiction type", label(detail.jurisdiction_type)], ["Region ID", detail.region_id]]} /><DetailSection title="Boundary" rows={[["Provider", detail.boundary_provider], ["Provider version", detail.boundary_provider_version], ["Provider boundary ID", detail.provider_boundary_identifier], ["Boundary type", label(detail.boundary_type)], ["CRS", detail.crs], ["Geometry validation", detail.geometry_validation_state], ["Source SHA-256", detail.boundary_source_sha256], ["Geometry SHA-256", detail.geometry_sha256]]} /><DetailSection title="Manifest" rows={[["Version", detail.manifest_version], ["Fingerprint", detail.manifest_fingerprint], ["Workflow", label(detail.workflow_state)]]} /><section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><h3 className="text-sm font-bold text-amber-950">Scientific safety</h3><p className="mt-1 text-xs text-amber-900">This operation configures geography only. Species programs, ecological status, datasets, models, occurrences, and anomaly evidence remain empty until separately reviewed scientific workflows act.</p></section><div className="mt-6 flex justify-end gap-2">{detail.workflow_state === "READY_FOR_REVIEW" && <button disabled={busy} onClick={onApprove} className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40">{busy === "approve" ? "Approving…" : "Approve"}</button>}{detail.workflow_state === "APPROVED" && <button disabled={busy} onClick={onApply} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40">{busy === "apply" ? "Applying…" : "Apply onboarding"}</button>}</div></> : <><DetailSection title="Current geographic state" rows={[["Region", detail.region?.name], ["Country code", detail.country_code], ["Operational boundary", detail.operational_boundary_configured ? "Configured" : "Not configured"], ["Active status", detail.status]]} /><section className="mt-5"><h3 className="text-sm font-bold">Onboarding history</h3>{detail.onboarding_history?.length ? detail.onboarding_history.map((record) => <div key={record.id} className="mt-2 rounded-lg border border-app-border p-3 text-xs"><strong>Audit #{record.id} · {label(record.action_performed)}</strong><p className="mt-1 break-all text-app-muted">{record.manifest_fingerprint}</p></div>) : <p className="mt-2 text-sm text-app-muted">No workflow audit record is available for legacy onboarding.</p>}</section></>}
  </aside></div>;
}

function DetailSection({ title, rows }) { return <section className="mt-5 rounded-xl border border-app-border p-4"><h3 className="text-sm font-bold">{title}</h3><dl className="mt-3 grid gap-3 sm:grid-cols-2">{rows.map(([name, value]) => <div key={name}><dt className="text-[10px] font-bold uppercase tracking-wide text-app-muted">{name}</dt><dd className="mt-1 break-all text-xs">{value || "Unavailable"}</dd></div>)}</dl></section>; }
function Feedback({ message }) { if (message.type === "results") return <div className="mt-4 rounded-xl border border-app-border bg-white p-4"><strong className="text-sm">Batch results</strong>{message.results.map((result, index) => <p key={`${result.jurisdiction}-${index}`} className="mt-2 text-sm"><StateBadge value={result.status} /> <span className="ml-2">{result.jurisdiction}{result.reason ? ` — ${result.reason}` : ""}</span></p>)}</div>; const tone = message.type === "error" ? "border-red-200 bg-red-50 text-red-800" : message.type === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-teal-200 bg-teal-50 text-teal-800"; return <div role="status" className={`mt-4 rounded-xl border p-3 text-sm ${tone}`}>{message.text}</div>; }
