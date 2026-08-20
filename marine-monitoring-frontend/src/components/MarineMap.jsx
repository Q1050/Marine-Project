import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Circle,
  Rectangle,
  ZoomControl,
  Tooltip,
} from "react-leaflet";

import "leaflet/dist/leaflet.css";

import L from "leaflet";

function createMarkerIcon(className, symbol) {
  return L.divIcon({
    className: "",
    html: `
      <div class="marine-marker ${className}">
        ${symbol}
      </div>
    `,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
    popupAnchor: [0, -18],
  });
}

const nativeIcon = createMarkerIcon("marker-native", "●");

const invasiveIcon = createMarkerIcon("marker-invasive", "!");

const reviewIcon = createMarkerIcon("marker-review", "?");

const anomalyIcon = createMarkerIcon("marker-anomaly", "⚠");

const confirmedIcon = createMarkerIcon("marker-confirmed", "✓");
const correctedIcon = createMarkerIcon("marker-corrected", "C");
const duplicateIcon = createMarkerIcon("marker-duplicate", "D");

function getMarkerIcon(observation) {
  if (observation.is_possible_duplicate) {
    return duplicateIcon;
  }

  if (observation.verification_status === "CONFIRMED") {
    return confirmedIcon;
  }

  if (observation.verification_status === "CORRECTED") {
    return correctedIcon;
  }

  if (observation.verification_status === "NEEDS_MORE_REVIEW") {
    return reviewIcon;
  }
  if (observation.identification_status === "unresolved") {
    return reviewIcon;
  }

  if (observation.priority === "HIGH") {
    return anomalyIcon;
  }

  if (observation.ecological_status === "INVASIVE") {
    return invasiveIcon;
  }

  return nativeIcon;
}

const SUITABILITY_STYLES = {
  VERY_LOW: { color: "#3b82f6", fillOpacity: 0.08 },
  LOW: { color: "#22a6a1", fillOpacity: 0.12 },
  MODERATE: { color: "#e1ad01", fillOpacity: 0.17 },
  HIGH: { color: "#ed7d31", fillOpacity: 0.22 },
  VERY_HIGH: { color: "#c53b3b", fillOpacity: 0.28 },
};

const MONITORING_PRIORITY_STYLES = {
  VERY_LOW: { color: "#7c6b91", fillOpacity: 0.008, opacity: 0.06, weight: 0.15 },
  LOW: { color: "#76558f", fillOpacity: 0.035, opacity: 0.18, weight: 0.35 },
  MODERATE: { color: "#743a99", fillOpacity: 0.11, opacity: 0.42, weight: 0.7 },
  HIGH: { color: "#70209f", fillOpacity: 0.2, opacity: 0.68, weight: 1.05 },
  VERY_HIGH: { color: "#641090", fillOpacity: 0.3, opacity: 0.92, weight: 1.7 },
};

const REASON_LABELS = {
  HIGH_HABITAT_SUITABILITY:
    "High relative habitat suitability",
  NEAR_RECENT_CONFIRMED_SIGHTING:
    "Near a recent expert-confirmed sighting",
  NEAR_RECENT_AI_SUPPORTED_SIGHTING:
    "Near a recent AI-supported sighting",
};

function suitabilityBounds(cell) {
  const halfSize = Number(cell.grid_size || 0.1) / 2;
  return [
    [cell.latitude - halfSize, cell.longitude - halfSize],
    [cell.latitude + halfSize, cell.longitude + halfSize],
  ];
}

