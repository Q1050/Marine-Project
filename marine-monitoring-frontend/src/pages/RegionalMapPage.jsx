import { useEffect, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  Tooltip,
  useMapEvents,
} from "react-leaflet";
import {
  getJurisdictions,
  getRegionOverview,
} from "../services/api";
import { REGIONS } from "../config/geography";

const REGION = REGIONS.caribbean;

function getRegionalViewFromUrl() {
  const params = new URLSearchParams(window.location.search);
  if (!["lat", "lng", "z"].every((key) => params.has(key))) return null;
  const lat = Number(params.get("lat"));
  const lng = Number(params.get("lng"));
  const zoom = Number(params.get("z"));
  if (![lat, lng, zoom].every(Number.isFinite)) return null;
  return { lat, lng, zoom };
}

const number = (value) => Number(value || 0).toLocaleString();

function RegionalStatusBar({ region, observations, operational, scientific, summaries }) {
  return (
    <div className="regional-status-bar">
      <div className="regional-status-bar__heading">
        <p className="regional-status-bar__eyebrow">Caribbean regional monitoring</p>
        <h1 className="regional-status-bar__title">{region?.name || REGION.name} Overview</h1>
        <p className="regional-status-bar__subtitle">
          Operational monitoring activity across configured Caribbean jurisdictions.
        </p>
      </div>
      <div className="regional-status-bar__kpis">
        <Kpi label="Monitored jurisdictions" value={`${region ? region.boundary_configured : 0}/${region ? region.total : 0}`} sublabel="boundary configured" />
        <Kpi label="Total observations" value={number(observations?.total)} sublabel={`${number(observations?.confirmed)} confirmed · ${number(observations?.corrected)} corrected`} />
        <Kpi label="Reports requiring review" value={number((observations?.pending_review || 0) + (observations?.needs_more_review || 0))} sublabel={`${number(observations?.pending_review)} pending · ${number(observations?.needs_more_review)} needs more`} />
        <Kpi label="Active investigations" value={number(operational?.investigations_active)} sublabel={`${number(operational?.investigations_total)} total investigations`} />
      </div>
      {summaries && summaries.length > 0 && (
        <ul className="regional-status-bar__jurisdictions">
          {summaries.map((item) => (
            <li key={item.slug} className="regional-status-bar__jurisdiction">
              <div>
                <strong>{item.name}</strong>
                <span className="regional-status-bar__meta">
                  {number(item.observations.total)} reports ·{" "}
                  {number(item.investigations.active)} active investigations
                </span>
              </div>
              <div className="regional-status-bar__capabilities">
                <CapabilityTag label="Suitability" available={item.capabilities?.habitat_suitability} />
                <CapabilityTag label="Monitoring Priority" available={item.capabilities?.monitoring_priority} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {scientific && summaries && summaries.length > 0 && (
        <p className="regional-status-bar__note">
          {scientific.jurisdictions_with_species_programs || 0} jurisdiction
          {(scientific.jurisdictions_with_species_programs || 0) === 1 ? " has" : "s have"} a validated scientific deployment. Predictive science is jurisdiction-specific; there is no Caribbean-wide prediction model.
        </p>
      )}
    </div>
  );
}

function Kpi({ label, value, sublabel }) {
  return (
    <div className="regional-status-bar__kpi">
      <p className="regional-status-bar__kpi-label">{label}</p>
      <strong className="regional-status-bar__kpi-value">{value}</strong>
      {sublabel && <p className="regional-status-bar__kpi-sublabel">{sublabel}</p>}
    </div>
  );
}

function CapabilityTag({ label, available }) {
  return (
    <span className={`regional-capability-tag ${available ? "regional-capability-tag--available" : "regional-capability-tag--unavailable"}`}>
      {label}: {available ? "Available" : "Not configured"}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="regional-state regional-state--loading">
      <p>Loading Caribbean monitoring overview…</p>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="regional-state regional-state--error" role="alert">
      <h2>Regional overview unavailable</h2>
      <p>{message || "The regional overview service is currently unavailable."}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="regional-state__retry">
          Retry
        </button>
      )}
    </div>
  );
}

function EmptyRegionState() {
  return (
    <div className="regional-state regional-state--empty">
      <h2>No jurisdictions configured</h2>
      <p>
        The Caribbean region has no active jurisdictions configured yet. Use the
        platform administration tools to onboard a jurisdiction.
      </p>
    </div>
  );
}

export default function RegionalMapPage({
  onOpenJurisdiction,
  onGeographicContextChange,
}) {
  const [overview, setOverview] = useState(null);
  const [jurisdictions, setJurisdictions] = useState([]);
  const [overviewState, setOverviewState] = useState("loading");
  const [overviewError, setOverviewError] = useState(null);
  const [jurisdictionState, setJurisdictionState] = useState("loading");
  const [initialView] = useState(getRegionalViewFromUrl);

  useEffect(() => {
    let active = true;
    getRegionOverview("caribbean")
      .then((data) => {
        if (!active) return;
        setOverview(data);
        setOverviewState(data?.jurisdiction_summaries?.length ? "ready" : "empty");
      })
      .catch((error) => {
        if (!active) return;
        setOverview(null);
        setOverviewError(error?.message || "Regional overview could not be loaded.");
        setOverviewState("error");
      });
    getJurisdictions("caribbean")
      .then((data) => {
        if (!active) return;
        setJurisdictions(
          (data.jurisdictions || []).map((item) => ({
            ...item,
            center: [item.center_latitude, item.center_longitude],
            configured: item.operational_boundary_configured,
          })),
        );
        setJurisdictionState("ready");
      })
      .catch(() => active && setJurisdictionState("error"));
    return () => {
      active = false;
    };
  }, []);

  const loadOverview = () => {
    setOverviewState("loading");
    setOverviewError(null);
    getRegionOverview("caribbean")
      .then((data) => {
        setOverview(data);
        setOverviewState(data?.jurisdiction_summaries?.length ? "ready" : "empty");
      })
      .catch((error) => {
        setOverview(null);
        setOverviewError(error?.message || "Regional overview could not be loaded.");
        setOverviewState("error");
      });
  };

  const showMap = overviewState === "ready";
  const showStatusBar = overviewState === "ready";
  const showJurisdictionPins = overviewState === "ready" && jurisdictions.length > 0;

  return (
    <div className="regional-explorer">
      {overviewState === "loading" && <LoadingState />}
      {overviewState === "error" && (
        <ErrorState message={overviewError} onRetry={loadOverview} />
      )}
      {overviewState === "empty" && <EmptyRegionState />}
      {showStatusBar && (
        <RegionalStatusBar
          region={overview?.jurisdictions}
          observations={overview?.observations}
          operational={overview?.operational_activity}
          scientific={overview?.scientific_deployments}
          summaries={overview?.jurisdiction_summaries}
        />
      )}
      {showMap && (
        <div className="regional-map-wrap">
          <MapContainer
            {...(initialView
              ? { center: [initialView.lat, initialView.lng], zoom: initialView.zoom }
              : { bounds: REGION.bounds, boundsOptions: { padding: [24, 24] } })}
            zoomSnap={0.25}
            minZoom={3.5}
            maxZoom={10}
            className="regional-map"
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors &copy; CARTO"
              url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            />
            <RegionalMapState
              onChange={(view) => {
                onGeographicContextChange?.(null);
                const params = new URLSearchParams(window.location.search);
                params.set("lat", view.lat.toFixed(4));
                params.set("lng", view.lng.toFixed(4));
                params.set("z", view.zoom.toFixed(2));
                const regionalUrl = `/region/caribbean?${params}`;
                window.history.replaceState(
                  { ...window.history.state, regionalView: view },
                  "",
                  regionalUrl,
                );
                sessionStorage.setItem("caribbeanRegionalUrl", regionalUrl);
              }}
            />
            {showJurisdictionPins && jurisdictions.map((jurisdiction) => (
              <CircleMarker
                key={jurisdiction.id}
                center={jurisdiction.center}
                radius={jurisdiction.configured ? 11 : 7}
                pathOptions={{
                  color: jurisdiction.configured ? "#087c75" : "#71838b",
                  fillColor: jurisdiction.configured ? "#0b9489" : "#ffffff",
                  fillOpacity: jurisdiction.configured ? 0.85 : 0.7,
                  weight: jurisdiction.configured ? 3 : 2,
                  dashArray: jurisdiction.configured ? null : "4 3",
                }}
              >
                <Tooltip direction="top" offset={[0, -9]}>
                  {jurisdiction.name} · {jurisdiction.status}
                </Tooltip>
                <Popup minWidth={240}>
                  <CountryPreview
                    jurisdiction={jurisdiction}
                    summary={overview?.jurisdiction_summaries?.find(
                      (item) => item.slug === jurisdiction.slug,
                    )}
                    onOpen={() => onOpenJurisdiction?.(jurisdiction.slug)}
                  />
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="regional-map-legend">
            <strong>Caribbean jurisdictions</strong>
            <span>
              <i className="active-dot" /> Monitoring active
            </span>
            <span>
              <i className="planned-dot" /> Planned / not configured
            </span>
          </div>
        </div>
      )}
      {overviewState === "ready" && jurisdictionState === "error" && (
        <p className="regional-warnings">Jurisdiction boundary metadata could not be loaded. The map may be missing jurisdiction pins.</p>
      )}
    </div>
  );
}

function RegionalMapState({ onChange }) {
  useMapEvents({
    moveend: (event) => {
      const map = event.target;
      const center = map.getCenter();
      onChange({ lat: center.lat, lng: center.lng, zoom: map.getZoom() });
    },
  });
  return null;
}

function CountryPreview({ jurisdiction, summary, onOpen }) {
  const configured = jurisdiction.configured;
  return (
    <div className="country-preview">
      <span className={configured ? "configured" : "planned"}>
        {jurisdiction.status}
      </span>
      <h2>{jurisdiction.name}</h2>
      {configured && summary ? (
        <>
          <div>
            <span>Observations</span>
            <strong>{number(summary.observations?.total)}</strong>
          </div>
          <div>
            <span>Awaiting review</span>
            <strong>{number(summary.observations?.pending_review)}</strong>
          </div>
          <div>
            <span>Investigations (active / total)</span>
            <strong>
              {number(summary.investigations?.active)} / {number(summary.investigations?.total)}
            </strong>
          </div>
          <div>
            <span>Field visits</span>
            <strong>{number(summary.field_visits_total)}</strong>
          </div>
          <div>
            <span>Habitat suitability</span>
            <strong>
              {summary.capabilities?.habitat_suitability ? "Available" : "Not configured"}
            </strong>
          </div>
          <div>
            <span>Monitoring priority</span>
            <strong>
              {summary.capabilities?.monitoring_priority ? "Available" : "Not configured"}
            </strong>
          </div>
          <button onClick={onOpen}>Open {jurisdiction.name} →</button>
        </>
      ) : configured ? (
        <p>This jurisdiction is configured. Summary details are not available.</p>
      ) : (
        <p>This jurisdiction is not yet configured for operational monitoring.</p>
      )}
    </div>
  );
}