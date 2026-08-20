import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import MarineMap from "../components/MarineMap";

import ObservationPanel from "../components/ObservationPanel";

import MapFilters from "../components/MapFilters";

import {
  getMapObservations,
  getObservation,
  getHotspots,
  getAnalyticsSummary,
  getSuitabilityGrid,
  getMonitoringPriorityGrid,
  getMonitoringPrioritySummary,
  getMonitoringPriorityFreshness,
  regenerateMonitoringPriorities,
} from "../services/api";
import { jurisdictionRoles, useAuth } from "../auth/AuthContext";
import { useJurisdiction } from "../geography/JurisdictionContext";

const MONITORING_INTERPRETATION_LABELS = {
  RECENT_REPORTING_EXISTING_RANGE:
    "Recent reporting · Existing historical range",
  INCREASED_REPORTING_EXISTING_RANGE:
    "Increased reporting · Existing historical range",
  NOTABLE_ACTIVITY_SPARSE_HISTORY:
    "Notable activity · Sparse historical records",
  POTENTIAL_RANGE_EXPANSION: "Potential range expansion",
  UNVERIFIED_OUT_OF_RANGE_REPORT: "Unverified out-of-range report",
  INSUFFICIENT_REGIONAL_CONTEXT: "Insufficient regional context",
};

const REGIONAL_CONTEXT_LABELS = {
  ESTABLISHED_RECORDS: "established records",
  SPARSE_RECORDS: "sparse records",
  NO_REGIONAL_RECORDS: "no regional records",
  INSUFFICIENT_DATA: "insufficient data",
};

const REASON_LABELS = {
  HIGH_HABITAT_SUITABILITY: "High relative habitat suitability",
  NEAR_RECENT_CONFIRMED_SIGHTING: "Near a recent expert-confirmed sighting",
  NEAR_RECENT_AI_SUPPORTED_SIGHTING: "Near a recent AI-supported sighting",
};

function signalEmphasisClass(interpretation) {
  if (interpretation === "POTENTIAL_RANGE_EXPANSION") {
    return "signal-item--potential";
  }

  if (interpretation === "UNVERIFIED_OUT_OF_RANGE_REPORT") {
    return "signal-item--unverified";
  }

  return "";
}

