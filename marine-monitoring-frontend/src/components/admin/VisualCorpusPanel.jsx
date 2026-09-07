import { useEffect, useState } from "react";
import {
  acquireCommonsTaxonomyEvidence,
  getIdentificationAcquisitionRuns,
  getIdentificationCorpora,
  getIdentificationCorpusPlans,
  getIdentificationMediaAssets,
  getIdentificationMediaContent,
  getIdentificationMediaSources,
  resolveIdentificationMediaTaxonomy,
  reviewIdentificationMediaAsset,
} from "../../services/api";
import {
  filterMediaAssets,
  isMediaReviewable,
  normalizeResolutionReason,
  TAXONOMY_RESOLUTION_ACTIONS,
  nextTaxonomySelectionAfterResolution,
  nextSelectionAfterDisposition,
  reviewNavigationAssets,
  taxonomyNavigationAssets,
} from "./visualCorpusReviewState";

const human = (value) =>
  String(value || "Unknown")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
function Pill({ children }) {
  return (
    <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-700">
      {human(children)}
    </span>
  );
}

function ControlledThumbnail({ asset, large = false }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let active = true;
    let localUrl = "";
    if (asset.content_url)
      getIdentificationMediaContent(asset.id)
        .then((blob) => {
          if (active) {
            localUrl = URL.createObjectURL(blob);
            setUrl(localUrl);
          }
        })
        .catch(() => setUrl(""));
    return () => {
      active = false;
      if (localUrl) URL.revokeObjectURL(localUrl);
    };
  }, [asset.content_url, asset.id]);
  const size = large ? "h-[min(56vh,560px)]" : "h-28";
  return url ? (
    <img
      src={url}
      alt={`Governed candidate for ${asset.scientific_name}`}
      className={`${size} w-full rounded-lg bg-slate-950 object-contain`}
    />
  ) : (
    <div
      className={`grid ${size} place-items-center rounded-lg bg-slate-100 text-xs text-app-muted`}
    >
      Reference only / unavailable
    </div>
  );
}