function readableBand(value) {
  if (!value) {
    return "Unavailable";
  }

  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatScore(value) {
  return value == null
    ? "Unavailable"
    : Number(value).toFixed(3);
}

function formatDistance(value) {
  return value == null
    ? "Unavailable"
    : `${Number(value).toFixed(1)} km`;
}

function formatTimestamp(value) {
  if (!value) {
    return "Unavailable";
  }

  const timestampValue = /(?:Z|[+-]\d\d:\d\d)$/i.test(value)
    ? value
    : `${value}Z`;
  const timestamp = new Date(timestampValue);
  return Number.isNaN(timestamp.getTime())
    ? "Unavailable"
    : timestamp.toLocaleString();
}

export default function MarineMap({
  observations,
  onSelectObservation,
  hotspots,
  suitabilityCells,
  monitoringPriorityCells,
  monitoringPriorityVisible,
  selectedPriorityCellId,
  visibleLayers,
  onSelectPriorityCell,
  onSelectSuitabilityCell,
  center = [18.1096, -77.2975],
  zoom = 8,
}) {
  return (
    <MapContainer
      center={center}
      zoom={zoom}
      zoomControl={false}
      style={{
        height: "100%",
        width: "100%",
      }}
    >
      <ZoomControl position="bottomright" />
      <TileLayer
        attribution="&copy; OpenStreetMap contributors &copy; CARTO"
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />

      {visibleLayers.suitability && suitabilityCells.map((cell, index) => {
        const style = SUITABILITY_STYLES[cell.suitability_band] || SUITABILITY_STYLES.VERY_LOW;

        return (
          <Rectangle
            key={`suitability-${cell.latitude}-${cell.longitude}-${index}`}
            bounds={suitabilityBounds(cell)}
            pathOptions={{
              color: style.color,
              fillColor: style.color,
              fillOpacity: style.fillOpacity,
              opacity: 0.35,
              weight: 0.6,
            }}
            eventHandlers={{ click: () => onSelectSuitabilityCell?.(cell) }}
          />
        );
      })}

      {monitoringPriorityVisible && monitoringPriorityCells.map((cell, index) => {
        const style = MONITORING_PRIORITY_STYLES[cell.priority_band]
          || MONITORING_PRIORITY_STYLES.VERY_LOW;
        const nearbyCount = Array.isArray(cell.nearby_observation_ids)
          ? cell.nearby_observation_ids.length
          : null;
        const reasons = Array.isArray(cell.reason_codes)
          ? cell.reason_codes
          : [];
        const selected = selectedPriorityCellId != null
          && cell.grid_cell_id === selectedPriorityCellId;
        const basePathOptions = {
          color: style.color,
          fillColor: style.color,
          fillOpacity: selected ? Math.max(style.fillOpacity, 0.2) : style.fillOpacity,
          opacity: selected ? 1 : style.opacity,
          weight: selected ? 2.8 : style.weight,
          dashArray: null,
        };

        return (
          <Rectangle
            key={`monitoring-priority-${cell.grid_cell_id || index}`}
            bounds={suitabilityBounds({
              ...cell,
              grid_size: 0.1,
            })}
            pathOptions={basePathOptions}
            eventHandlers={{
              click: (event) => {
                onSelectPriorityCell?.(cell);
                globalThis.setTimeout(() => event.target.closePopup(), 0);
              },
              mouseover: (event) => {
                event.target.setStyle({
                  fillOpacity: Math.max(style.fillOpacity + 0.09, 0.1),
                  opacity: Math.max(style.opacity, 0.55),
                  weight: Math.max(style.weight + 0.7, 0.85),
                });
                const element = event.target.getElement();
                if (element) element.style.cursor = "pointer";
              },
              mouseout: (event) => event.target.setStyle(basePathOptions),
            }}
          >
            <Tooltip sticky direction="top" opacity={0.96}>
              <strong>Monitoring priority</strong><br />
              {readableBand(cell.priority_band)} · {formatScore(cell.monitoring_priority_score)}
            </Tooltip>
            <Popup maxWidth={330}>
              <div className="monitoring-priority-popup">
                <strong>Priority for monitoring</strong>
                <span>Priority band: {readableBand(cell.priority_band)}</span>
                <span>
                  Monitoring priority score: {formatScore(cell.monitoring_priority_score)}
                </span>
                <span>
                  Habitat suitability score: {formatScore(cell.suitability_score)}
                </span>
                <span>
                  Current observation evidence score: {formatScore(cell.current_evidence_score)}
                </span>
                <span>
                  Nearest qualifying evidence: {formatDistance(
                    cell.nearest_evidence_km
                    ?? cell.distance_from_nearest_current_evidence_km
                  )}
                </span>

                {cell.contributing_observation_id != null ? (
                  <>
                    <span>
                      Contributing observation: #{cell.contributing_observation_id}
                    </span>
                    <span>
                      Observation distance: {formatDistance(
                        cell.contributing_observation_distance_km
                      )}
                    </span>
                    <span>
                      Verification weight: {formatScore(
                        cell.contributing_verification_weight
                      )}
                    </span>
                    <span>
                      Recency weight: {formatScore(
                        cell.contributing_recency_weight
                      )}
                    </span>
                    <span>
                      Distance weight: {formatScore(
                        cell.contributing_distance_weight
                      )}
                    </span>
                    <span>
                      Contributing evidence score: {formatScore(
                        cell.contributing_evidence_score
                      )}
                    </span>
                  </>
                ) : (
                  <span>
                    No qualifying nearby observation evidence contributed.
                  </span>
                )}

                {nearbyCount != null && (
                  <span>Nearby contextual observations: {nearbyCount}</span>
                )}

                {reasons.length > 0 && (
                  <div className="monitoring-priority-reasons">
                    <span>Why this cell is prioritized:</span>
                    <ul>
                      {reasons.map((reason) => (
                        <li key={reason}>
                          {REASON_LABELS[reason] || readableBand(reason)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <span>
                  Recommendation snapshot generated: {formatTimestamp(cell.generated_at)}
                </span>
                <small>Version: {cell.prediction_version || "Unavailable"}</small>
                <em>
                  Prioritized using habitat suitability and recent observation evidence.
                </em>
                <em>
                  Monitoring prioritization; not a spread, invasion, or occurrence probability.
                </em>
              </div>
            </Popup>
          </Rectangle>
        );
      })}

      {visibleLayers.hotspots && hotspots.map((hotspot, index) => {
        const radius = 2500 + Math.min(hotspot.total_observations * 750, 6000);

        return (
          <Circle
            key={`hotspot-${index}`}
            center={[hotspot.latitude, hotspot.longitude]}
            radius={radius}
            pathOptions={{
              fillOpacity: 0.18,
              opacity: 0.5,
            }}
          >
            <Popup>
              <strong>Observation hotspot</strong>
              <br />
              Sightings: {hotspot.total_observations}
              <br />
              Verified: {hotspot.verified_observations}
              <br />
              Invasive: {hotspot.invasive_observations}
              <br />
              Activity status: {hotspot.activity_status || "Unavailable"}
              <br />
              Invasive activity: {hotspot.invasive_activity || "NONE"}
              <br />
              Invasive evidence confidence:{" "}
              {hotspot.invasive_evidence_confidence || "NONE"}
              <br />
              Weighted invasive evidence:{" "}
              {Number(hotspot.weighted_invasive_evidence || 0).toFixed(1)}
              <br />
              AI unresolved: {hotspot.unresolved_observations}
              <br />
              Past 7 days: {hotspot.past_7_days}
              <br />
              Past 30 days: {hotspot.past_30_days}
              <br />
              Past 90 days: {hotspot.past_90_days}
              {Object.entries(hotspot.species || {}).map(([species, count]) => (
                <div
                  key={species}
                  style={{
                    marginTop: "4px",
                  }}
                >
                  {species}: {count}
                </div>
              ))}
            </Popup>
          </Circle>
        );
      })}

      {visibleLayers.sightings && observations.map((observation) => (
        <Marker
          key={observation.id}
          position={[observation.latitude, observation.longitude]}
          icon={getMarkerIcon(observation)}
          eventHandlers={{
            click: () => {
              onSelectObservation(observation);
            },
          }}
        />
      ))}
    </MapContainer>
  );
}
