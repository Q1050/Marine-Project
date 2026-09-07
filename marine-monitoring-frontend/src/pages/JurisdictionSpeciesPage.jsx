import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getJurisdictionSpeciesIntelligence, getPublicTaxonMedia, getSpeciesCatalogDetail } from "../services/api";
import { useJurisdiction } from "../geography/JurisdictionContext";
import { SpeciesCard, SpeciesIntelligence } from "./RegionalSpeciesIntelligencePage";
import { indexedTaxaLabel } from "../utils/speciesPresentation";

const number = (value) => Number(value || 0).toLocaleString();

export default function JurisdictionSpeciesPage() {
  const { activeRegion, activeJurisdiction, jurisdiction: metadata } = useJurisdiction();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [catalogDetail, setCatalogDetail] = useState(null);
  const [media, setMedia] = useState(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState(null);
  const selectedId = Number(searchParams.get("taxon"));

  useEffect(() => {
    if (!activeRegion || !activeJurisdiction) return undefined;
    let active = true;
    getJurisdictionSpeciesIntelligence(activeRegion, activeJurisdiction)
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setState("ready");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason?.message || "Jurisdiction species intelligence could not be loaded.");
        setState("error");
      });
    return () => { active = false; };
  }, [activeRegion, activeJurisdiction]);

  const species = useMemo(() => data?.species || [], [data]);
  const selectedSummary = useMemo(
    () => species.find((item) => item.id === selectedId) || species[0] || null,
    [selectedId, species],
  );

  useEffect(() => {
    if (!selectedSummary?.id) return undefined;
    let active = true;
    Promise.all([
      getSpeciesCatalogDetail(selectedSummary.id),
      getPublicTaxonMedia(selectedSummary.id).catch(() => ({ reference_gallery: [] })),
    ]).then(([detail, mediaPayload]) => {
      if (!active) return;
      setCatalogDetail(detail);
      setMedia(mediaPayload);
    }).catch((reason) => {
      if (active) setError(reason?.message || "Species detail could not be loaded.");
    });
    return () => { active = false; };
  }, [selectedSummary?.id]);

  const jurisdictionName = metadata?.name || data?.jurisdiction?.name || "Jurisdiction";
  const selectSpecies = (item) => {
    const next = new URLSearchParams(searchParams);
    next.set("taxon", item.id);
    setSearchParams(next);
    setCatalogDetail(null);
    setMedia(null);
  };
  const perJurisdiction = selectedSummary?.per_jurisdiction?.[0] || {};
  const evidence = perJurisdiction.evidence || selectedSummary?.evidence || {};
  const operationalContext = selectedSummary ? {
    jurisdictionName,
    totalReports: evidence.total || 0,
    verifiedReports: evidence.verified_or_corrected || 0,
    speciesProgram: perJurisdiction.scientific_program ? "Configured" : "Not configured",
    suitability: perJurisdiction.suitability || "Not configured",
    monitoringPriority: perJurisdiction.monitoring_priority || "Not configured",
  } : null;
  const displayedDetail = catalogDetail?.id === selectedSummary?.id ? catalogDetail : null;

  return <div className="species-catalog-page">
    <aside className="species-catalog">
      <div className="species-catalog__header">
        <p className="species-intelligence__eyebrow">{jurisdictionName} workspace</p>
        <div className="species-catalog__heading-row"><h1>Species Catalog</h1><span>{indexedTaxaLabel(data?.count || 0)}</span></div>
        <p>Canonical species with governed {jurisdictionName} evidence or configured scientific programs.</p>
      </div>
      {state === "loading" && <p className="species-catalog__state">Loading jurisdiction species intelligence…</p>}
      {state === "error" && <p className="species-catalog__state" role="alert">{error}</p>}
      {state === "ready" && species.length === 0 && <p className="species-catalog__state">No canonical species are currently configured for this jurisdiction.</p>}
      {state === "ready" && species.length > 0 && <ul className="species-catalog__list">{species.map((item) => {
        const scoped = item.per_jurisdiction?.[0]?.evidence || item.evidence || {};
        return <SpeciesCard key={item.id} item={{ ...item, confirmed_observation_count: scoped.verified_or_corrected || 0 }} selected={selectedSummary?.id === item.id} onSelect={() => selectSpecies(item)} />;
      })}</ul>}
    </aside>
    <main className="species-intelligence-pane">
      {selectedSummary && !displayedDetail && state === "ready" && <div className="species-intelligence-empty"><h2>Loading species intelligence…</h2></div>}
      {displayedDetail && <SpeciesIntelligence species={displayedDetail} media={media} operationalContext={operationalContext} trackingUnavailableLabel="Country map species filtering is not currently available" />}
      {state === "ready" && (data?.unresolved_evidence || []).length > 0 && <section className="rsi-unresolved country-species-unresolved">
        <h3>Unresolved observation evidence</h3>
        <p className="rsi-unresolved__note">These operational names do not resolve to the canonical Country catalog and have not been silently promoted.</p>
        <ul>{data.unresolved_evidence.map((item) => <li key={item.scientific_name}><strong>{item.scientific_name}</strong><span>{number(item.evidence?.total)} report{item.evidence?.total === 1 ? "" : "s"}</span></li>)}</ul>
      </section>}
    </main>
  </div>;
}
