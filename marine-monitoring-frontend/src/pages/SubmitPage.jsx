import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  analyzeObservation,
  getImageUrl,
  resolveJurisdiction,
  getPublicJurisdiction,
  getPublicSpeciesDetail,
} from "../services/api";
import SightingLocationPicker from "../components/SightingLocationPicker";
import { adjustedLocation, confirmedLocation, deviceLocationProposal } from "../utils/sightingLocation";

function readableLabel(value) {
  if (!value) {
    return "Unavailable";
  }

  return String(value)
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function SubmitPage({ onObservationCreated }) {
  const [searchParams] = useSearchParams();
  const suggestedTaxonId = searchParams.get("taxon_id");
  const expectedJurisdictionId = searchParams.get("jurisdiction_id");
  const [reportingContext,setReportingContext]=useState(null);
  useEffect(()=>{if(!expectedJurisdictionId)return; Promise.all([getPublicJurisdiction(expectedJurisdictionId),suggestedTaxonId?getPublicSpeciesDetail(expectedJurisdictionId,suggestedTaxonId):Promise.resolve(null)]).then(([jurisdiction,taxon])=>setReportingContext({jurisdiction,taxon})).catch(()=>setReportingContext(null));},[expectedJurisdictionId,suggestedTaxonId]);
  const [image, setImage] = useState(null);

  const preview = useMemo(
    () => (image ? URL.createObjectURL(image) : null),
    [image],
  );

  const [latitude, setLatitude] = useState("");

  const [longitude, setLongitude] = useState("");

  const [locationAccuracy, setLocationAccuracy] = useState(null);
  const [locationSource, setLocationSource] = useState("MANUAL");
  const [locationCapturedAt, setLocationCapturedAt] = useState(null);
  const [resolution, setResolution] = useState(null);
  const [locationConfirmed, setLocationConfirmed] = useState(false);
  const [locationPickerVisible, setLocationPickerVisible] = useState(false);
  const [locating, setLocating] = useState(false);
  const [resolvingLocation, setResolvingLocation] = useState(false);

  const [submitting, setSubmitting] = useState(false);

  const [error, setError] = useState(null);

  const [result, setResult] = useState(null);

  // ==========================================================
  // IMAGE PREVIEW
  // ==========================================================

  useEffect(() => {
    if (!preview) return undefined;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  // ==========================================================
  // BROWSER LOCATION
  // ==========================================================

  function useCurrentLocation() {
    setError(null);

    if (!navigator.geolocation) {
      setError("Current location is unavailable. Choose the sighting location on the map or enter coordinates manually.");
      setLocationPickerVisible(true);
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        applyLocation(deviceLocationProposal(position));
        setLocationPickerVisible(true);
        setLocating(false);
      },

      (locationError) => {
        console.error(locationError);
        setLocating(false);
        setLocationPickerVisible(true);
        setError(locationError.code === 1
          ? "Location permission was denied. Choose the sighting location on the map or enter coordinates manually."
          : locationError.code === 3
            ? "Location request timed out. Try again or choose the sighting location manually."
            : "Current location is unavailable. Choose the sighting location on the map or enter coordinates manually.");
      },

      {
        enableHighAccuracy: true,
        timeout: 10000,
      },
    );
  }

  function applyLocation(location) {
    setLatitude(location.latitude);
    setLongitude(location.longitude);
    setLocationSource(location.source);
    setLocationAccuracy(location.accuracy);
    setLocationCapturedAt(location.capturedAt);
    setLocationConfirmed(location.confirmed);
    setResolution(location.resolution);
  }

  function changeManualCoordinate(field, value) {
    applyLocation(adjustedLocation(
      field === "latitude" ? value : latitude,
      field === "longitude" ? value : longitude,
      "MANUAL",
    ));
  }

  function selectOnMap(nextLatitude, nextLongitude) {
    applyLocation(adjustedLocation(
      Number(nextLatitude).toFixed(6),
      Number(nextLongitude).toFixed(6),
      "MAP_SELECTED",
    ));
  }

  async function confirmLocation() {
    setError(null);
    setResolvingLocation(true);
    try {
      const data = await resolveJurisdiction(latitude, longitude);
      const confirmed = confirmedLocation({
        latitude,
        longitude,
        source: locationSource,
        accuracy: locationAccuracy,
        capturedAt: locationCapturedAt,
      }, data);
      setLocationConfirmed(confirmed.confirmed);
      setResolution(confirmed.resolution);
      if (data.status === "NO_CONFIGURED_JURISDICTION")
        setError(
          "This sighting location is not currently covered by an active monitoring jurisdiction.",
        );
      if (data.status === "AMBIGUOUS")
        setError(
          "We couldn't determine a single monitoring jurisdiction for this sighting location.",
        );
    } catch {
      setResolution(null);
      setLocationConfirmed(false);
      setError(
        "We couldn't verify the monitoring jurisdiction. Please try again.",
      );
    } finally {
      setResolvingLocation(false);
    }
  }

  // ==========================================================
  // SUBMIT
  // ==========================================================

  async function handleSubmit(event) {
    event.preventDefault();

    setError(null);
    setResult(null);

    if (!image) {
      setError("Please select an image.");

      return;
    }

    if (latitude === "" || longitude === "") {
      setError("Latitude and longitude are required.");

      return;
    }
    if (!locationConfirmed || resolution?.status !== "RESOLVED") {
      setError("Confirm the sighting location before submitting.");
      return;
    }

    try {
      setSubmitting(true);

      const data = await analyzeObservation({
        image,
        latitude,
        longitude,
        locationAccuracy,
        locationCapturedAt,
        locationSource,
        expectedJurisdictionId,
        reporterSuggestedTaxonId: suggestedTaxonId,
      });

      setResult(data);

      if (onObservationCreated) {
        onObservationCreated();
      }
    } catch (err) {
      console.error(err);

      setError(err.message || "Unable to submit observation.");
    } finally {
      setSubmitting(false);
    }
  }

  // ==========================================================
  // VIEW
  // ==========================================================

  return (
    <div className="submit-page">
      <div className="submit-form-area">
        <div className="page-heading">
          <h2>Submit observation</h2>

          <p>Upload a marine sighting and provide the observation location.</p>
          {expectedJurisdictionId && <div className="mt-2 rounded-lg bg-teal-50 p-3 text-sm text-teal-900"><p><strong>Reporting in:</strong> {reportingContext?.jurisdiction?.name||"Validating jurisdiction…"}</p><p><strong>Suggested species:</strong> {reportingContext?.taxon?`${reportingContext.taxon.scientific_name}${reportingContext.taxon.common_name?` · ${reportingContext.taxon.common_name}`:""}`:"Not specified"}</p><p className="mt-1 text-xs">This suggestion does not determine the final identification.</p></div>}
        </div>

        <form onSubmit={handleSubmit} className="observation-form">
          <label className="upload-box">
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0];

                setImage(file || null);

                setResult(null);
              }}
            />

            {preview ? (
              <img
                src={preview}
                alt="Observation preview"
                className="upload-preview"
              />
            ) : (
              <div className="upload-placeholder">
                <strong>Choose marine image</strong>

                <span>JPG, PNG or WEBP</span>
              </div>
            )}
          </label>

          <div className="location-heading"><h3>Where did you see this?</h3></div>

          <p className="location-guidance">
            Add the location where the animal was observed. Your current
            location can help us start, but you can adjust the sighting
            position before submitting.
          </p>

          <div className="flex flex-col gap-2 sm:flex-row">
            <button type="button" className="secondary-button" onClick={useCurrentLocation} disabled={locating}>
              {locating ? "Getting current location..." : "Use my current location"}
            </button>
            <button type="button" className="secondary-button" onClick={() => setLocationPickerVisible(true)}>
              Choose location manually
            </button>
          </div>

          {locationPickerVisible && (
            <SightingLocationPicker latitude={latitude} longitude={longitude} onSelect={selectOnMap} />
          )}

          <div className="coordinate-grid">
            <label>
              Latitude
              <input
                type="number"
                step="any"
                min="-90"
                max="90"
                value={latitude}
                onChange={(event) => changeManualCoordinate("latitude", event.target.value)}
                placeholder="18.4300"
              />
            </label>

            <label>
              Longitude
              <input
                type="number"
                step="any"
                min="-180"
                max="180"
                value={longitude}
                onChange={(event) => changeManualCoordinate("longitude", event.target.value)}
                placeholder="-77.1000"
              />
            </label>
          </div>

          {latitude !== "" && longitude !== "" && (
            <div className="location-confirmation" role="status">
              <strong>{locationConfirmed ? "Sighting location confirmed" : "Sighting location ready to confirm"}</strong>
              <span>
                {latitude}, {longitude}
                {locationAccuracy != null
                  ? ` · accuracy approximately ±${Math.round(locationAccuracy)} m`
                  : locationSource === "MAP_SELECTED" ? " · selected on map" : " · manually entered"}
              </span>
              {resolution?.status === "RESOLVED" && <span><strong>Monitoring jurisdiction:</strong> {resolution.jurisdiction.name}</span>}
              <span className="text-xs text-slate-600">Place the marker where the sighting occurred, not where you are submitting the report from.</span>
              <button type="button" className="secondary-button" disabled={resolvingLocation} onClick={confirmLocation}>{resolvingLocation ? "Checking jurisdiction..." : "Confirm sighting location"}</button>
            </div>
          )}

          {error && <div className="form-error">{error}</div>}

          <button
            type="submit"
            className="primary-button"
            disabled={submitting}
          >
            {submitting ? "Analyzing observation..." : "Analyze observation"}
          </button>
        </form>
      </div>

      <aside className="submission-result">
        {!result && (
          <div className="empty-result">
            <h3>Analysis result</h3>

            <p>Submit a sighting to see the AI and regional analysis.</p>
          </div>
        )}

        {result && <ResultPanel result={result} />}
      </aside>
    </div>
  );
}

