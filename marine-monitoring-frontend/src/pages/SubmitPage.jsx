import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { analyzeObservation, getPublicJurisdiction, getPublicSpeciesDetail, resolveJurisdiction } from "../services/api";
import SightingLocationPicker from "../components/SightingLocationPicker";
import { adjustedLocation, confirmedLocation, deviceLocationProposal } from "../utils/sightingLocation";
import { alternativeCandidates, canSubmitObservation, similarityLabel, validateObservationImage } from "../utils/submissionPresentation";

const sourceLabel = (source) => source === "DEVICE_GEOLOCATION" ? "Current location" : source === "MAP_SELECTED" ? "Selected on map" : "Manually entered";

export default function SubmitPage({ onObservationCreated }) {
  const [searchParams] = useSearchParams();
  const suggestedTaxonId = searchParams.get("taxon_id");
  const expectedJurisdictionId = searchParams.get("jurisdiction_id");
  const [reportingContext, setReportingContext] = useState(null);
  const [image, setImage] = useState(null);
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
  const [resultOpen, setResultOpen] = useState(false);
  const fileInput = useRef(null);
  const resultCloseButton = useRef(null);
  const preview = useMemo(() => image ? URL.createObjectURL(image) : null, [image]);
  const readyToSubmit = canSubmitObservation({ image, latitude, longitude, locationConfirmed, resolution, submitting });

  useEffect(() => { if (!expectedJurisdictionId) return; Promise.all([getPublicJurisdiction(expectedJurisdictionId), suggestedTaxonId ? getPublicSpeciesDetail(expectedJurisdictionId, suggestedTaxonId) : Promise.resolve(null)]).then(([jurisdiction, taxon]) => setReportingContext({ jurisdiction, taxon })).catch(() => setReportingContext(null)); }, [expectedJurisdictionId, suggestedTaxonId]);
  useEffect(() => { if (!preview) return undefined; return () => URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => { if (resultOpen) resultCloseButton.current?.focus(); }, [resultOpen]);
  useEffect(() => { const close = (event) => { if (event.key === "Escape") setResultOpen(false); }; window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, []);

  function chooseImage(file) {
    const imageError = file ? validateObservationImage(file) : null;
    if (imageError) { setError(imageError); if (fileInput.current) fileInput.current.value = ""; return; }
    setImage(file || null);
    setResult(null);
    setResultOpen(false);
    setError(null);
  }

  function removeImage() {
    setImage(null);
    setResult(null);
    setResultOpen(false);
    if (fileInput.current) fileInput.current.value = "";
  }

  function applyLocation(location) {
    setLatitude(location.latitude); setLongitude(location.longitude); setLocationSource(location.source);
    setLocationAccuracy(location.accuracy); setLocationCapturedAt(location.capturedAt);
    setLocationConfirmed(location.confirmed); setResolution(location.resolution);
  }

  function useCurrentLocation() {
    setError(null);
    if (!navigator.geolocation) { setError("Current location is unavailable. Choose the sighting location on the map or enter coordinates manually."); setLocationPickerVisible(true); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition((position) => { applyLocation(deviceLocationProposal(position)); setLocationPickerVisible(true); setLocating(false); }, (locationError) => { setLocating(false); setLocationPickerVisible(true); setError(locationError.code === 1 ? "Location permission was denied. Choose the sighting location on the map or enter coordinates manually." : locationError.code === 3 ? "Location request timed out. Try again or choose the sighting location manually." : "Current location is unavailable. Choose the sighting location on the map or enter coordinates manually."); }, { enableHighAccuracy: true, timeout: 10000 });
  }

  function changeManualCoordinate(field, value) { applyLocation(adjustedLocation(field === "latitude" ? value : latitude, field === "longitude" ? value : longitude, "MANUAL")); }
  function selectOnMap(nextLatitude, nextLongitude) { applyLocation(adjustedLocation(Number(nextLatitude).toFixed(6), Number(nextLongitude).toFixed(6), "MAP_SELECTED")); }

  async function confirmLocation() {
    setError(null); setResolvingLocation(true);
    try {
      const data = await resolveJurisdiction(latitude, longitude);
      const confirmed = confirmedLocation({ latitude, longitude, source: locationSource, accuracy: locationAccuracy, capturedAt: locationCapturedAt }, data);
      setLocationConfirmed(confirmed.confirmed); setResolution(confirmed.resolution);
      if (data.status === "NO_CONFIGURED_JURISDICTION") setError("This sighting location is not currently covered by an active monitoring jurisdiction.");
      if (data.status === "AMBIGUOUS") setError("We couldn't determine a single monitoring jurisdiction for this sighting location.");
    } catch { setResolution(null); setLocationConfirmed(false); setError("We couldn't verify the monitoring jurisdiction. Please try again."); }
    finally { setResolvingLocation(false); }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    const imageError = validateObservationImage(image);
    if (imageError) { setError(imageError); return; }
    if (latitude === "" || longitude === "") { setError("Latitude and longitude are required."); return; }
    if (!locationConfirmed || resolution?.status !== "RESOLVED") { setError("Confirm the sighting location before submitting."); return; }
    try {
      setSubmitting(true);
      const data = await analyzeObservation({ image, latitude, longitude, locationAccuracy, locationCapturedAt, locationSource, expectedJurisdictionId, reporterSuggestedTaxonId: suggestedTaxonId });
      setResult(data); setResultOpen(true); onObservationCreated?.();
    } catch (submitError) { setError(submitError.message || "Unable to submit observation. The backend may be unavailable."); }
    finally { setSubmitting(false); }
  }

  return <div className="submit-experience">
    <header className="submit-experience__header"><p className="submit-kicker">Field reporting workflow</p><h1>Submit Marine Observation</h1><p>Upload field imagery and verify the sighting location for preliminary AI analysis and jurisdictional review.</p>{expectedJurisdictionId && <div className="submission-context"><strong>Reporting in:</strong> {reportingContext?.jurisdiction?.name || "Validating jurisdiction…"}{reportingContext?.taxon && <span>Suggested taxon: <em>{reportingContext.taxon.scientific_name}</em></span>}<small>The suggestion does not determine final identification.</small></div>}</header>
    <div className="submit-workspace"><main className="submit-workflow"><form onSubmit={handleSubmit} className="observation-form">
      <section className="submission-step"><StepHeader number="1" title="Specimen Imagery & Photographic Evidence" required /><input ref={fileInput} id="observation-image" className="submission-file-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => chooseImage(event.target.files?.[0] || null)} />
        {!preview ? <label htmlFor="observation-image" className="submission-upload-empty"><span className="submission-upload-icon">＋</span><strong>Choose or capture a marine image</strong><span>JPEG, PNG, or WEBP · maximum 10 MB</span></label> : <div className="submission-image-selected"><img src={preview} alt="Selected marine observation" /><div><span>{image.name}</span><span>{(image.size / 1024 / 1024).toFixed(2)} MB</span></div><div className="submission-image-actions"><button type="button" onClick={() => fileInput.current?.click()}>Replace image</button><button type="button" className="danger" onClick={removeImage}>Remove</button></div></div>}
      </section>
      <section className="submission-step"><StepHeader number="2" title="Observation Location" required status={locationConfirmed ? "Location selected" : null} /><p className="submission-step__guidance">Place the marker where the organism was observed, not where the report is being submitted.</p><div className="submission-location-actions"><button type="button" onClick={useCurrentLocation} disabled={locating}>{locating ? "Getting current location…" : "Use current location"}</button><button type="button" onClick={() => setLocationPickerVisible(true)}>Choose location manually</button></div>{locationPickerVisible && <SightingLocationPicker latitude={latitude} longitude={longitude} onSelect={selectOnMap} />}
        <div className="coordinate-grid"><label>Latitude<input aria-label="Latitude" type="number" step="any" min="-90" max="90" value={latitude} onChange={(event) => changeManualCoordinate("latitude", event.target.value)} placeholder="Latitude" /></label><label>Longitude<input aria-label="Longitude" type="number" step="any" min="-180" max="180" value={longitude} onChange={(event) => changeManualCoordinate("longitude", event.target.value)} placeholder="Longitude" /></label></div>
        {latitude !== "" && longitude !== "" && <div className={`submission-location-summary ${locationConfirmed ? "confirmed" : ""}`} role="status"><div><strong>{locationConfirmed ? "Location selected" : "Location available — confirmation required"}</strong><span>{latitude}, {longitude} · {sourceLabel(locationSource)}</span>{locationSource === "DEVICE_GEOLOCATION" && locationAccuracy != null && <span>Browser-reported accuracy: approximately ±{Math.round(locationAccuracy)} m</span>}{resolution?.status === "RESOLVED" && <span>Monitoring jurisdiction: {resolution.jurisdiction.name}</span>}</div><button type="button" disabled={resolvingLocation} onClick={confirmLocation}>{resolvingLocation ? "Checking jurisdiction…" : locationConfirmed ? "Reconfirm location" : "Confirm location"}</button></div>}
      </section>
      <section className="submission-step submission-step--optional"><StepHeader number="3" title="Optional Observation Details" /><p>No additional structured field details are required by the current reporting contract. Image and confirmed location data will be submitted.</p></section>
      {error && <div className="form-error" role="alert">{error}</div>}
      <section className="submission-action"><button type="submit" className="submission-primary-action" disabled={!readyToSubmit}>{submitting ? <><span className="submission-spinner" /> Analyzing and submitting…</> : "Analyze & Submit Sighting"}</button><p>AI-assisted identification is preliminary. Every submitted observation remains pending expert review.</p></section>
    </form></main>
    <aside className="submission-analysis" aria-label="Preliminary AI identification">{result ? <ResultPanel result={result} preview={preview} /> : <PreAnalysis />}</aside></div>
    {result && resultOpen && <div className="submission-result-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setResultOpen(false); }}><section role="dialog" aria-modal="true" aria-labelledby="mobile-result-title" className="submission-result-sheet"><div className="submission-sheet-grabber" /><button ref={resultCloseButton} type="button" className="submission-sheet-close" aria-label="Close preliminary identification" onClick={() => setResultOpen(false)}>×</button><ResultPanel result={result} preview={preview} mobile /><button type="button" className="submission-sheet-done" onClick={() => setResultOpen(false)}>Done</button></section></div>}
  </div>;
}

function StepHeader({ number, title, required, status }) { return <div className="submission-step__header"><span>{number}</span><h2>{title}</h2>{required && <small>Required</small>}{status && <strong>{status}</strong>}</div>; }

function PreAnalysis() { return <div className="submission-analysis-empty"><p className="submit-kicker">Analysis panel</p><h2>Preliminary AI Identification</h2><div className="ai-caution"><strong>AI Suggestion — Not Authoritative</strong><span>Results require validation by an authorized expert.</span></div><p>After submission, this panel may show:</p><ul><li>Preliminary species suggestion</li><li>Alternative candidates where available</li><li>Governed regional context</li><li>The expert-review pathway</li></ul></div>; }

function ResultPanel({ result, preview, mobile = false }) {
  const identification = result.identification || {};
  const candidates = alternativeCandidates(identification);
  const displaySpecies = identification.species || identification.nearest_candidate || "Identification unresolved";
  const jurisdiction = result.observation?.jurisdiction?.name || result.jurisdiction_resolution?.jurisdiction?.name;
  const hasGovernedEvidence = Boolean(result.regional_evidence?.species);
  return <div className="submit-result-panel"><p className="submit-kicker">Observation submitted</p><h2 id={mobile ? "mobile-result-title" : undefined}>Preliminary AI Identification</h2><div className="ai-caution"><strong>AI Suggestion — Not Authoritative</strong><span>Algorithmic similarity does not establish expert identification, presence, or ecological status.</span></div><div className="submission-primary-result">{preview && <img src={preview} alt="Submitted marine observation" />}<div><span>Primary suggestion</span><h3><em>{displaySpecies}</em></h3><dl><div><dt>Similarity</dt><dd>{similarityLabel(identification.score)}</dd></div><div><dt>Identification state</dt><dd>{identification.status || "Unresolved"}</dd></div></dl></div></div>
    {candidates.length > 0 && <section className="submission-candidates"><h3>Alternative candidates</h3><ul>{candidates.map((candidate) => <li key={candidate.scientific_name}><em>{candidate.scientific_name}</em><span>Similarity {similarityLabel(candidate.score)}</span></li>)}</ul></section>}
    <section className="submission-result-context"><h3>Regional context</h3><p>{jurisdiction ? `Submitted to the ${jurisdiction} monitoring jurisdiction.` : "Jurisdiction context is unavailable."}</p><p>{hasGovernedEvidence ? "Governed regional occurrence evidence is available for the suggested taxon. This submission does not establish presence or ecological status." : "Insufficient governed regional evidence is available for an additional public context statement."}</p><strong>Governed ecological status: Not established by this submission</strong><p>Expert verification and governed ecological-status review are separate decisions.</p></section>
    <ReviewPathway identification={identification} />
    <div className="submission-result-actions">{result.reporter_status_token && <a href={`/reporter/status/${result.reporter_status_token}`}>View submitted observation</a>}<span>Submitted for expert review · Report {result.submission_reference || "received"}</span></div>
  </div>;
}

function ReviewPathway({ identification }) { const analyzed = Boolean(identification?.status); return <section className="review-pathway"><h3>Review pathway</h3><ol><li className="complete"><span>1</span><div><strong>Submitted observation</strong><small>Complete</small></div></li><li className={analyzed ? "complete" : "current"}><span>2</span><div><strong>AI-assisted preliminary identification</strong><small>{analyzed ? "Complete" : "Current"}</small></div></li><li className="current"><span>3</span><div><strong>Expert review</strong><small>Pending</small></div></li><li><span>4</span><div><strong>Scientific assessment where eligible</strong><small>Not started</small></div></li></ol></section>; }
