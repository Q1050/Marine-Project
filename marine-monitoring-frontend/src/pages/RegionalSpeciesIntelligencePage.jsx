import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getImageUrl, getPublicTaxonMedia, getRegionSpeciesTracking, getSpeciesCatalog, getSpeciesCatalogDetail } from "../services/api";
import { formatTaxonomyLineage, indexedTaxaLabel, safeDisplayText } from "../utils/speciesPresentation";

const number = (value) => Number(value || 0).toLocaleString();

function taxonIdentifier(item) {
  const scheme = safeDisplayText(item.authoritative_identifier_scheme);
  const identifier = safeDisplayText(item.authoritative_identifier);
  if (scheme && identifier) return `${scheme}: ${identifier}`;
  if (Number.isFinite(Number(item.aphia_id))) return `WoRMS AphiaID: ${item.aphia_id}`;
  const catalogId = safeDisplayText(item.id);
  return catalogId ? `Catalog ID: ${catalogId}` : "Taxonomic identifier unavailable";
}

export function SpeciesCard({ item, selected, onSelect }) {
  return <li><button type="button" className={`catalog-card ${selected ? "catalog-card--selected" : ""}`} onClick={onSelect}>
    <span className="catalog-card__name">{safeDisplayText(item.common_name, "Common name unavailable")}</span>
    <em>{safeDisplayText(item.scientific_name, "Scientific name unavailable")}</em>
    <span className="catalog-card__meta">
      <span>{safeDisplayText(item.taxonomic_rank, "Rank unavailable")}</span>
      <span>{number(item.confirmed_observation_count)} confirmed observation{item.confirmed_observation_count === 1 ? "" : "s"}</span>
    </span>
    <span className="catalog-card__identifier">{taxonIdentifier(item)}</span>
  </button></li>;
}