// ============================================================
// RESULT PANEL
// ============================================================

function ResultPanel({ result }) {
  const identification = result.identification;

  const imageUrl = getImageUrl(result.observation.image_url);

  const displaySpecies = identification.species || "Unresolved observation";

  return (
    <div className="submit-result-panel">
      <span className="observation-id">
        Report {result.submission_reference || "received"}
      </span>

      <p className="reason-box">{result.submission_message || "Your report was received and may be reviewed by an authorized jurisdiction team. Initial AI identification is not final expert verification."}</p>
      {result.reporter_status_token && <a className="inline-block rounded bg-teal-700 px-4 py-2 font-bold text-white" href={`/reporter/status/${result.reporter_status_token}`}>View private report status</a>}

      <h2>{displaySpecies}</h2>

      {imageUrl && (
        <img
          src={imageUrl}
          alt={displaySpecies}
          className="observation-image"
        />
      )}

      <div className="result-status">
        <span>{readableLabel(result.decision)}</span>

        <strong>{result.priority}</strong>
      </div>

      <div className="detail-row">
        <span>Identification</span>

        <strong>{identification.status}</strong>
      </div>

      {identification.species && (
        <div className="detail-row">
          <span>Species</span>

          <strong>{identification.species}</strong>
        </div>
      )}

      {identification.nearest_candidate && (
        <div className="detail-row">
          <span>Nearest candidate</span>

          <strong>{identification.nearest_candidate}</strong>
        </div>
      )}

      <div className="detail-row">
        <span>AI identification score</span>

        <strong>{identification.score?.toFixed(3) ?? "—"}</strong>
      </div>

      <div className="detail-row">
        <span>Ecological status</span>

        <strong>{result.ecological_status}</strong>
      </div>

      <div className="reason-box">{result.reason}</div>
    </div>
  );
}