export default function MapPage({ refreshKey }) {
  const { user } = useAuth();
  const { activeRegion, activeJurisdiction, jurisdiction } = useJurisdiction();
  const scope = useMemo(
    () => ({ region: activeRegion, jurisdiction: activeJurisdiction }),
    [activeRegion, activeJurisdiction],
  );
  const hasSuitability = Boolean(
    jurisdiction?.capabilities?.habitat_suitability,
  );
  const hasMonitoringPriority = Boolean(
    jurisdiction?.capabilities?.monitoring_priority,
  );
  const navigate = useNavigate();
  const canRegenerate =
    hasMonitoringPriority &&
    (user?.is_platform_admin ||
      jurisdictionRoles(user, activeRegion, activeJurisdiction).includes(
        "MANAGER",
      ));
  const canManageInvestigations = canRegenerate;

  const [observations, setObservations] = useState([]);

  const [selectedObservation, setSelectedObservation] = useState(null);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hotspots, setHotspots] = useState([]);
  const [suitabilityCells, setSuitabilityCells] = useState([]);
  const [hotspotError, setHotspotError] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [suitabilityError, setSuitabilityError] = useState(null);
  const [monitoringPriorityCells, setMonitoringPriorityCells] = useState([]);
  const [monitoringPrioritySummary, setMonitoringPrioritySummary] =
    useState(null);
  const [monitoringPriorityLoading, setMonitoringPriorityLoading] =
    useState(true);
  const [monitoringPriorityError, setMonitoringPriorityError] = useState(null);
  const [monitoringPriorityVisible, setMonitoringPriorityVisible] =
    useState(false);
  const [monitoringPriorityFreshness, setMonitoringPriorityFreshness] =
    useState(null);
  const [monitoringPriorityRefreshKey, setMonitoringPriorityRefreshKey] =
    useState(0);
  const [monitoringPriorityRefreshing, setMonitoringPriorityRefreshing] =
    useState(false);
  const [
    monitoringPriorityRefreshMessage,
    setMonitoringPriorityRefreshMessage,
  ] = useState(null);
  const [selectedPriorityCell, setSelectedPriorityCell] = useState(null);
  const [selectedSuitabilityCell, setSelectedSuitabilityCell] = useState(null);
  const [activeMapControl, setActiveMapControl] = useState(null);
  const [mapMode, setMapMode] = useState("OBSERVATIONS");
  const [visibleLayers, setVisibleLayers] = useState({
    sightings: true,
    hotspots: true,
    suitability: false,
  });

  const [error, setError] = useState(null);

  const [filters, setFilters] = useState({
    species: "",
    ecological_status: "",
    priority: "",
    verification_status: "",
    decision: "",
  });
  const [observationDetails, setObservationDetails] = useState(null);

  const [detailsLoading, setDetailsLoading] = useState(false);
  function toggleLayer(layer) {
    setVisibleLayers((current) => ({
      ...current,
      [layer]: !current[layer],
    }));
  }
  async function handleObservationSelect(observation) {
    try {
      setSelectedObservation(observation);

      setObservationDetails(null);
      setDetailsLoading(true);

      const data = await getObservation(observation.id);

      setObservationDetails(data);
    } catch (err) {
      console.error("Unable to load observation:", err);
    } finally {
      setDetailsLoading(false);
    }
  }

  useEffect(() => {
    async function loadObservations() {
      try {
        setError(null);
        const [
          observationResult,
          hotspotResult,
          summaryResult,
          suitabilityResult,
        ] = await Promise.allSettled([
          getMapObservations(scope),
          getHotspots(scope),
          getAnalyticsSummary(scope),
          hasSuitability
            ? getSuitabilityGrid(scope)
            : Promise.resolve({ cells: [] }),
        ]);

        if (observationResult.status === "rejected") {
          throw observationResult.reason;
        }

        const observationData = observationResult.value;

        setObservations(observationData.markers || []);

        if (hotspotResult.status === "fulfilled") {
          setHotspots(hotspotResult.value.hotspots || []);
          setHotspotError(null);
        } else {
          console.error("Unable to load hotspots:", hotspotResult.reason);
          setHotspots([]);
          setHotspotError("Observation hotspots are temporarily unavailable.");
        }

        if (summaryResult.status === "fulfilled") {
          setSummary(summaryResult.value);
          setSummaryError(null);
        } else {
          console.error(
            "Unable to load monitoring summary:",
            summaryResult.reason,
          );
          setSummary(null);
          setSummaryError("Monitoring summary is temporarily unavailable.");
        }

        if (suitabilityResult.status === "fulfilled") {
          setSuitabilityCells(suitabilityResult.value.cells || []);
          setSuitabilityError(null);
        } else {
          // Habitat suitability is optional; core map workflows remain usable.
          console.error(
            "Unable to load habitat suitability:",
            suitabilityResult.reason,
          );
          setSuitabilityCells([]);
          setSuitabilityError(
            "Habitat suitability is temporarily unavailable.",
          );
        }
      } catch (err) {
        console.error(err);

        setError("Unable to load observations.");
      } finally {
        setLoading(false);
      }
    }

    loadObservations();
  }, [hasSuitability, refreshKey, scope]);

  useEffect(() => {
    let active = true;

    async function loadMonitoringPriority() {
      if (!hasMonitoringPriority) {
        setMonitoringPriorityCells([]);
        setMonitoringPrioritySummary(null);
        setMonitoringPriorityFreshness(null);
        setMonitoringPriorityLoading(false);
        return;
      }
      setMonitoringPriorityLoading(true);
      setMonitoringPriorityError(null);

      const [cellsResult, summaryResult, freshnessResult] =
        await Promise.allSettled([
          getMonitoringPriorityGrid(scope),
          getMonitoringPrioritySummary(scope),
          getMonitoringPriorityFreshness(scope),
        ]);

      if (!active) {
        return;
      }

      if (cellsResult.status === "fulfilled") {
        setMonitoringPriorityCells(cellsResult.value.cells || []);
      } else {
        console.error(
          "Unable to load monitoring priority:",
          cellsResult.reason,
        );
        setMonitoringPriorityCells([]);
        setMonitoringPriorityError(
          cellsResult.reason?.message || "Failed to load monitoring priority.",
        );
      }

      if (summaryResult.status === "fulfilled") {
        setMonitoringPrioritySummary(summaryResult.value);
      } else {
        console.error(
          "Unable to load monitoring-priority summary:",
          summaryResult.reason,
        );
        setMonitoringPrioritySummary(null);
      }

      if (freshnessResult.status === "fulfilled") {
        setMonitoringPriorityFreshness(freshnessResult.value);
      } else {
        console.error(
          "Unable to check monitoring-priority freshness:",
          freshnessResult.reason,
        );
        setMonitoringPriorityFreshness(null);
      }

      setMonitoringPriorityLoading(false);
    }

    loadMonitoringPriority();

    return () => {
      active = false;
    };
  }, [hasMonitoringPriority, refreshKey, monitoringPriorityRefreshKey, scope]);

  async function refreshMonitoringPriorities() {
    try {
      setMonitoringPriorityRefreshing(true);
      setMonitoringPriorityRefreshMessage(null);
      await regenerateMonitoringPriorities(scope);
      setMonitoringPriorityRefreshMessage(
        "Monitoring priorities refreshed successfully.",
      );
      setMonitoringPriorityRefreshKey((current) => current + 1);
    } catch (err) {
      console.error("Monitoring-priority refresh failed:", err);
      setMonitoringPriorityRefreshMessage(
        err.message ||
          "Refresh failed. The previous snapshot remains available.",
      );
    } finally {
      setMonitoringPriorityRefreshing(false);
    }
  }

  const filteredObservations = useMemo(() => {
    return observations.filter((observation) => {
      if (filters.species && observation.species !== filters.species) {
        return false;
      }

      if (
        filters.ecological_status &&
        observation.ecological_status !== filters.ecological_status
      ) {
        return false;
      }

      if (filters.priority && observation.priority !== filters.priority) {
        return false;
      }

      if (
        filters.verification_status &&
        observation.verification_status !== filters.verification_status
      ) {
        return false;
      }

      return true;
    });
  }, [observations, filters]);

  const stats = {
    total: filteredObservations.length,

    invasive: filteredObservations.filter(
      (item) => item.ecological_status === "INVASIVE",
    ).length,

    unresolved: filteredObservations.filter(
      (item) => item.identification_status === "unresolved",
    ).length,

    review: filteredObservations.filter(
      (item) => item.priority === "HIGH" || item.priority === "REVIEW",
    ).length,
  };

  if (loading) {
    return <div className="center-message">Loading sightings...</div>;
  }

  if (error) {
    return <div className="center-message error">{error}</div>;
  }

  return (
    <div className="map-page h-full overflow-hidden">
      {/* =========================================
        PLATFORM-WIDE MONITORING SUMMARY
    ========================================= */}

      {summary && (
        <section className="monitoring-summary">
          <div className="summary-card">
            <span>Total sightings</span>
            <strong>{summary.total_observations}</strong>
          </div>

          <div className="summary-card">
            <span>Invasive sightings</span>
            <strong>{summary.invasive_observations}</strong>
          </div>

          <div className="summary-card">
            <span>Pending review</span>
            <strong>{summary.pending_review}</strong>
          </div>

          <div className="summary-card">
            <span>AI unresolved</span>
            <strong>{summary.unresolved_identifications}</strong>
          </div>

          <div className="summary-card">
            <span>Active areas</span>
            <strong>{summary.active_hotspots}</strong>
          </div>

          <div className="summary-card">
            <span>Species observed</span>
            <strong>{summary.species_observed}</strong>
          </div>
        </section>
      )}

      {/* =========================================
        MAIN 3-COLUMN WORKSPACE
    ========================================= */}

      <div className="dashboard-page !block !h-full !min-h-0 relative">
        {/* LEFT SIDEBAR */}

        <div className="dashboard-sidebar hidden">
          <MapFilters
            filters={filters}
            onChange={setFilters}
            observations={observations}
          />

          <section className="map-layers" aria-label="Map layers">
            <h3>Map layers</h3>

            <label>
              <input
                type="checkbox"
                checked={visibleLayers.sightings}
                onChange={() => toggleLayer("sightings")}
              />
              Sightings
            </label>

            <label>
              <input
                type="checkbox"
                checked={visibleLayers.hotspots}
                onChange={() => toggleLayer("hotspots")}
              />
              Hotspots
            </label>

            <label>
              <input
                type="checkbox"
                checked={visibleLayers.suitability}
                onChange={() => toggleLayer("suitability")}
              />
              Habitat suitability
            </label>

            <label>
              <input
                type="checkbox"
                checked={monitoringPriorityVisible}
                onChange={() =>
                  setMonitoringPriorityVisible((current) => !current)
                }
              />
              Monitoring priority
            </label>
          </section>

          {(hotspotError || summaryError || suitabilityError) && (
            <section
              className="map-service-warnings"
              aria-label="Unavailable map data"
            >
              <h3>Data availability</h3>
              {hotspotError && <p>{hotspotError}</p>}
              {summaryError && <p>{summaryError}</p>}
              {suitabilityError && <p>{suitabilityError}</p>}
            </section>
          )}

          {monitoringPriorityVisible && (
            <section className="monitoring-priority-summary">
              <h3>Monitoring priority</h3>

              {monitoringPriorityLoading ? (
                <p>Loading recommendation snapshot...</p>
              ) : monitoringPriorityError ? (
                <p className="monitoring-priority-error">
                  {monitoringPriorityError}
                </p>
              ) : (
                <>
                  <p>{monitoringPriorityCells.length} recommendation cells</p>
                  {monitoringPrioritySummary?.diagnostics
                    ?.priority_band_counts && (
                    <div className="monitoring-priority-band-counts">
                      {[
                        ["Very low", "VERY_LOW"],
                        ["Low", "LOW"],
                        ["Moderate", "MODERATE"],
                        ["High", "HIGH"],
                        ["Very high", "VERY_HIGH"],
                      ].map(([label, band]) => (
                        <span key={band}>
                          {label}:{" "}
                          {monitoringPrioritySummary.diagnostics
                            .priority_band_counts[band] || 0}
                        </span>
                      ))}
                    </div>
                  )}
                  {monitoringPrioritySummary?.generated_at && (
                    <p>
                      Recommendation snapshot generated:{" "}
                      {formatMapTimestamp(
                        monitoringPrioritySummary.generated_at,
                      )}
                    </p>
                  )}

                  <SnapshotFreshness freshness={monitoringPriorityFreshness} />

                  {["STALE", "UNKNOWN"].includes(
                    monitoringPriorityFreshness?.status,
                  ) &&
                    canRegenerate && (
                      <button
                        type="button"
                        className="monitoring-priority-refresh-button"
                        disabled={monitoringPriorityRefreshing}
                        onClick={refreshMonitoringPriorities}
                      >
                        {monitoringPriorityRefreshing
                          ? "Refreshing monitoring priorities..."
                          : "Refresh monitoring priorities"}
                      </button>
                    )}

                  {monitoringPriorityRefreshMessage && (
                    <p
                      className="monitoring-priority-refresh-message"
                      role="status"
                    >
                      {monitoringPriorityRefreshMessage}
                    </p>
                  )}
                </>
              )}
            </section>
          )}

          {summary?.species_signals?.length > 0 && (
            <section className="monitoring-signals">
              <div className="monitoring-signals-header">
                <h3>Monitoring Signals</h3>

                <span>{summary.species_signals.length}</span>
              </div>

              <div className="signal-list">
                {summary.species_signals.map((signal, index) => (
                  <div
                    className={`signal-item ${signalEmphasisClass(
                      signal.monitoring_interpretation,
                    )}`.trim()}
                    key={`${signal.species}-${signal.latitude}-${signal.longitude}-${index}`}
                  >
                    <div className="signal-species">
                      <strong>{signal.species}</strong>

                      <span className="signal-interpretation">
                        {MONITORING_INTERPRETATION_LABELS[
                          signal.monitoring_interpretation
                        ] || "Monitoring activity"}
                      </span>
                    </div>

                    <div className="signal-details">
                      <strong>{signal.past_7_days} reports / 7d</strong>

                      <span>
                        {signal.evidence?.confirmed || 0} confirmed
                        {" · "}
                        {signal.evidence?.ai_supported || 0} AI-supported
                      </span>
                    </div>

                    <div className="signal-context">
                      <span>
                        Historical context:{" "}
                        {REGIONAL_CONTEXT_LABELS[signal.regional_context] ||
                          "insufficient data"}
                      </span>

                      <span>
                        {Number(signal.latitude).toFixed(2)},{" "}
                        {Number(signal.longitude).toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="summary-block">
            <h3>Current view</h3>

            <div className="summary-grid">
              <div>
                <strong>{stats.total}</strong>
                <span>Sightings</span>
              </div>

              <div>
                <strong>{stats.invasive}</strong>
                <span>Invasive</span>
              </div>

              <div>
                <strong>{stats.unresolved}</strong>
                <span>Unresolved</span>
              </div>

              <div>
                <strong>{stats.review}</strong>
                <span>Review</span>
              </div>
            </div>
          </div>
        </div>

        {/* MAP */}

        <div className="dashboard-map !h-full !w-full relative">
          <MarineMap
            key={`${activeRegion}-${activeJurisdiction}`}
            center={[
              jurisdiction.center_latitude,
              jurisdiction.center_longitude,
            ]}
            zoom={jurisdiction.default_zoom}
            observations={filteredObservations}
            hotspots={hotspots}
            suitabilityCells={suitabilityCells}
            monitoringPriorityCells={monitoringPriorityCells}
            monitoringPriorityVisible={monitoringPriorityVisible}
            selectedPriorityCellId={selectedPriorityCell?.grid_cell_id}
            visibleLayers={visibleLayers}
            onSelectObservation={(observation) => {
              setSelectedPriorityCell(null);
              setSelectedSuitabilityCell(null);
              handleObservationSelect(observation);
            }}
            onSelectPriorityCell={(cell) => {
              setSelectedObservation(null);
              setObservationDetails(null);
              setSelectedSuitabilityCell(null);
              setSelectedPriorityCell(cell);
            }}
            onSelectSuitabilityCell={(cell) => {
              setSelectedObservation(null);
              setObservationDetails(null);
              setSelectedPriorityCell(null);
              setSelectedSuitabilityCell(cell);
            }}
          />

          <MonitoringMapToolbar
            filters={filters}
            onFiltersChange={setFilters}
            observations={observations}
            visibleLayers={visibleLayers}
            toggleLayer={toggleLayer}
            monitoringPriorityVisible={monitoringPriorityVisible}
            setMonitoringPriorityVisible={setMonitoringPriorityVisible}
            activeControl={activeMapControl}
            setActiveControl={setActiveMapControl}
            mapMode={mapMode}
            onMapModeChange={(mode) => {
              setMapMode(mode);
              setVisibleLayers({
                sightings: true,
                hotspots: true,
                suitability: false,
              });
              setMonitoringPriorityVisible(mode === "MONITORING_PRIORITY");
            }}
            summary={summary}
            stats={stats}
            freshness={monitoringPriorityFreshness}
            prioritySummary={monitoringPrioritySummary}
            priorityLoading={monitoringPriorityLoading}
            priorityError={monitoringPriorityError}
            refreshing={monitoringPriorityRefreshing}
            refreshMessage={monitoringPriorityRefreshMessage}
            onRefresh={refreshMonitoringPriorities}
            canRefresh={canRegenerate}
            hasSuitability={hasSuitability}
            hasMonitoringPriority={hasMonitoringPriority}
          />

          <AdaptiveMapLegend
            visibleLayers={visibleLayers}
            monitoringPriorityVisible={monitoringPriorityVisible}
          />

          {(hotspotError ||
            summaryError ||
            suitabilityError ||
            monitoringPriorityError) && (
            <div
              className="absolute bottom-4 left-4 z-[850] max-w-xs rounded-lg border border-amber-200 bg-white/95 p-3 text-xs text-amber-800 shadow-lg"
              role="status"
            >
              {hotspotError ||
                suitabilityError ||
                monitoringPriorityError ||
                summaryError}
            </div>
          )}
        </div>

        {/* OBSERVATION DETAILS */}

        {(selectedPriorityCell ||
          selectedSuitabilityCell ||
          selectedObservation) && (
          <aside className="absolute inset-y-0 right-0 z-[1050] w-full overflow-y-auto border-l border-app-border bg-white shadow-2xl sm:w-[390px]">
            {selectedPriorityCell ? (
              <PriorityCellPanel
                cell={selectedPriorityCell}
                freshness={monitoringPriorityFreshness}
                onClose={() => setSelectedPriorityCell(null)}
                onCreateInvestigation={
                  canManageInvestigations
                    ? () =>
                        navigate(
                          `/region/${activeRegion}/${activeJurisdiction}/investigations?source_type=MONITORING_PRIORITY&generation_id=${encodeURIComponent(selectedPriorityCell.generation_id)}&cell_id=${encodeURIComponent(selectedPriorityCell.grid_cell_id)}&latitude=${encodeURIComponent(selectedPriorityCell.latitude)}&longitude=${encodeURIComponent(selectedPriorityCell.longitude)}`,
                        )
                    : null
                }
              />
            ) : selectedSuitabilityCell ? (
              <SuitabilityCellPanel
                cell={selectedSuitabilityCell}
                onClose={() => setSelectedSuitabilityCell(null)}
              />
            ) : (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedObservation(null);
                    setObservationDetails(null);
                  }}
                  className="absolute right-4 top-4 z-10 grid h-8 w-8 place-items-center rounded-full border border-app-border bg-white text-lg shadow-sm"
                  aria-label="Close observation details"
                >
                  ×
                </button>
                <ObservationPanel
                  observation={selectedObservation}
                  details={observationDetails}
                  loading={detailsLoading}
                />
              </div>
            )}
            {!selectedPriorityCell &&
              !selectedSuitabilityCell &&
              selectedObservation &&
              canManageInvestigations && (
                <button
                  type="button"
                  onClick={() =>
                    navigate(
                      `/region/${activeRegion}/${activeJurisdiction}/investigations?source_type=OBSERVATION&observation_id=${encodeURIComponent(selectedObservation.id)}&latitude=${encodeURIComponent(selectedObservation.latitude)}&longitude=${encodeURIComponent(selectedObservation.longitude)}`,
                    )
                  }
                  className="mx-6 mb-6 w-[calc(100%-3rem)] rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white"
                >
                  Create investigation
                </button>
              )}
          </aside>
        )}
      </div>
    </div>
  );
}

function PriorityCellPanel({
  cell,
  freshness,
  onClose,
  onCreateInvestigation,
}) {
  const reasons = Array.isArray(cell.reason_codes) ? cell.reason_codes : [];
  return (
    <div className="priority-detail-drawer">
      <div className="drawer-kicker">
        <span>Monitoring priority</span>
        <button
          onClick={onClose}
          aria-label="Close monitoring priority details"
        >
          ×
        </button>
      </div>
      <h2>{readableMapLabel(cell.priority_band)} priority area</h2>
      <p>
        {Number(cell.latitude).toFixed(3)}, {Number(cell.longitude).toFixed(3)}
      </p>
      <div className="priority-score-card">
        <span>Priority score</span>
        <strong>{formatMapScore(cell.monitoring_priority_score)}</strong>
        <i
          style={{
            width: `${Math.max(0, Math.min(100, Number(cell.monitoring_priority_score || 0) * 100))}%`,
          }}
        />
      </div>
      <section>
        <h3>Why this area?</h3>
        <DetailMetric
          label="Habitat suitability"
          value={formatMapScore(cell.suitability_score)}
        />
        <DetailMetric
          label="Observation evidence"
          value={formatMapScore(cell.current_evidence_score)}
        />
        <DetailMetric
          label="Nearest qualifying evidence"
          value={formatMapDistance(
            cell.nearest_evidence_km ??
              cell.distance_from_nearest_current_evidence_km,
          )}
        />
        {cell.contributing_observation_id != null && (
          <DetailMetric
            label="Contributing observation"
            value={`#${cell.contributing_observation_id}`}
          />
        )}
      </section>
      {reasons.length > 0 && (
        <section>
          <h3>Prioritization context</h3>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>
                {REASON_LABELS[reason] || readableMapLabel(reason)}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="drawer-detail">
        <h3>Evidence breakdown</h3>
        <DetailMetric
          label="Verification weight"
          value={formatMapScore(cell.contributing_verification_weight)}
        />
        <DetailMetric
          label="Recency weight"
          value={formatMapScore(cell.contributing_recency_weight)}
        />
        <DetailMetric
          label="Distance weight"
          value={formatMapScore(cell.contributing_distance_weight)}
        />
        <DetailMetric
          label="Evidence score"
          value={formatMapScore(cell.contributing_evidence_score)}
        />
      </section>
      <section>
        <h3>Monitoring snapshot</h3>
        <DetailMetric label="Status" value={freshnessLabel(freshness)} />
        <DetailMetric
          label="Generated"
          value={formatMapTimestamp(cell.generated_at)}
        />
        <DetailMetric
          label="Version"
          value={cell.prediction_version || "Unavailable"}
        />
      </section>
      <div className="scientific-disclaimer">
        Prioritized using habitat suitability and recent observation evidence.
        <br />
        <strong>
          Monitoring prioritization; not a spread, invasion, or occurrence
          probability.
        </strong>
      </div>
      {onCreateInvestigation && (
        <button
          type="button"
          onClick={onCreateInvestigation}
          className="w-full rounded-lg bg-teal-700 px-4 py-3 text-sm font-bold text-white"
        >
          Create investigation
        </button>
      )}
    </div>
  );
}

function SuitabilityCellPanel({ cell, onClose }) {
  return (
    <div className="p-6">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-[.12em] text-teal-700">
          Habitat suitability
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close habitat suitability details"
          className="grid h-8 w-8 place-items-center rounded-full border border-app-border"
        >
          ×
        </button>
      </div>
      <h2 className="mt-3 text-xl font-bold">
        {readableMapLabel(cell.suitability_band)}
      </h2>
      <p className="mt-1 text-sm text-app-muted">
        {Number(cell.latitude).toFixed(3)}, {Number(cell.longitude).toFixed(3)}
      </p>
      <div className="mt-5 rounded-xl border border-teal-200 bg-teal-50 p-4">
        <span className="text-xs text-app-muted">
          Relative suitability score
        </span>
        <strong className="float-right text-2xl text-teal-700">
          {formatMapScore(cell.suitability_score)}
        </strong>
      </div>
      <section className="mt-6 border-t border-app-border pt-4">
        <DetailMetric label="Species" value="Pterois volitans" />
        <DetailMetric label="Model" value="Suitability v3" />
        <DetailMetric label="Grid size" value={`${cell.grid_size || 0.1}°`} />
      </section>
      <div className="scientific-disclaimer">
        Relative habitat suitability; not a spread or occurrence probability.
      </div>
    </div>
  );
}

function DetailMetric({ label, value }) {
  return (
    <div className="drawer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
function formatMapScore(value) {
  return value == null ? "Unavailable" : Number(value).toFixed(3);
}
function formatMapDistance(value) {
  return value == null ? "Unavailable" : `${Number(value).toFixed(1)} km`;
}
function readableMapLabel(value) {
  return value
    ? String(value)
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/\b\w/g, (c) => c.toUpperCase())
    : "Unavailable";
}

function MonitoringMapToolbar({
  filters,
  onFiltersChange,
  observations,
  visibleLayers,
  toggleLayer,
  monitoringPriorityVisible,
  setMonitoringPriorityVisible,
  activeControl,
  setActiveControl,
  mapMode,
  onMapModeChange,
  summary,
  stats,
  freshness,
  prioritySummary,
  priorityLoading,
  priorityError,
  refreshing,
  refreshMessage,
  onRefresh,
  canRefresh,
  hasSuitability,
  hasMonitoringPriority,
}) {
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const toggleControl = (name) =>
    setActiveControl(activeControl === name ? null : name);
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-[900] p-3">
      <div className="pointer-events-auto flex max-w-max flex-wrap items-center gap-2 rounded-xl border border-app-border bg-white/95 p-2 shadow-lg backdrop-blur">
        <select
          aria-label="Species"
          className="rounded-lg border border-app-border px-3 py-2 text-xs font-semibold"
          value={filters.species}
          onChange={(event) =>
            onFiltersChange({ ...filters, species: event.target.value })
          }
        >
          <option value="">All species</option>
          {[
            ...new Set(
              observations.map((item) => item.species).filter(Boolean),
            ),
          ]
            .sort()
            .map((species) => (
              <option key={species}>{species}</option>
            ))}
        </select>
        <button
          type="button"
          onClick={() => toggleControl("filters")}
          aria-expanded={activeControl === "filters"}
          className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold"
        >
          Filters{activeFilterCount ? ` · ${activeFilterCount}` : ""}
        </button>
        <button
          type="button"
          onClick={() => toggleControl("layers")}
          aria-expanded={activeControl === "layers"}
          className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold"
        >
          Layers
        </button>
        <button
          type="button"
          onClick={() => toggleControl("activity")}
          aria-expanded={activeControl === "activity"}
          className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold"
        >
          Monitoring activity
        </button>
        <div className="flex rounded-lg bg-slate-100 p-1" aria-label="Map mode">
          <ModeButton
            active={mapMode === "OBSERVATIONS"}
            onClick={() => onMapModeChange("OBSERVATIONS")}
          >
            Observations
          </ModeButton>
          {hasMonitoringPriority && (
            <ModeButton
              active={mapMode === "MONITORING_PRIORITY"}
              onClick={() => onMapModeChange("MONITORING_PRIORITY")}
            >
              Monitoring priority
            </ModeButton>
          )}
        </div>
      </div>
      {activeControl === "filters" && (
        <MapControlPanel title="Filters" onClose={() => setActiveControl(null)}>
          <MapFilters
            filters={filters}
            onChange={onFiltersChange}
            observations={observations}
          />
        </MapControlPanel>
      )}
      {activeControl === "layers" && (
        <MapControlPanel
          title="Map layers"
          onClose={() => setActiveControl(null)}
        >
          <div className="space-y-3">
            <LayerToggle
              checked={visibleLayers.sightings}
              onChange={() => toggleLayer("sightings")}
              label="Sightings"
              note="Individual observation reports"
            />
            <LayerToggle
              checked={visibleLayers.hotspots}
              onChange={() => toggleLayer("hotspots")}
              label="Observation hotspots"
              note="Recent observed activity concentration"
            />
            {hasSuitability && (
              <LayerToggle
                checked={visibleLayers.suitability}
                onChange={() => toggleLayer("suitability")}
                label="Habitat suitability"
                note="Relative environmental suitability"
              />
            )}
            {hasMonitoringPriority && (
              <LayerToggle
                checked={monitoringPriorityVisible}
                onChange={() => setMonitoringPriorityVisible((value) => !value)}
                label="Monitoring priority"
                note="Areas recommended for monitoring attention"
              />
            )}
            {!hasSuitability && !hasMonitoringPriority && (
              <p className="rounded-lg bg-slate-50 p-3 text-xs text-app-muted">
                Scientific layers are not configured for this jurisdiction.
              </p>
            )}
          </div>
        </MapControlPanel>
      )}
      {activeControl === "activity" && (
        <MapControlPanel
          title="Monitoring activity"
          onClose={() => setActiveControl(null)}
        >
          <div className="grid grid-cols-4 gap-2">
            <MiniStat label="Sightings" value={stats.total} />
            <MiniStat label="Invasive" value={stats.invasive} />
            <MiniStat label="Unresolved" value={stats.unresolved} />
            <MiniStat label="Review" value={stats.review} />
          </div>
          {summary?.species_signals?.slice(0, 4).map((signal, index) => (
            <div
              key={`${signal.species}-${index}`}
              className="mt-3 border-t border-app-border pt-3"
            >
              <strong className="block text-sm">{signal.species}</strong>
              <span className="block text-xs text-app-muted">
                {MONITORING_INTERPRETATION_LABELS[
                  signal.monitoring_interpretation
                ] || "Monitoring activity"}
              </span>
              <span className="mt-1 block text-xs">
                {signal.past_7_days} reports / 7d ·{" "}
                {signal.evidence?.confirmed || 0} confirmed ·{" "}
                {signal.evidence?.ai_supported || 0} AI-supported
              </span>
            </div>
          ))}
        </MapControlPanel>
      )}
      {monitoringPriorityVisible && (
        <div className="pointer-events-auto absolute right-3 top-3 hidden max-w-[260px] rounded-xl border border-purple-200 bg-white/95 p-3 shadow-lg md:block">
          <strong className="text-xs">Monitoring snapshot</strong>
          <p className="mt-1 text-xs text-app-muted">
            {priorityLoading
              ? "Loading…"
              : priorityError || freshnessLabel(freshness)}
          </p>
          {prioritySummary?.generated_at && (
            <p className="mt-1 text-[11px] text-app-muted">
              Generated {formatMapTimestamp(prioritySummary.generated_at)}
            </p>
          )}
          {canRefresh && ["STALE", "UNKNOWN"].includes(freshness?.status) && (
            <button
              type="button"
              disabled={refreshing}
              onClick={onRefresh}
              className="mt-2 rounded-md bg-priority-700 px-3 py-1.5 text-xs font-bold text-white"
            >
              {refreshing ? "Refreshing…" : "Refresh monitoring priorities"}
            </button>
          )}
          {refreshMessage && (
            <p className="mt-2 text-[11px]" role="status">
              {refreshMessage}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ModeButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-2.5 py-1.5 text-[11px] font-bold ${active ? "bg-white text-teal-700 shadow-sm" : "text-app-muted"}`}
    >
      {children}
    </button>
  );
}
function MapControlPanel({ title, onClose, children }) {
  return (
    <section className="pointer-events-auto mt-2 max-h-[70vh] w-[min(340px,calc(100vw-24px))] overflow-y-auto rounded-xl border border-app-border bg-white p-4 shadow-xl">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold">{title}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="grid h-7 w-7 place-items-center rounded-full hover:bg-slate-100"
        >
          ×
        </button>
      </div>
      {children}
    </section>
  );
}
function LayerToggle({ checked, onChange, label, note }) {
  return (
    <label className="flex cursor-pointer gap-3">
      <input
        type="checkbox"
        className="mt-1 accent-teal-700"
        checked={checked}
        onChange={onChange}
      />
      <span>
        <strong className="block text-sm">{label}</strong>
        <small className="text-app-muted">{note}</small>
      </span>
    </label>
  );
}
function MiniStat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2 text-center">
      <strong className="block text-lg">{value}</strong>
      <span className="text-[10px] text-app-muted">{label}</span>
    </div>
  );
}
function freshnessLabel(freshness) {
  return freshness?.status === "FRESH"
    ? "Up to date"
    : freshness?.status === "STALE"
      ? "Update available"
      : "Freshness unknown";
}

function AdaptiveMapLegend({ visibleLayers, monitoringPriorityVisible }) {
  const priorityBands = [
    ["Very low", "bg-purple-100/30 ring-purple-200/30"],
    ["Low", "bg-purple-200/50 ring-purple-300/40"],
    ["Moderate", "bg-purple-400/60 ring-purple-500/60"],
    ["High", "bg-purple-600/75 ring-purple-700/70"],
    ["Very high", "bg-purple-800/90 ring-purple-900/90"],
  ];
  return (
    <div className="pointer-events-none absolute bottom-4 left-4 z-[800] max-w-[250px] rounded-xl border border-app-border bg-white/95 p-3 text-[11px] shadow-lg">
      {visibleLayers.sightings && (
        <div>
          <strong className="block text-xs">Observations</strong>
          <span className="mt-1 block">
            ● Expert confirmed · ◇ AI-supported · ? Needs review
          </span>
        </div>
      )}
      {monitoringPriorityVisible && (
        <div className="mt-2">
          <strong className="block text-xs">Monitoring priority</strong>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5">
            {priorityBands.map(([label, classes]) => (
              <span key={label} className="flex items-center gap-1.5">
                <i className={`h-2.5 w-2.5 rounded-sm ring-1 ${classes}`} />
                {label}
              </span>
            ))}
          </div>
          <small className="mt-1.5 block text-app-muted">
            Stronger purple indicates greater monitoring attention.
          </small>
        </div>
      )}
      {visibleLayers.suitability && (
        <div className="mt-2">
          <strong className="block text-xs">Habitat suitability</strong>
          <div className="mt-1 h-2 rounded-full bg-gradient-to-r from-blue-200 via-amber-300 to-red-500" />
          <span className="flex justify-between">
            <i>Low</i>
            <i>High</i>
          </span>
        </div>
      )}
    </div>
  );
}

function formatMapTimestamp(value) {
  const timestampValue = /(?:Z|[+-]\d\d:\d\d)$/i.test(value)
    ? value
    : `${value}Z`;
  const timestamp = new Date(timestampValue);

  if (Number.isNaN(timestamp.getTime())) {
    return "Unavailable";
  }

  return timestamp.toLocaleString();
}

function SnapshotFreshness({ freshness }) {
  if (!freshness) {
    return (
      <div className="snapshot-freshness snapshot-freshness--unknown">
        <strong>Status: Freshness unknown</strong>
        <span>Snapshot freshness could not be checked completely.</span>
      </div>
    );
  }

  const status =
    {
      FRESH: "Up to date",
      STALE: "Update available",
      UNKNOWN: "Freshness unknown",
    }[freshness.status] || "Freshness unknown";

  const reason =
    freshness.status === "STALE"
      ? freshness.reasons?.includes("RECENCY_BUCKET_CHANGED")
        ? "Observation evidence has moved into a different recency period since this snapshot was generated."
        : "New or updated observation evidence is available since this monitoring snapshot was generated."
      : freshness.status === "UNKNOWN"
        ? "Older verification or evidence metadata does not contain enough timing information for a complete comparison."
        : "No relevant evidence changes are known since this snapshot was generated.";

  return (
    <div
      className={`snapshot-freshness snapshot-freshness--${freshness.status.toLowerCase()}`}
    >
      <strong>Status: {status}</strong>
      <span>{reason}</span>
    </div>
  );
}
