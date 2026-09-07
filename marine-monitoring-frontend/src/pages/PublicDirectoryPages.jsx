import { useEffect, useState } from "react";
import {
  GeoJSON,
  MapContainer,
  CircleMarker,
  Popup,
  Rectangle,
  TileLayer,
} from "react-leaflet";
import { BASEMAP } from "../config/basemap";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  getPublicJurisdiction,
  getPublicRegion,
  getPublicSpeciesDetail,
  getPublicSpeciesDirectory,
  getPublicSpeciesMap,
  getPublicSuitabilityGrid,
  getPublicTaxonMedia,
  getRegions,
} from "../services/api";

const readable = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
function Frame({ breadcrumbs = [], title, eyebrow, children, action }) {
  return (
    <main className="mx-auto max-w-[1450px] p-4 sm:p-6">
      <nav
        aria-label="Breadcrumb"
        className="mb-5 flex flex-wrap gap-2 text-xs text-app-muted"
      >
        <Link to="/regions" className="text-teal-700">
          Regions
        </Link>
        {breadcrumbs.map((item) => (
          <span key={item.label}>
            /{" "}
            {item.to ? (
              <Link to={item.to} className="text-teal-700">
                {item.label}
              </Link>
            ) : (
              item.label
            )}
          </span>
        ))}
      </nav>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.16em] text-teal-700">
            {eyebrow}
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{title}</h1>
        </div>
        {action}
      </header>
      {children}
    </main>
  );
}
function Loading({ error }) {
  return (
    <div
      className={`rounded-xl border p-6 text-sm ${error ? "border-red-200 bg-red-50 text-red-700" : "border-app-border bg-white text-app-muted"}`}
    >
      {error || "Loading public marine information…"}
    </div>
  );
}

export function PublicRegionsPage() {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    getRegions()
      .then((data) => setState({ data, error: null }))
      .catch((error) => setState({ data: null, error: error.message }));
  }, []);
  return (
    <Frame eyebrow="Public directory" title="Marine monitoring regions">
      {!state.data ? (
        <Loading error={state.error} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {state.data.regions.map((region) => (
            <Link
              key={region.id}
              to={`/regions/${region.slug}`}
              className="rounded-2xl border border-app-border bg-white p-6 shadow-sm transition hover:border-teal-400"
            >
              <h2 className="text-xl font-bold">{region.name}</h2>
              <p className="mt-2 text-sm text-app-muted">
                {region.jurisdiction_count} geographically onboarded
                jurisdiction{region.jurisdiction_count === 1 ? "" : "s"}
              </p>
              <span className="mt-5 inline-block text-sm font-bold text-teal-700">
                Explore region →
              </span>
            </Link>
          ))}
        </div>
      )}
    </Frame>
  );
}

export function PublicRegionPage() {
  const { regionSlug } = useParams(),
    [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    getPublicRegion(regionSlug)
      .then((data) => setState({ data, error: null }))
      .catch((error) => setState({ data: null, error: error.message }));
  }, [regionSlug]);
  const data = state.data;
  return (
    <Frame eyebrow="Marine monitoring region" title={data?.name || "Region"}>
      {!data ? (
        <Loading error={state.error} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.jurisdictions.map((item) => (
            <Link
              key={item.id}
              to={`/jurisdictions/${item.slug}`}
              className="rounded-2xl border border-app-border bg-white p-5 shadow-sm"
            >
              <div className="flex justify-between gap-3">
                <h2 className="font-bold">{item.name}</h2>
                <span
                  className={`rounded-full px-2 py-1 text-[11px] font-bold ${item.geographic_configuration_state === "CONFIGURED" ? "bg-teal-50 text-teal-800" : "bg-slate-100 text-slate-600"}`}
                >
                  {readable(item.geographic_configuration_state)}
                </span>
              </div>
              <p className="mt-3 text-sm text-app-muted">
                {item.marine_species_count
                  ? `${item.marine_species_count} governed marine taxa`
                  : "Geographically onboarded; no governed species directory yet."}
              </p>
            </Link>
          ))}
        </div>
      )}
    </Frame>
  );
}