export default function VisualCorpusPanel() {
  const [data, setData] = useState({
    sources: [],
    runs: [],
    assets: [],
    corpora: [],
    plans: [],
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [filter, setFilter] = useState("REVIEWABLE");
  const fetchData = async () => {
    const [sources, runs, assets, corpora, plans] = await Promise.all([
      getIdentificationMediaSources(),
      getIdentificationAcquisitionRuns(),
      getIdentificationMediaAssets(),
      getIdentificationCorpora(),
      getIdentificationCorpusPlans(),
    ]);
    return {
      sources: sources.items || [],
      runs: runs.items || [],
      assets: assets.items || [],
      corpora: corpora.items || [],
      plans: plans.items || [],
    };
  };
  useEffect(() => {
    let active = true;
    Promise.all([
      getIdentificationMediaSources(),
      getIdentificationAcquisitionRuns(),
      getIdentificationMediaAssets(),
      getIdentificationCorpora(),
      getIdentificationCorpusPlans(),
    ])
      .then(([sources, runs, assets, corpora, plans]) => {
        if (active)
          setData({
            sources: sources.items || [],
            runs: runs.items || [],
            assets: assets.items || [],
            corpora: corpora.items || [],
            plans: plans.items || [],
          });
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  const review = async (asset, decision) => {
    const reference = window.prompt(
      `Governed reason/reference for ${decision.toLowerCase()}:`,
    );
    if (!reference) return;
    const beforeAssets = data.assets;
    setBusy(true);
    setError("");
    try {
      const persisted = await reviewIdentificationMediaAsset(
        asset.id,
        decision,
        reference,
      );
      setData((current) => ({
        ...current,
        assets: current.assets.map((item) =>
          item.id === persisted.id ? persisted : item,
        ),
      }));
      const refreshed = await fetchData();
      setData(refreshed);
      setSelectedId((current) =>
        nextSelectionAfterDisposition({
          selectedId: current,
          reviewedId: asset.id,
          beforeAssets,
          afterAssets: refreshed.assets,
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const acquireTaxonomyEvidence = async (asset) => {
    setBusy(true);
    setError("");
    try {
      await acquireCommonsTaxonomyEvidence(asset.id);
      setData(await fetchData());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const resolveTaxonomy = async (asset, resolutionState) => {
    const reason = window.prompt(
      `Scientific reason for ${human(resolutionState)}:`,
    );
    const normalizedReason = normalizeResolutionReason(reason);
    if (!normalizedReason) return;
    const evidenceIds = (asset.taxonomy_history?.evidence || []).map(
      (item) => item.id,
    );
    const beforeAssets = data.assets;
    setBusy(true);
    setError("");
    try {
      const result = await resolveIdentificationMediaTaxonomy(
        asset.id,
        resolutionState,
        normalizedReason,
        evidenceIds,
      );
      setData((current) => ({
        ...current,
        assets: current.assets.map((item) =>
          item.id === asset.id ? result.asset : item,
        ),
      }));
      const refreshed = await fetchData();
      setData(refreshed);
      setSelectedId(
        nextTaxonomySelectionAfterResolution({
          reviewedId: asset.id,
          beforeAssets,
          afterAssets: refreshed.assets,
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const secondaryActions = [
    ["NEEDS_REVIEW", "Needs review"],
    ["TAXONOMY_REVIEW_REQUIRED", "Taxonomy review"],
    ["DUPLICATE", "Duplicate"],
  ];
  const visibleAssets = filterMediaAssets(data.assets, filter);
  const selected = data.assets.find((item) => item.id === selectedId);
  const navigationAssets =
    filter === "TAXONOMY_REVIEW"
      ? taxonomyNavigationAssets(data.assets)
      : reviewNavigationAssets(data.assets, selectedId);
  const taxonomyReviewCount = filterMediaAssets(
    data.assets,
    "TAXONOMY_REVIEW",
  ).length;
  const selectedIndex = navigationAssets.findIndex(
    (item) => item.id === selectedId,
  );
  useEffect(() => {
    if (!selected) return undefined;
    const handler = (event) => {
      if (
        event.key === "ArrowRight" &&
        selectedIndex < navigationAssets.length - 1
      )
        setSelectedId(navigationAssets[selectedIndex + 1].id);
      if (event.key === "ArrowLeft" && selectedIndex > 0)
        setSelectedId(navigationAssets[selectedIndex - 1].id);
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selected, selectedIndex, navigationAssets]);
  return (
    <div className="space-y-5">
      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      <section className="grid gap-3 lg:grid-cols-4">
        <Summary
          title="Corpus plans"
          value={data.plans.length}
          detail={
            data.plans
              .map(
                (item) =>
                  `${item.plan_key} ${item.version} · ${human(item.lifecycle_state)}`,
              )
              .join("; ") || "No plan prepared"
          }
        />
        <Summary
          title="Governed sources"
          value={data.sources.length}
          detail={
            data.sources
              .map(
                (item) =>
                  `${item.scientific_provider} · ${human(item.lifecycle_state)}`,
              )
              .join("; ") || "No source registered"
          }
        />
        <Summary
          title="Acquisition runs"
          value={data.runs.length}
          detail={
            data.runs
              .map(
                (item) =>
                  `${human(item.workflow_state)} · ${item.manifest?.retrieved ?? 0} retrieved`,
              )
              .join("; ") || "No runs"
          }
        />
        <Summary
          title="Corpora"
          value={data.corpora.length}
          detail={
            data.corpora
              .map(
                (item) =>
                  `${item.corpus_key} ${item.version} · ${human(item.lifecycle_state)}`,
              )
              .join("; ") || "No corpus prepared"
          }
        />
      </section>
      <section className="rounded-xl border border-app-border bg-white">
        <div className="border-b border-app-border p-4">
          <h2 className="font-bold">Identification-media review</h2>
          <p className="mt-1 text-xs text-app-muted">
            Approval requires governed taxonomy, an eligible item license, valid
            media, and a distinct duplicate state. Review cannot broaden source
            rights.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {[
              ["REVIEWABLE", "Pending review"],
              ["TAXONOMY_REVIEW", `Taxonomy review (${taxonomyReviewCount})`],
              ["ALL", "All assets"],
              ["APPROVED", "Approved"],
              ["EXCLUDED", "Excluded"],
            ].map(([value, label]) => (
              <button
                key={value}
                onClick={() => {
                  setFilter(value);
                  setSelectedId(null);
                }}
                className={`rounded-full border px-3 py-1 text-xs font-bold ${filter === value ? "border-teal-700 bg-teal-50 text-teal-800" : "border-app-border text-slate-600"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {selected && (
          <FocusedReview
            asset={selected}
            busy={busy}
            review={review}
            acquireTaxonomyEvidence={acquireTaxonomyEvidence}
            resolveTaxonomy={resolveTaxonomy}
            actions={secondaryActions}
            previous={() =>
              selectedIndex > 0 &&
              setSelectedId(navigationAssets[selectedIndex - 1].id)
            }
            next={() =>
              selectedIndex < navigationAssets.length - 1 &&
              setSelectedId(navigationAssets[selectedIndex + 1].id)
            }
            close={() => setSelectedId(null)}
          />
        )}
        {!visibleAssets.length ? (
          <p className="p-10 text-center text-sm text-app-muted">
            No media assets match this review filter.
          </p>
        ) : (
          <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
            {visibleAssets.map((asset) => (
              <article
                key={asset.id}
                className="rounded-xl border border-app-border p-3"
              >
                <ControlledThumbnail asset={asset} />
                <div className="mt-3 flex items-start justify-between gap-2">
                  <div>
                    <strong className="italic">{asset.scientific_name}</strong>
                    <p className="text-xs text-app-muted">
                      {asset.source?.provider} · asset {asset.id}
                    </p>
                  </div>
                  <Pill>{asset.review_state}</Pill>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <Meta name="License" value={asset.license_classification} />
                  <Meta name="Taxonomy" value={asset.taxonomic_linkage} />
                  <Meta name="Quality" value={asset.quality_state} />
                  <Meta name="Duplicate" value={asset.duplicate_state} />
                  <Meta
                    name="Dimensions"
                    value={
                      asset.width_px
                        ? `${asset.width_px}×${asset.height_px}`
                        : "Not stored"
                    }
                  />
                  <Meta name="Context" value={asset.biological_context} />
                </dl>
                <p className="mt-3 line-clamp-2 text-xs text-app-muted">
                  {asset.attribution_text}
                </p>
                <button
                  onClick={() => setSelectedId(asset.id)}
                  className="mt-3 w-full rounded-lg border border-teal-700 px-3 py-2 text-xs font-bold text-teal-800"
                >
                  {isMediaReviewable(asset)
                    ? "Review details"
                    : "Inspect details"}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
      <p className="rounded-lg bg-slate-50 p-3 text-xs text-app-muted">
        Identification media does not establish jurisdiction presence,
        ecological status, invasiveness, suitability, or anomaly evidence.
      </p>
    </div>
  );
}
function FocusedReview({
  asset,
  busy,
  review,
  acquireTaxonomyEvidence,
  resolveTaxonomy,
  actions,
  previous,
  next,
  close,
}) {
  return (
    <div className="border-b border-app-border bg-slate-50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="font-bold">Focused scientific review</h3>
          <p className="text-xs text-app-muted">
            Arrow keys navigate · Escape closes
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={previous}
            className="rounded border px-3 py-1 text-xs"
          >
            Previous
          </button>
          <button onClick={next} className="rounded border px-3 py-1 text-xs">
            Next
          </button>
          <button onClick={close} className="rounded border px-3 py-1 text-xs">
            Close
          </button>
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
        <ControlledThumbnail asset={asset} large />
        <div className="space-y-4">
          <div>
            <strong className="text-lg italic">{asset.scientific_name}</strong>
            <p className="text-sm text-app-muted">
              Governed target · {asset.source?.provider}
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Meta
              name="Provider taxonomy"
              value={asset.provider_taxon_evidence || asset.taxonomic_linkage}
            />
            <Meta name="License" value={asset.license_expression} />
            <Meta
              name="Dimensions"
              value={
                asset.width_px
                  ? `${asset.width_px}×${asset.height_px}`
                  : "Not acquired"
              }
            />
            <Meta name="Technical quality" value={asset.quality_state} />
            <Meta name="SHA-256" value={asset.sha256_status} />
            <Meta name="Duplicate context" value={asset.duplicate_state} />
            <Meta name="Locality" value={asset.locality} />
            <Meta name="Event date" value={asset.event_date} />
          </dl>
          <p className="rounded-lg bg-white p-3 text-xs">
            <b>Attribution:</b> {asset.attribution_text}
          </p>
          {asset.taxonomic_limitations && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              {asset.taxonomic_limitations}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <a
              href={asset.source_reference}
              target="_blank"
              rel="noreferrer"
              className="rounded border px-3 py-2 text-xs font-bold text-teal-800"
            >
              Provider page
            </a>
            {asset.license_url && (
              <a
                href={asset.license_url}
                target="_blank"
                rel="noreferrer"
                className="rounded border px-3 py-2 text-xs font-bold text-teal-800"
              >
                License
              </a>
            )}
          </div>
          {(asset.review_state === "TAXONOMY_REVIEW_REQUIRED" ||
            (asset.taxonomy_history?.evidence || []).length > 0 ||
            (asset.taxonomy_history?.resolutions || []).length > 0) && (
            <TaxonomyEvidenceReview
              asset={asset}
              busy={busy}
              acquire={acquireTaxonomyEvidence}
              resolve={resolveTaxonomy}
            />
          )}
          {["READY_FOR_REVIEW", "REVIEW_REQUIRED"].includes(
            asset.review_state,
          ) && (
            <div className="flex flex-wrap gap-2">
              <button
                disabled={busy}
                onClick={() => review(asset, "APPROVED")}
                className="rounded bg-teal-700 px-3 py-2 text-xs font-bold text-white"
              >
                Approve
              </button>
              <button
                disabled={busy}
                onClick={() => review(asset, "EXCLUDED")}
                className="rounded border border-red-300 px-3 py-2 text-xs font-bold text-red-700"
              >
                Exclude
              </button>
              {actions.map(([decision, label]) => (
                <button
                  key={decision}
                  disabled={busy}
                  onClick={() => review(asset, decision)}
                  className="rounded border px-3 py-2 text-xs font-bold"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
function TaxonomyEvidenceReview({ asset, busy, acquire, resolve }) {
  const evidence = asset.taxonomy_history?.evidence || [];
  const resolutions = asset.taxonomy_history?.resolutions || [];
  const unresolved =
    asset.review_state === "TAXONOMY_REVIEW_REQUIRED" &&
    resolutions.length === 0;
  return (
    <section className="rounded-lg border border-amber-200 bg-white p-3 text-xs">
      <h4 className="font-bold">Taxonomy evidence</h4>
      <p className="mt-1 text-app-muted">
        Visual resemblance and provider search context are not governed species
        identification.
      </p>
      {evidence.map((item) => (
        <div key={item.id} className="mt-2 border-t border-slate-200 pt-2">
          <b>{human(item.provider)}</b> · {human(item.reconciliation_state)}
          <p>{item.scientific_name || "No species-level name supplied"}</p>
          <p className="text-app-muted">
            {human(item.evidence_type)} · retrieved {String(item.retrieved_at)}
          </p>
          <a
            className="text-teal-800 underline"
            href={item.reference}
            target="_blank"
            rel="noreferrer"
          >
            Evidence source
          </a>
          {item.metadata?.inaturalist_photo_reference && (
            <a
              className="text-teal-800 underline"
              href={item.metadata.inaturalist_photo_reference}
              target="_blank"
              rel="noreferrer"
            >
              Linked iNaturalist photo provenance
            </a>
          )}
        </div>
      ))}
      {resolutions.map((item) => (
        <div
          key={`resolution-${item.id}`}
          className="mt-3 rounded border border-teal-200 bg-teal-50 p-2"
        >
          <b>{human(item.resolution_state)}</b>
          <p>{item.reviewer_reason}</p>
          <p className="text-app-muted">Resolved {String(item.created_at)}</p>
        </div>
      ))}
      <div className="mt-3 flex flex-wrap gap-2">
        {unresolved && (
          <button
            disabled={busy}
            onClick={() => acquire(asset)}
            className="rounded border px-3 py-2 font-bold text-teal-800"
          >
            Refresh provider evidence
          </button>
        )}
        {unresolved &&
          evidence.length > 0 &&
          TAXONOMY_RESOLUTION_ACTIONS.map(([state, label]) => (
            <button
              key={state}
              disabled={busy}
              onClick={() => resolve(asset, state)}
              className={
                state === "CONFIRMED_TARGET_TAXON"
                  ? "rounded bg-teal-700 px-3 py-2 font-bold text-white"
                  : "rounded border px-3 py-2 font-bold"
              }
            >
              {label}
            </button>
          ))}
      </div>
    </section>
  );
}
function Summary({ title, value, detail }) {
  return (
    <article className="rounded-xl border border-app-border bg-white p-4">
      <p className="text-xs font-bold uppercase tracking-wide text-app-muted">
        {title}
      </p>
      <strong className="mt-1 block text-2xl">{value}</strong>
      <p className="mt-2 text-xs text-app-muted">{detail}</p>
    </article>
  );
}
function Meta({ name, value }) {
  return (
    <div>
      <dt className="font-bold text-app-muted">{name}</dt>
      <dd>{human(value)}</dd>
    </div>
  );
}