function ReturnContext({ params }) {
  const observation = params.get("observation");
  const lat = Number(params.get("returnLat"));
  const lng = Number(params.get("returnLng"));
  const zoom = Number(params.get("returnZoom"));
  if (!observation || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const query = new URLSearchParams({ lat, lng, z: Number.isFinite(zoom) ? zoom : 7, observation });
  if (params.get("taxon")) query.set("trackTaxon", params.get("taxon"));
  return <div className="species-return-context"><span className="species-return-context__icon">⌖</span><div><strong>Linked from field observation #{observation}</strong><span>{lat.toFixed(4)}, {lng.toFixed(4)}</span></div><a href={`/region/caribbean?${query}`}>Return to Map Marker ←</a></div>;
}

function ReferenceImagery({ media }) {
  const images = media?.reference_gallery || [];
  if (!images.length) return null;
  return <section className="species-intelligence__section species-reference-imagery">
    <div><p className="species-intelligence__eyebrow">Visual corpus</p><h2>Reference imagery</h2></div>
    <p className="species-reference-imagery__note">Human-approved taxonomic reference assets with public-compatible licenses. Imagery is identification support, not occurrence evidence.</p>
    <ul>{images.map((item) => {
      const lifeStage = safeDisplayText(item.life_stage);
      return <li key={item.id}><figure>
        <a href={safeDisplayText(item.source_reference) || undefined} target="_blank" rel="noreferrer"><img src={getImageUrl(item.url)} alt={`Reference image of ${safeDisplayText(item.scientific_name, "the selected species")}`} loading="lazy" /></a>
        <figcaption>{lifeStage && <span className="species-reference-imagery__stage">{lifeStage}</span>}<span>{safeDisplayText(item.attribution_text, safeDisplayText(item.creator, "Attribution available from source"))}</span><span>{safeDisplayText(item.source_provider, "Approved visual corpus")} · {safeDisplayText(item.license, "License metadata unavailable")}</span>{safeDisplayText(item.license_url) && <a href={item.license_url} target="_blank" rel="noreferrer">License</a>}</figcaption>
      </figure></li>;
    })}</ul>
  </section>;
}

export function SpeciesIntelligence({ species, tracking = [], media, operationalContext = null, trackingUnavailableLabel = "No confirmed tracked observations" }) {
  const navigate = useNavigate();
  const trackingItem = tracking.find((item) => item.taxon.id === species.id);
  const lineageItems = formatTaxonomyLineage(species.taxonomy);
  const sourceScheme = safeDisplayText(species.authoritative_identifier_scheme);
  const sourceIdentifier = safeDisplayText(species.authoritative_identifier);
  const sources = [
    sourceScheme && sourceIdentifier ? { label: sourceScheme, value: sourceIdentifier } : null,
    Number.isFinite(Number(species.aphia_id)) ? { label: "WoRMS AphiaID", value: String(species.aphia_id) } : null,
  ].filter(Boolean);
  const commonName = safeDisplayText(species.common_name, "Common name unavailable");
  const scientificName = safeDisplayText(species.scientific_name, "Scientific name unavailable");
  const authorship = safeDisplayText(species.authorship);

  return <article className="species-intelligence">
    <section className="species-intelligence__hero">
      {lineageItems.length > 0 && <p className="species-lineage">{lineageItems.join(" › ")}</p>}
      <div className="species-intelligence__title-row"><div>
        <p className="species-intelligence__eyebrow">Species intelligence</p>
        <div className="species-intelligence__names"><h1>{commonName}</h1><em>{scientificName}</em></div>
        {authorship && <span className="species-authorship">{authorship}</span>}
      </div>{trackingItem ? <button type="button" className="species-tracking-action" onClick={() => navigate(`/region/caribbean?trackTaxon=${species.id}`)}>View on Tracking Map</button> : <span className="species-tracking-unavailable">{trackingUnavailableLabel}</span>}</div>
      <div className="species-badges"><span>Taxonomic status: {safeDisplayText(species.accepted_name_status, "Unavailable")}</span><span>Ecological status: Not available</span>{operationalContext ? <span>Monitoring priority: {operationalContext.monitoringPriority}</span> : <span>Monitoring priority: Not available</span>}</div>
    </section>

    <section className="species-intelligence__section"><div><p className="species-intelligence__eyebrow">Accepted taxonomy</p><h2>Canonical record</h2></div><dl className="species-facts"><div><dt>Scientific name</dt><dd><em>{scientificName}</em></dd></div><div><dt>Taxonomic rank</dt><dd>{safeDisplayText(species.taxonomic_rank, "Not available")}</dd></div><div><dt>Taxonomic identifier</dt><dd>{taxonIdentifier(species)}</dd></div><div><dt>Name status</dt><dd>{safeDisplayText(species.accepted_name_status, "Not available")}</dd></div></dl><p className="species-missing-note">A governed public description and diagnostic reference are not yet available for this taxon.</p></section>
    <ReferenceImagery media={media} />
    <section className="species-intelligence__section species-intelligence__evidence"><div><p className="species-intelligence__eyebrow">Observation context</p><h2>Confirmed field evidence</h2></div><strong className="species-evidence-total">{number(operationalContext?.verifiedReports ?? species.confirmed_observation_count)}</strong><p>Expert-confirmed or expert-corrected platform observation{(operationalContext?.verifiedReports ?? species.confirmed_observation_count) === 1 ? "" : "s"}{operationalContext?.jurisdictionName ? ` in ${operationalContext.jurisdictionName}` : ""}.</p>{operationalContext ? <p className="species-missing-note">{number(operationalContext.totalReports)} total platform report{operationalContext.totalReports === 1 ? "" : "s"} in this jurisdiction; unresolved identity evidence is excluded from this canonical count.</p> : trackingItem?.observations?.length > 0 ? <ul className="species-jurisdiction-list">{[...new Set(trackingItem.observations.map((item) => safeDisplayText(item.jurisdiction?.name)).filter(Boolean))].map((name) => <li key={name}>{name}</li>)}</ul> : <p className="species-missing-note">No qualifying regional location evidence is available.</p>}</section>
    <section className="species-intelligence__section"><div><p className="species-intelligence__eyebrow">Scientific capabilities</p><h2>Suitability and priority</h2></div>{operationalContext ? <dl className="species-facts"><div><dt>Species program</dt><dd>{operationalContext.speciesProgram}</dd></div><div><dt>Habitat suitability</dt><dd>{operationalContext.suitability}</dd></div><div><dt>Monitoring priority</dt><dd>{operationalContext.monitoringPriority}</dd></div><div><dt>Jurisdiction</dt><dd>{operationalContext.jurisdictionName}</dd></div></dl> : <p className="species-missing-note">No jurisdiction-specific suitability or monitoring-priority deployment is exposed by this catalog record.</p>}</section>
    <section className="species-intelligence__section"><div><p className="species-intelligence__eyebrow">Sources</p><h2>Taxonomic references</h2></div>{sources.length ? <ul className="species-source-list">{sources.map((source) => <li key={`${source.label}-${source.value}`}><strong>{source.label}</strong><span>{source.value}</span></li>)}</ul> : <p className="species-missing-note">No public authoritative source identifier is available.</p>}</section>
  </article>;
}

export default function RegionalSpeciesIntelligencePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [catalog, setCatalog] = useState({ count: 0, items: [] });
  const [tracking, setTracking] = useState([]);
  const [selected, setSelected] = useState(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState(null);
  const [mediaByTaxon, setMediaByTaxon] = useState({});
  const selectedId = Number(searchParams.get("taxon"));
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250); return () => window.clearTimeout(timer); }, [query]);
  useEffect(() => { let active = true; Promise.all([getSpeciesCatalog({ search: debouncedQuery, withObservations: filter === "observed", pageSize: 100 }), getRegionSpeciesTracking("caribbean")]).then(([catalogData, trackingData]) => { if (!active) return; setCatalog(catalogData); setTracking(trackingData.items || []); setState("ready"); }).catch((reason) => { if (!active) return; setError(reason?.message || "Species catalog could not be loaded."); setState("error"); }); return () => { active = false; }; }, [debouncedQuery, filter]);
  useEffect(() => { let active = true; if (selectedId > 0) getSpeciesCatalogDetail(selectedId).then((item) => active && setSelected(item)).catch(() => active && setSelected(null)); return () => { active = false; }; }, [selectedId]);
  const observedCount = useMemo(() => tracking.length, [tracking]);
  const displayedSelected = selectedId > 0 ? selected : catalog.items[0] || null;
  useEffect(() => { let active = true; const taxonId = displayedSelected?.id; if (taxonId && !mediaByTaxon[taxonId]) getPublicTaxonMedia(taxonId).then((payload) => { if (active) setMediaByTaxon((current) => ({ ...current, [taxonId]: payload })); }).catch(() => { if (active) setMediaByTaxon((current) => ({ ...current, [taxonId]: { reference_gallery: [] } })); }); return () => { active = false; }; }, [displayedSelected?.id, mediaByTaxon]);
  const selectSpecies = (item) => { const next = new URLSearchParams(searchParams); next.set("taxon", item.id); setSearchParams(next); setSelected(item); };
  return <div className="species-catalog-page">
    <aside className="species-catalog"><div className="species-catalog__header"><div className="species-catalog__heading-row"><h1>Species Catalog</h1><span>{indexedTaxaLabel(catalog.count)}</span></div><label><span className="sr-only">Search species</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Common name, scientific name, or taxon ID" /></label><div className="species-catalog__filters" role="group" aria-label="Catalog filters"><button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All Species</button><button type="button" className={filter === "observed" ? "active" : ""} onClick={() => setFilter("observed")}>With Observations ({observedCount})</button></div><p>Canonical taxonomy catalog · independent of regional or ecological status</p></div>
      {state === "loading" && <p className="species-catalog__state">Loading catalog…</p>}{state === "error" && <p className="species-catalog__state" role="alert">{error}</p>}{state === "ready" && <ul className="species-catalog__list">{catalog.items.map((item) => <SpeciesCard key={item.id} item={item} selected={displayedSelected?.id === item.id} onSelect={() => selectSpecies(item)} />)}</ul>}{state === "ready" && catalog.items.length === 0 && <p className="species-catalog__state">No canonical taxa match this search.</p>}
    </aside>
    <main className="species-intelligence-pane"><ReturnContext params={searchParams} />{displayedSelected ? <SpeciesIntelligence species={displayedSelected} tracking={tracking} media={mediaByTaxon[displayedSelected.id]} /> : <div className="species-intelligence-empty"><h2>Select a species</h2><p>Choose a canonical taxon from the catalog to view available intelligence.</p></div>}</main>
  </div>;
}