export function PublicJurisdictionPage() {
  const { jurisdiction } = useParams(),
    [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    getPublicJurisdiction(jurisdiction)
      .then((data) => setState({ data, error: null }))
      .catch((error) => setState({ data: null, error: error.message }));
  }, [jurisdiction]);
  const data = state.data;
  return (
    <Frame
      breadcrumbs={
        data
          ? [
              { label: data.region.name, to: `/regions/${data.region.slug}` },
              { label: data.name },
            ]
          : []
      }
      eyebrow="Jurisdiction marine monitoring"
      title={data ? `${data.name} Marine Monitoring` : "Jurisdiction"}
      action={
        data && (
          <Link
            to={data.report_sighting_url}
            className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white"
          >
            Report a sighting
          </Link>
        )
      }
    >
      {!data ? (
        <Loading error={state.error} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Geography", readable(data.geographic_configuration_state)],
              ["Marine species", data.governed_marine_species_count],
              ["Invasive marine species", data.governed_invasive_species_count],
              ["Directory", readable(data.governed_species_directory_state)],
            ].map(([label, value]) => (
              <article
                key={label}
                className="rounded-xl border border-app-border bg-white p-5"
              >
                <p className="text-xs font-bold uppercase text-app-muted">
                  {label}
                </p>
                <strong className="mt-2 block text-xl">{value}</strong>
              </article>
            ))}
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <DirectoryLink
              to={`/jurisdictions/${data.id}/marine-species`}
              title="Marine Species"
              text="Browse taxa with current approved jurisdiction status."
            />
            <DirectoryLink
              to={`/jurisdictions/${data.id}/invasive-species`}
              title="Invasive Marine Species"
              text={
                data.governed_invasive_species_count
                  ? "Browse current approved invasive-status records."
                  : "No governed invasive marine-species records are currently available for this jurisdiction. No governed invasive-species assertions are shown until source review is complete."
              }
            />
          </div>
        </>
      )}
    </Frame>
  );
}
function DirectoryLink({ to, title, text }) {
  return (
    <Link
      to={to}
      className="rounded-2xl border border-app-border bg-white p-6 shadow-sm"
    >
      <h2 className="text-lg font-bold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-app-muted">{text}</p>
      <span className="mt-4 inline-block text-sm font-bold text-teal-700">
        Open directory →
      </span>
    </Link>
  );
}

