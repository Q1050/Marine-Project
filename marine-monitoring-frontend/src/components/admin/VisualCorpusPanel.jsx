import { useEffect, useState } from "react";
import { getIdentificationAcquisitionRuns, getIdentificationCorpora, getIdentificationMediaAssets, getIdentificationMediaContent, getIdentificationMediaSources, reviewIdentificationMediaAsset } from "../../services/api";

const human = (value) => String(value || "Unknown").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
function Pill({ children }) { return <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-700">{human(children)}</span>; }

function ControlledThumbnail({ asset }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true; let localUrl = "";
    if (asset.content_url) getIdentificationMediaContent(asset.id).then((blob) => { if (active) { localUrl = URL.createObjectURL(blob); setUrl(localUrl); } }).catch(() => setUrl(""));
    return () => { active = false; if (localUrl) URL.revokeObjectURL(localUrl); };
  }, [asset.content_url, asset.id]);
  return url ? <img src={url} alt={`Governed candidate for ${asset.scientific_name}`} className="h-28 w-full rounded-lg object-cover" /> : <div className="grid h-28 place-items-center rounded-lg bg-slate-100 text-xs text-app-muted">Reference only / unavailable</div>;
}

export default function VisualCorpusPanel() {
  const [data, setData] = useState({ sources: [], runs: [], assets: [], corpora: [] }); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = () => Promise.all([getIdentificationMediaSources(), getIdentificationAcquisitionRuns(), getIdentificationMediaAssets(), getIdentificationCorpora()]).then(([sources, runs, assets, corpora]) => setData({ sources: sources.items || [], runs: runs.items || [], assets: assets.items || [], corpora: corpora.items || [] })).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const review = async (asset, decision) => { const reference = window.prompt(`Governed reason/reference for ${decision.toLowerCase()}:`); if (!reference) return; setBusy(true); try { await reviewIdentificationMediaAsset(asset.id, decision, reference); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <div className="space-y-5">
    {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <section className="grid gap-3 lg:grid-cols-3">
      <Summary title="Governed sources" value={data.sources.length} detail={data.sources.map((item) => `${item.scientific_provider} · ${human(item.lifecycle_state)}`).join("; ") || "No source registered"} />
      <Summary title="Acquisition runs" value={data.runs.length} detail={data.runs.map((item) => `${human(item.workflow_state)} · ${item.manifest?.retrieved ?? 0} retrieved`).join("; ") || "No runs"} />
      <Summary title="Corpora" value={data.corpora.length} detail={data.corpora.map((item) => `${item.corpus_key} ${item.version} · ${human(item.lifecycle_state)}`).join("; ") || "No corpus prepared"} />
    </section>
    <section className="rounded-xl border border-app-border bg-white">
      <div className="border-b border-app-border p-4"><h2 className="font-bold">Identification-media review</h2><p className="mt-1 text-xs text-app-muted">Approval requires governed taxonomy, an eligible item license, valid media, and a distinct duplicate state. Review cannot broaden source rights.</p></div>
      {!data.assets.length ? <p className="p-10 text-center text-sm text-app-muted">No controlled media candidates have been acquired.</p> : <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{data.assets.map((asset) => <article key={asset.id} className="rounded-xl border border-app-border p-3"><ControlledThumbnail asset={asset}/><div className="mt-3 flex items-start justify-between gap-2"><div><strong className="italic">{asset.scientific_name}</strong><p className="text-xs text-app-muted">{asset.source?.provider} · asset {asset.id}</p></div><Pill>{asset.review_state}</Pill></div><dl className="mt-3 grid grid-cols-2 gap-2 text-xs"><Meta name="License" value={asset.license_classification}/><Meta name="Taxonomy" value={asset.taxonomic_linkage}/><Meta name="Quality" value={asset.quality_state}/><Meta name="Duplicate" value={asset.duplicate_state}/><Meta name="Dimensions" value={asset.width_px ? `${asset.width_px}×${asset.height_px}` : "Not stored"}/><Meta name="Context" value={asset.biological_context}/></dl><p className="mt-3 line-clamp-2 text-xs text-app-muted">{asset.attribution_text}</p>{asset.review_state === "READY_FOR_REVIEW" && <div className="mt-3 flex gap-2"><button disabled={busy || !asset.training_eligible && asset.review_state === "APPROVED"} onClick={() => review(asset, "APPROVED")} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Approve</button><button disabled={busy} onClick={() => review(asset, "EXCLUDED")} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-bold text-red-700">Exclude</button></div>}</article>)}</div>}
    </section><p className="rounded-lg bg-slate-50 p-3 text-xs text-app-muted">Identification media does not establish jurisdiction presence, ecological status, invasiveness, suitability, or anomaly evidence.</p>
  </div>;
}
function Summary({ title, value, detail }) { return <article className="rounded-xl border border-app-border bg-white p-4"><p className="text-xs font-bold uppercase tracking-wide text-app-muted">{title}</p><strong className="mt-1 block text-2xl">{value}</strong><p className="mt-2 text-xs text-app-muted">{detail}</p></article>; }
function Meta({ name, value }) { return <div><dt className="font-bold text-app-muted">{name}</dt><dd>{human(value)}</dd></div>; }