export function PublicSpeciesDirectoryPage({ invasive = false }) {
  const { jurisdictionId } = useParams(),
    [params, setParams] = useSearchParams(),
    page = Number(params.get("page") || 1),
    search = params.get("search") || "",
    [query, setQuery] = useState(search),
    [jurisdiction, setJurisdiction] = useState(null),
    [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    getPublicJurisdiction(jurisdictionId).then(setJurisdiction);
    getPublicSpeciesDirectory(jurisdictionId, { invasive, page, search })
      .then((data) => setState({ data, error: null }))
      .catch((error) => setState({ data: null, error: error.message }));
  }, [jurisdictionId, invasive, page, search]);
  const data = state.data,
    title = invasive ? "Invasive Marine Species" : "Marine Species";
  function submit(event) {
    event.preventDefault();
    setParams(query ? { search: query, page: 1 } : { page: 1 });
  }
  return (
    <Frame
      breadcrumbs={
        jurisdiction
          ? [
              {
                label: jurisdiction.region.name,
                to: `/regions/${jurisdiction.region.slug}`,
              },
              {
                label: jurisdiction.name,
                to: `/jurisdictions/${jurisdiction.id}`,
              },
              { label: title },
            ]
          : []
      }
      eyebrow="Governed public directory"
      title={title}
    >
      {
        <form onSubmit={submit} className="mb-5 flex max-w-xl gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search scientific or common name"
            className="min-w-0 flex-1 rounded-lg border border-app-border px-3 py-2"
          />
          <button className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white">
            Search
          </button>
        </form>
      }
      {!data ? (
        <Loading error={state.error} />
      ) : data.items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-app-border bg-white p-10 text-center">
          <h2 className="font-bold">
            No governed {invasive ? "invasive " : ""}marine-species records are
            currently available for this jurisdiction.
          </h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-app-muted">
            This is a valid scientific state. Regional taxonomy and unreviewed
            legacy classifications are not used to populate this directory.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((item) => (
              <Link
                key={item.taxon_id}
                to={`/jurisdictions/${jurisdictionId}/species/${item.taxon_id}`}
                className="rounded-xl border border-app-border bg-white p-5"
              >
                {item.primary_image?.url ? <figure className="-mx-5 -mt-5 mb-4 overflow-hidden rounded-t-xl"><img src={item.primary_image.url} alt={item.primary_image.alt_text} className="h-40 w-full object-cover"/><figcaption className="px-3 py-2 text-[10px] text-app-muted">{item.primary_image.attribution_text} · {item.primary_image.license}</figcaption></figure> : <div className="-mx-5 -mt-5 mb-4 grid h-40 place-items-center rounded-t-xl bg-slate-100 text-xs text-app-muted">No approved public image</div>}
                <p className="text-xs text-app-muted">
                  {item.common_name || "Common name not available"}
                </p>
                <h2 className="mt-1 font-serif text-xl italic">
                  {item.scientific_name}
                </h2>
                <div className="mt-3 flex flex-wrap gap-1">
                  {item.current_reviewed_status.statuses.map((status) => (
                    <span
                      key={status}
                      className="rounded-full bg-teal-50 px-2 py-1 text-xs font-bold text-teal-800"
                    >
                      {readable(status)}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
          <div className="mt-6 flex justify-between text-sm">
            <button
              disabled={page <= 1}
              onClick={() =>
                setParams({ ...(search && { search }), page: page - 1 })
              }
            >
              ← Previous
            </button>
            <span>
              Page {data.page} · {data.total} records
            </span>
            <button
              disabled={page * data.page_size >= data.total}
              onClick={() =>
                setParams({ ...(search && { search }), page: page + 1 })
              }
            >
              Next →
            </button>
          </div>
        </>
      )}
    </Frame>
  );
}

export function PublicSpeciesDetailPage() {
  const { jurisdictionId, taxonId } = useParams(),
    [state, setState] = useState({ detail: null, map: null, error: null });
  useEffect(() => {
    Promise.all([
      getPublicSpeciesDetail(jurisdictionId, taxonId),
      getPublicSpeciesMap(jurisdictionId, taxonId),
      getPublicSuitabilityGrid(jurisdictionId, taxonId),
      getPublicTaxonMedia(taxonId),
    ])
      .then(([detail, map, suitability, media]) => setState({ detail: { ...detail, media }, map: { ...map, suitability }, error: null }))
      .catch((error) =>
        setState({ detail: null, map: null, error: error.message }),
      );
  }, [jurisdictionId, taxonId]);
  const { detail, map } = state;
  return (
    <Frame
      breadcrumbs={
        map
          ? [
              {
                label: map.jurisdiction.name,
                to: `/jurisdictions/${jurisdictionId}`,
              },
              {
                label: "Marine species",
                to: `/jurisdictions/${jurisdictionId}/marine-species`,
              },
              { label: detail?.scientific_name },
            ]
          : []
      }
      eyebrow="Marine species"
      title={detail?.common_name || detail?.scientific_name || "Species detail"}
      action={
        map && (
          <Link
            to={`/region/${map.jurisdiction.region_slug}/${map.jurisdiction.slug}/submit?jurisdiction_id=${map.jurisdiction.id}&taxon_id=${taxonId}`}
            className="rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white"
          >
            Report a sighting
          </Link>
        )
      }
    >
      {!detail || !map ? (
        <Loading error={state.error} />
      ) : (
        <>
          <p className="-mt-4 mb-6 font-serif text-xl italic text-app-muted">
            {detail.scientific_name}
          </p>
          {detail.media?.primary_image?.url ? <figure className="mb-5 overflow-hidden rounded-2xl border border-app-border bg-white"><img src={detail.media.primary_image.url} alt={`${detail.scientific_name} reference`} className="max-h-80 w-full object-cover"/><figcaption className="p-3 text-xs text-app-muted">{detail.media.primary_image.attribution_text} · {detail.media.primary_image.license}</figcaption></figure> : <div className="mb-5 rounded-xl border border-dashed border-app-border bg-slate-50 p-6 text-sm text-app-muted">No approved public reference image is available for this marine taxon.</div>}
          <div className="grid gap-5 xl:grid-cols-[1.5fr_.8fr]">
            <SpeciesEvidenceMap data={map} />
            <aside className="space-y-4">
              <Info title="Jurisdiction status">
                {detail.current_reviewed_status.statuses.length ? (
                  <div className="flex flex-wrap gap-2">
                    {detail.current_reviewed_status.statuses.map((item) => (
                      <span
                        key={item}
                        className="rounded-full bg-teal-50 px-3 py-1 text-sm font-bold text-teal-800"
                      >
                        {readable(item)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p>
                    No current approved ecological-status record is available.
                  </p>
                )}
              </Info>
              <Info title="Occurrence evidence">
                <strong>{detail.occurrence_summary.count}</strong> applied
                governed record
                {detail.occurrence_summary.count === 1 ? "" : "s"}. This
                indicates evidence, not ecological or invasive status.
              </Info>
              <Info title="Environmental context">
                {detail.suitability.available ? (
                  <p>
                    {detail.suitability.label} Model:{" "}
                    {detail.suitability.model_version}
                  </p>
                ) : (
                  <p>No authorized suitability context is available.</p>
                )}
              </Info>
            </aside>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Info title="Verified platform observations">
              {detail.verified_observations.length
                ? `${detail.verified_observations.length} non-duplicate verified report(s).`
                : "No appropriate verified public reports are available."}
            </Info>
            <Info title="Sources">
              {detail.source_attribution.length
                ? detail.source_attribution.map((source) => (
                    <p key={`${source.title}-${source.reference}`}>
                      {source.organization}:{" "}
                      <a
                        className="text-teal-700 underline"
                        href={source.reference}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {source.title}
                      </a>
                    </p>
                  ))
                : "No approved ecological-status source attribution is available."}
            </Info>
          </div>
        </>
      )}
    </Frame>
  );
}
function Info({ title, children }) {
  return (
    <section className="rounded-xl border border-app-border bg-white p-5 text-sm leading-6 text-app-muted">
      <h2 className="mb-2 font-bold text-slate-900">{title}</h2>
      {children}
    </section>
  );
}
function SpeciesEvidenceMap({ data }) {
  const [layers, setLayers] = useState({ boundary: true, occurrence: true, observations: true, suitability: false });
  const center = [
    data.jurisdiction.center_latitude,
    data.jurisdiction.center_longitude,
  ];
  return (
    <section className="overflow-hidden rounded-2xl border border-app-border bg-white">
      <div className="flex flex-wrap gap-3 border-b border-app-border p-3 text-xs">{[["boundary","Jurisdiction boundary",true],["occurrence","Governed occurrence evidence",true],["observations","Verified observations",true],["suitability","Environmental suitability",data.suitability?.available]].map(([key,label,available]) => <label key={key} className="flex items-center gap-2"><input type="checkbox" disabled={!available} checked={available && layers[key]} onChange={() => setLayers((value) => ({ ...value, [key]: !value[key] }))}/>{label}{!available && " (unavailable)"}</label>)}</div>
      <div className="h-[480px]">
        <MapContainer
          center={center}
          zoom={data.jurisdiction.default_zoom || 7}
          className="h-full w-full"
        >
          <TileLayer
            attribution={BASEMAP.attribution}
            url={BASEMAP.url}
          />
          {layers.suitability && data.suitability?.cells.map((cell) => { const half=cell.grid_size/2; return <Rectangle key={`${cell.latitude}-${cell.longitude}`} bounds={[[cell.latitude-half,cell.longitude-half],[cell.latitude+half,cell.longitude+half]]} pathOptions={{color:"#7c3aed",weight:0,fillOpacity:Math.max(.08,(cell.suitability_score||0)*.35)}}><Popup>{cell.suitability_band}<br/>Relative environmental suitability: {cell.suitability_score?.toFixed(3)}<br/>{data.suitability.disclaimer}</Popup></Rectangle>; })}
          {layers.boundary && data.boundary && (
            <GeoJSON
              data={data.boundary}
              style={{ color: "#0f766e", weight: 2, fillOpacity: 0.04 }}
            />
          )}
          {layers.occurrence && data.occurrence_points.map((point, index) => (
            <CircleMarker
              key={`e-${index}`}
              center={[point.latitude, point.longitude]}
              radius={5}
              pathOptions={{ color: "#0f766e", fillOpacity: 0.8 }}
            >
              <Popup>
                Governed occurrence evidence
                <br />
                {point.event_date || "Date unavailable"}
              </Popup>
            </CircleMarker>
          ))}
          {layers.observations && data.verified_observations.map((point) => (
            <CircleMarker
              key={`o-${point.id}`}
              center={[point.latitude, point.longitude]}
              radius={6}
              pathOptions={{ color: "#ea580c", fillOpacity: 0.85 }}
            >
              <Popup>Verified platform observation #{point.id}</Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
      <div className="flex flex-wrap gap-4 border-t border-app-border p-3 text-xs">
        {data.suitability?.available && <span className="font-semibold text-violet-800">Environmental suitability model — this does not confirm species presence.</span>}
        <span>
          <b className="text-teal-700">●</b> Governed occurrence evidence
        </span>
        <span>
          <b className="text-orange-600">●</b> Verified platform observation
        </span>
        <span>
          <b className="text-teal-700">—</b> Monitoring boundary
        </span>
      </div>
    </section>
  );
}
