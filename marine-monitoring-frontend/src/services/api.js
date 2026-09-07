const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const authHeaders = (headers = {}) => {
  const token = sessionStorage.getItem("trustedAccessToken");
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers;
};

export async function loginTrustedUser(email, password) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
  if (!response.ok) throw new Error("Invalid email or password.");
  return response.json();
}

export async function getCurrentUser() {
  const response = await fetch(`${API_BASE_URL}/auth/me`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Authentication required.");
  return response.json();
}

export async function logoutTrustedUser() {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, { method: "POST", headers: authHeaders() });
  if (!response.ok) throw new Error("Sign out failed.");
  return response.json();
}

export async function getTrustedUsers() {
  const response = await fetch(`${API_BASE_URL}/admin/users`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load trusted users.");
  return response.json();
}

async function adminRequest(path, options = {}) {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const contentHeaders = options.body && !isFormData ? { "Content-Type": "application/json" } : {};
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: authHeaders({ ...contentHeaders, ...(options.headers || {}) }) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error?.message || data.detail || "Administrative request failed."); }
  return response.json();
}

export const getSystemStatus = () => adminRequest("/admin/system/status");
export const processScientificEvent = (id) => adminRequest(`/admin/system/events/${id}/process`, { method: "POST" });
export const retryScientificEvent = (id) => adminRequest(`/admin/system/events/${id}/retry`, { method: "POST" });
export const createSystemBackup = () => adminRequest("/admin/system/backups", { method: "POST" });

export const getAdminOverview = () => adminRequest("/admin/overview");
export const getAdminRegions = () => adminRequest("/admin/regions");
export const createAdminRegion = (payload) => adminRequest("/admin/regions", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminRegion = (id, payload) => adminRequest(`/admin/regions/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const getAdminJurisdictions = () => adminRequest("/admin/jurisdictions");
export const getAdminJurisdiction = (id) => adminRequest(`/admin/jurisdictions/${id}`);
export const getRegionOnboardingInventory = (regionId) => adminRequest(`/admin/regions/${regionId}/jurisdiction-onboarding/prepare?dry_run=true`, { method: "POST" });
export const prepareRegionJurisdictions = (regionId, identifiers) => {
  const params = new URLSearchParams({ dry_run: "false", canonical_identifiers: identifiers.join(",") });
  return adminRequest(`/admin/regions/${regionId}/jurisdiction-onboarding/prepare?${params}`, { method: "POST" });
};
export const getOnboardingPreparation = (id) => adminRequest(`/admin/jurisdiction-onboarding/${id}`);
export const approveOnboardingPreparation = (id, manifestFingerprint, approvalReference) => adminRequest(`/admin/jurisdiction-onboarding/${id}/approve`, { method: "POST", body: JSON.stringify({ expected_manifest_fingerprint: manifestFingerprint, approval_reference: approvalReference }) });
export const applyOnboardingPreparation = (id) => adminRequest(`/admin/jurisdiction-onboarding/${id}/apply`, { method: "POST" });
export const applyOnboardingBatch = (preparationIds) => adminRequest("/admin/jurisdiction-onboarding/apply-batch", { method: "POST", body: JSON.stringify({ preparation_ids: preparationIds }) });
export const getAdminRegionTaxa = (regionId) => adminRequest(`/admin/regions/${regionId}/taxa`);
export const getAdminJurisdictionTaxonReadiness = (jurisdictionId, taxonId) => adminRequest(`/admin/jurisdictions/${jurisdictionId}/taxa/${taxonId}/readiness`);
export const getAdminTaxa = () => adminRequest("/admin/taxa");
export const prepareAdminTaxonomy = (taxonId, regionId) => adminRequest("/admin/taxonomy/prepare", { method: "POST", body: JSON.stringify({ taxon_id: Number(taxonId), region_id: Number(regionId) }) });
export const approveAdminTaxonomy = (id, fingerprint, approvalReference) => adminRequest(`/admin/taxonomy/preparations/${id}/approve`, { method: "POST", body: JSON.stringify({ expected_preparation_fingerprint: fingerprint, approval_reference: approvalReference }) });
export const applyAdminTaxonomy = (id) => adminRequest(`/admin/taxonomy/preparations/${id}/apply`, { method: "POST" });
export const getAdminTaxonomyHistory = (taxonId) => adminRequest(`/admin/taxa/${taxonId}/taxonomy-history`);
export const prepareAdminTaxonomyBulk = (regionId, candidates, dryRun = true) => adminRequest(`/admin/regions/${regionId}/taxonomy/prepare-bulk`, { method: "POST", body: JSON.stringify({ candidates, dry_run: dryRun }) });
export const approveAdminTaxonomyBatch = (preparationIds, approvalReference) => adminRequest("/admin/taxonomy/preparations/approve-batch", { method: "POST", body: JSON.stringify({ preparation_ids: preparationIds, approval_reference: approvalReference }) });
export const applyAdminTaxonomyBatch = (preparationIds) => adminRequest("/admin/taxonomy/preparations/apply-batch", { method: "POST", body: JSON.stringify({ preparation_ids: preparationIds }) });
export const approveLocalTaxonCandidateBatch = (candidateIds, approvalReference) => adminRequest("/admin/taxonomy/local-candidate-batches/approve", { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, approval_reference: approvalReference }) });
export const applyLocalTaxonCandidateBatch = (candidateIds) => adminRequest("/admin/taxonomy/local-candidate-batches/apply", { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds }) });
export const preflightRegionalTaxonManifest = (manifest) => adminRequest("/admin/taxonomy/manifests/preflight", { method: "POST", body: JSON.stringify(manifest) });
export const prepareRegionalTaxonManifest = (manifest) => adminRequest("/admin/taxonomy/manifests", { method: "POST", body: JSON.stringify(manifest) });
export const getRegionalTaxonManifest = (runId) => adminRequest(`/admin/taxonomy/manifests/${runId}`);
export const approveRegionalTaxonManifestItems = (runId, itemIds, approvalReference) => adminRequest(`/admin/taxonomy/manifests/${runId}/approve`, { method: "POST", body: JSON.stringify({ item_ids: itemIds, approval_reference: approvalReference }) });
export const rejectRegionalTaxonManifestItem = (runId, itemId, approvalReference) => adminRequest(`/admin/taxonomy/manifests/${runId}/items/${itemId}/reject`, { method: "POST", body: JSON.stringify({ item_ids: [itemId], approval_reference: approvalReference }) });
export const applyRegionalTaxonManifestItems = (runId, itemIds) => adminRequest(`/admin/taxonomy/manifests/${runId}/apply`, { method: "POST", body: JSON.stringify({ item_ids: itemIds }) });
export const retryRegionalTaxonManifestItems = (runId, itemIds) => adminRequest(`/admin/taxonomy/manifests/${runId}/retry`, { method: "POST", body: JSON.stringify({ item_ids: itemIds }) });
export const parseScientificCorpusManifest = (content, inputFormat) => adminRequest("/admin/scientific-corpus/manifests/parse", { method: "POST", body: JSON.stringify({ content, input_format: inputFormat }) });
export const getScientificCorpusContract = () => adminRequest("/admin/scientific-corpus/contract");
export const getAdminOccurrenceSources = () => adminRequest("/admin/occurrence-sources");
export const getScientificScalingSummary = (regionId) => adminRequest(`/admin/regions/${regionId}/scientific-scaling/summary`);
export const getScientificScalingInventory = (regionId) => adminRequest(`/admin/regions/${regionId}/scientific-scaling/inventory`);
export const getScientificScalingMatrix = (regionId, params = {}) => adminRequest(`/admin/regions/${regionId}/scientific-scaling/matrix?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== "" && value !== undefined && value !== null)).toString()}`);
export const getScientificScalingWorkQueue = (regionId, params = {}) => adminRequest(`/admin/regions/${regionId}/scientific-scaling/work-queue?${new URLSearchParams(Object.entries(params).filter(([, value]) => value !== "" && value !== undefined && value !== null)).toString()}`);
export const getEarlyWarningQueue = () => adminRequest("/admin/early-warning/queue");
export const getEarlyWarningSummary = () => adminRequest("/admin/early-warning/summary");
export const reviewEarlyWarning = (assessmentId, state, reason) => adminRequest(`/admin/early-warning/assessments/${assessmentId}/disposition`, { method: "POST", body: JSON.stringify({ state, reason }) });
export const getScientificEarlyWarningQueue = () => adminRequest("/scientific-review/early-warning");
export const reviewScientificEarlyWarning = (assessmentId, state, reason) => adminRequest(`/scientific-review/early-warning/${assessmentId}/disposition`, { method: "POST", body: JSON.stringify({ state, reason }) });
export const claimScientificEarlyWarning = (assessmentId) => adminRequest(`/scientific-review/early-warning/${assessmentId}/claim`, { method: "POST", body: JSON.stringify({ reason: "Scientific reviewer claimed assessment" }) });
export const evaluateScientificObservation = (observationId) => adminRequest(`/scientific-review/observations/${observationId}/evaluate`, { method: "POST" });
export const getEarlyWarningConfigurations = (filters = {}) => adminRequest(`/admin/early-warning/configurations?${new URLSearchParams(Object.entries(filters).filter(([,value])=>value!==""&&value!==undefined&&value!==null)).toString()}`);
export const getEarlyWarningEventSummary = () => adminRequest("/admin/early-warning/events/summary");
export const getScientificReviewerGrants = () => adminRequest("/admin/scientific-reviewers");
export const grantScientificReviewer = (payload) => adminRequest("/admin/scientific-reviewers", { method: "POST", body: JSON.stringify(payload) });
export const revokeScientificReviewer = (id) => adminRequest(`/admin/scientific-reviewers/${id}/revoke`, { method: "POST" });
export const createEarlyWarningConfiguration = (payload) => adminRequest("/admin/early-warning/configurations", { method: "POST", body: JSON.stringify(payload) });
export const updateEarlyWarningConfiguration = (id, payload) => adminRequest(`/admin/early-warning/configurations/${id}`, { method: "PUT", body: JSON.stringify(payload) });
export const transitionEarlyWarningConfiguration = (id, targetState, reference) => adminRequest(`/admin/early-warning/configurations/${id}/transition`, { method: "POST", body: JSON.stringify({ target_state: targetState, reference }) });
export const getEarlyWarningEvents = (state = "") => adminRequest(`/admin/early-warning/events${state ? `?state=${state}` : ""}`);
export const processEarlyWarningEvent = (id) => adminRequest(`/admin/early-warning/events/${id}/process`, { method: "POST" });
export const prepareAdminOccurrenceEvidence = (jurisdictionId, taxonId, sourceKey, dryRun = false) => adminRequest("/admin/occurrence-evidence/preparations", { method: "POST", body: JSON.stringify({ jurisdiction_id: Number(jurisdictionId), taxon_id: Number(taxonId), source_key: sourceKey, dry_run: dryRun }) });
export const getAdminOccurrencePreparation = (preparationId) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}`);
export const approveAdminOccurrenceCandidates = (preparationId, candidateIds, reviewReference) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/approve`, { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, review_reference: reviewReference }) });
export const rejectAdminOccurrenceCandidates = (preparationId, candidateIds, reviewReference) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/reject`, { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, review_reference: reviewReference }) });
export const applyAdminOccurrenceEvidence = (preparationId) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/apply`, { method: "POST" });
export const retryAdminOccurrenceEvidence = (preparationId) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/retry`, { method: "POST" });
export const initializeAdminOccurrenceReview = (preparationId) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/initialize-review`, { method: "POST" });
export const getAdminOccurrenceReviewReport = (preparationId) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/review-report`);
export const disposeAdminOccurrenceCandidates = (preparationId, candidateIds, disposition, reviewReference, evidenceNote = null) => adminRequest(`/admin/occurrence-evidence/preparations/${preparationId}/dispositions`, { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, disposition, review_reference: reviewReference, evidence_note: evidenceNote }) });
export const getAdminEcologicalStatus = (jurisdictionId, taxonId) => adminRequest(`/admin/jurisdictions/${jurisdictionId}/taxa/${taxonId}/ecological-status`);
export const preflightAdminEcologicalStatus = (payload) => adminRequest("/admin/ecological-status/preflight", { method: "POST", body: JSON.stringify(payload) });
export const prepareAdminEcologicalStatus = (payload) => adminRequest("/admin/ecological-status/preparations", { method: "POST", body: JSON.stringify(payload) });
export const reviewAdminEcologicalStatus = (preparationId, candidateIds, reviewReference, disposition = "APPROVED") => adminRequest(`/admin/ecological-status/preparations/${preparationId}/review`, { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, review_reference: reviewReference, disposition }) });
export const applyAdminEcologicalStatus = (preparationId) => adminRequest(`/admin/ecological-status/preparations/${preparationId}/apply`, { method: "POST" });
export const getAdminEcologicalSources = () => adminRequest("/admin/ecological-status/sources");
export const getAdminPublicMedia = () => adminRequest("/admin/public-media");
export const getAdminObservationQueue = (params = {}) => adminRequest(`/admin/observations/queue?${new URLSearchParams(Object.entries(params).filter(([,value])=>value!==undefined&&value!==null&&value!=="")).toString()}`);
export const getAdminObservationOperations = (id) => adminRequest(`/admin/observations/${id}/operations`);
export const getEligibleObservationReviewers = (jurisdictionId) => adminRequest(`/admin/observation-reviewers/eligible?jurisdiction_id=${jurisdictionId}`);
export const getObservationReviewers = () => adminRequest("/admin/observation-reviewers");
export const grantObservationReviewer = (payload) => adminRequest("/admin/observation-reviewers/grants",{method:"POST",body:JSON.stringify(payload)});
export const revokeObservationReviewer = (id) => adminRequest(`/admin/observation-reviewers/grants/${id}/revoke`,{method:"POST"});
export const getReviewerHome = () => adminRequest("/reviewer/home");
export const submitPilotFeedback = (payload) => adminRequest("/pilot/feedback",{method:"POST",body:JSON.stringify(payload)});
export const getAdminPilotFeedback = () => adminRequest("/admin/pilot/feedback");
export const getAdminPilotActivity = () => adminRequest("/admin/pilot/activity");
async function authenticatedObservationImage(path) { const response=await fetch(`${API_BASE_URL}${path}`,{headers:authHeaders()});const contentType=response.headers.get("Content-Type") || "";if(!response.ok || !contentType.toLowerCase().startsWith("image/"))throw new Error("Private observation image unavailable.");return URL.createObjectURL(await response.blob()); }
export const getPrivateObservationImage = (id) => authenticatedObservationImage(`/admin/observations/${id}/image`);
export const getJurisdictionObservationImage = (id) => authenticatedObservationImage(`/observations/${id}/image`);
export const claimAdminObservation = (id) => adminRequest(`/admin/observations/${id}/claim`, { method: "POST", body: JSON.stringify({ reason: "Reviewer claimed case" }) });
export const assignAdminObservation = (id, reviewerUserId, expectedReviewerUserId = null) => adminRequest(`/admin/observations/${id}/assign`, { method: "POST", body: JSON.stringify({ reviewer_user_id: reviewerUserId, expected_reviewer_user_id: expectedReviewerUserId, reason: "Operational assignment" }) });
export const requestAdminObservationInformation = (id, reason) => adminRequest(`/admin/observations/${id}/request-information`, { method: "POST", body: JSON.stringify({ reason }) });
export const closeAdminObservation = (id, reopen = false, reason = null) => adminRequest(`/admin/observations/${id}/close?reopen=${reopen}`,{method:"POST",body:JSON.stringify({reason:reason||(reopen?"Operational case reopened":"Operational review completed")})});
export const rotateReporterLink = (id) => adminRequest(`/admin/observations/${id}/manual-reporter-link`,{method:"POST"});
export const triageAdminObservation = (id) => adminRequest(`/admin/observations/${id}/triage`, { method: "POST" });
export const updateAdminObservationDisposition = (id, disposition, species, reason) => adminRequest(`/admin/observations/${id}/disposition`, { method: "POST", body: JSON.stringify({ disposition, species, reason }) });
export const updateAdminObservationPriority = (id, priority, reason) => adminRequest(`/admin/observations/${id}/priority`, { method: "POST", body: JSON.stringify({ priority, reason }) });
export const registerAdminPublicMedia = (payload) => adminRequest("/admin/public-media", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminPublicMedia = (id, action, primary = false) => adminRequest(`/admin/public-media/${id}/${action}?primary=${primary}`, { method: "POST" });
export const getAdminSuitabilityDisplay = (id) => adminRequest(`/admin/suitability-deployments/${id}/public-display`);
export const approveAdminSuitabilityDisplay = (id, reference) => adminRequest(`/admin/suitability-deployments/${id}/public-display/approve`, { method: "POST", body: JSON.stringify({ review_reference: reference }) });
export const revokeAdminSuitabilityDisplay = (id) => adminRequest(`/admin/suitability-deployments/${id}/public-display/revoke`, { method: "POST" });
export const getAdminEcologicalIngestionRuns = (jurisdictionId) => adminRequest(`/admin/ecological-status/ingestion-runs?jurisdiction_id=${Number(jurisdictionId)}`);
export const getAdminEcologicalIngestion = (runId) => adminRequest(`/admin/ecological-status/ingestion-runs/${runId}`);
export const preflightAdminEcologicalArtifact = (sourceId, jurisdictionId, file, mapping) => { const body = new FormData(); body.append("source_id", sourceId); body.append("jurisdiction_id", jurisdictionId); body.append("mapping_json", JSON.stringify(mapping)); body.append("artifact", file); return adminRequest("/admin/ecological-status/ingestion/preflight", { method: "POST", body }); };
export const createAdminEcologicalIngestion = (sourceId, jurisdictionId, file, mapping) => { const body = new FormData(); body.append("source_id", sourceId); body.append("jurisdiction_id", jurisdictionId); body.append("mapping_json", JSON.stringify(mapping)); body.append("artifact", file); return adminRequest("/admin/ecological-status/ingestion-runs", { method: "POST", body }); };
export const reviewAdminEcologicalIngestion = (runId, rowIds, disposition, reviewReference) => adminRequest(`/admin/ecological-status/ingestion-runs/${runId}/review`, { method: "POST", body: JSON.stringify({ row_ids: rowIds, disposition, review_reference: reviewReference }) });
export const applyAdminEcologicalIngestion = (runId, rowIds) => adminRequest(`/admin/ecological-status/ingestion-runs/${runId}/apply`, { method: "POST", body: JSON.stringify({ row_ids: rowIds, disposition: "APPROVED", review_reference: "apply" }) });
export const createAdminJurisdiction = (payload) => adminRequest("/admin/jurisdictions", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminJurisdiction = (id, payload) => adminRequest(`/admin/jurisdictions/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const getAdminOrganizations = () => adminRequest("/admin/organizations");
export const getAdminSpeciesPrograms = () => adminRequest("/admin/species-programs");
export const createAdminOrganization = (payload) => adminRequest("/admin/organizations", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminOrganization = (id, payload) => adminRequest(`/admin/organizations/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const addAdminParticipation = (organizationId, jurisdictionId) => adminRequest(`/admin/organizations/${organizationId}/jurisdictions`, { method: "POST", body: JSON.stringify({ jurisdiction_id: Number(jurisdictionId) }) });
export const updateAdminParticipation = (id, status) => adminRequest(`/admin/organization-jurisdictions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
export const createAdminUser = (payload) => adminRequest("/admin/users", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminUser = (id, payload) => adminRequest(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const addAdminMembership = (userId, payload) => adminRequest(`/admin/users/${userId}/memberships`, { method: "POST", body: JSON.stringify(payload) });
export const updateAdminMembership = (id, payload) => adminRequest(`/admin/memberships/${id}`, { method: "PATCH", body: JSON.stringify(payload) });

function geographicQuery({ region, jurisdiction } = {}) {
  const params = new URLSearchParams();
  if (region) params.set("region_slug", region);
  if (jurisdiction) params.set("jurisdiction_slug", jurisdiction);
  return params.size ? `?${params}` : "";
}

export async function getRegions() {
  const response = await fetch(`${API_BASE_URL}/regions`);
  if (!response.ok) throw new Error("Failed to load regions.");
  return response.json();
}

export async function getPublicRegion(region) {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}`);
  if (!response.ok) throw new Error("Region not found.");
  return response.json();
}

export async function getPublicJurisdiction(jurisdiction) {
  const response = await fetch(`${API_BASE_URL}/jurisdictions/${encodeURIComponent(jurisdiction)}`);
  if (!response.ok) throw new Error("Jurisdiction not found.");
  return response.json();
}

export async function getPublicSpeciesDirectory(jurisdictionId, { invasive = false, page = 1, pageSize = 24, search = "" } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (search) params.set("search", search);
  const directory = invasive ? "invasive-species" : "marine-species";
  const response = await fetch(`${API_BASE_URL}/jurisdictions/${jurisdictionId}/${directory}?${params}`);
  if (!response.ok) throw new Error("Species directory is unavailable.");
  return response.json();
}

export async function getPublicSpeciesDetail(jurisdictionId, taxonId) {
  const response = await fetch(`${API_BASE_URL}/jurisdictions/${jurisdictionId}/species/${taxonId}`);
  if (!response.ok) throw new Error("Species detail is unavailable.");
  return response.json();
}

export async function getPublicSpeciesMap(jurisdictionId, taxonId) {
  const response = await fetch(`${API_BASE_URL}/jurisdictions/${jurisdictionId}/species/${taxonId}/map`);
  if (!response.ok) throw new Error("Species map evidence is unavailable.");
  return response.json();
}
export async function getPublicSuitabilityGrid(jurisdictionId, taxonId) {
  const response = await fetch(`${API_BASE_URL}/jurisdictions/${jurisdictionId}/species/${taxonId}/suitability-grid`);
  if (!response.ok) throw new Error("Suitability context is unavailable.");
  return response.json();
}
export async function getPublicTaxonMedia(taxonId) {
  const response = await fetch(`${API_BASE_URL}/species/${taxonId}/public-media`);
  if (!response.ok) throw new Error("Public media is unavailable.");
  return response.json();
}

export async function getJurisdictions(region) {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/jurisdictions`);
  if (!response.ok) throw new Error("Failed to load jurisdictions.");
  return response.json();
}

export async function getJurisdiction(region, jurisdiction) {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/jurisdictions/${encodeURIComponent(jurisdiction)}`);
  if (!response.ok) throw new Error("Jurisdiction not found.");
  return response.json();
}

export async function getRegionOverview(region = "caribbean") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/overview`);
  if (!response.ok) throw new Error("Failed to load regional overview.");
  return response.json();
}

export async function getRegionSpeciesEvidence(region = "caribbean") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/species-evidence`);
  if (!response.ok) throw new Error("Failed to load regional species evidence.");
  return response.json();
}

export async function getRegionAnalytics(region = "caribbean") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/analytics`);
  if (!response.ok) throw new Error("Failed to load regional analytics.");
  return response.json();
}

export async function getRegionSpeciesIntelligence(region = "caribbean") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/species`);
  if (!response.ok) throw new Error("Failed to load regional species intelligence.");
  return response.json();
}

export async function getJurisdictionSpeciesIntelligence(region = "caribbean", jurisdiction) {
  if (!jurisdiction) {
    throw new Error("Jurisdiction slug is required to load jurisdiction species intelligence.");
  }
  const response = await fetch(
    `${API_BASE_URL}/regions/${encodeURIComponent(region)}/jurisdictions/${encodeURIComponent(jurisdiction)}/species`,
  );
  if (!response.ok) throw new Error("Failed to load jurisdiction species intelligence.");
  return response.json();
}

export async function getSpeciesCatalog({ page = 1, pageSize = 50, search = "", withObservations = false } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (search) params.set("search", search);
  if (withObservations) params.set("with_observations", "true");
  const response = await fetch(`${API_BASE_URL}/species/catalog?${params}`);
  if (!response.ok) throw new Error("Marine species catalog is unavailable.");
  return response.json();
}

export async function getSpeciesCatalogDetail(taxonId) {
  const response = await fetch(`${API_BASE_URL}/species/catalog/${encodeURIComponent(taxonId)}`);
  if (!response.ok) throw new Error("Species intelligence is unavailable.");
  return response.json();
}

export async function getRegionSpeciesTracking(region = "caribbean") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/species-tracking`);
  if (!response.ok) throw new Error("Species tracking data is unavailable.");
  return response.json();
}

export async function getJurisdictionBoundary(region, jurisdiction) {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/jurisdictions/${encodeURIComponent(jurisdiction)}/boundary`);
  if (!response.ok) throw new Error("Operational boundary not available.");
  return response.json();
}

export async function getOrganizations() {
  const response = await fetch(`${API_BASE_URL}/organizations`);
  if (!response.ok) throw new Error("Failed to load organizations.");
  return response.json();
}

export async function getJurisdictionOrganizations(region = "caribbean", jurisdiction = "jamaica") {
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(region)}/jurisdictions/${encodeURIComponent(jurisdiction)}/organizations`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load participating organizations.");
  return response.json();
}

export async function getInvestigations(scope, filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const query = params.size ? `?${params}` : "";
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(scope.region)}/jurisdictions/${encodeURIComponent(scope.jurisdiction)}/investigations${query}`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load investigations.");
  return response.json();
}

export async function createInvestigation(scope, payload) {
  if (payload === undefined) {
    payload = scope;
    const match = window.location.pathname.match(/^\/region\/([^/]+)\/([^/]+)/);
    scope = { region: match?.[1] || "caribbean", jurisdiction: match?.[2] || "jamaica" };
  }
  const response = await fetch(`${API_BASE_URL}/regions/${encodeURIComponent(scope.region)}/jurisdictions/${encodeURIComponent(scope.jurisdiction)}/investigations`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Failed to create investigation."); }
  return response.json();
}

export async function updateInvestigationStatus(id, status, outcomeSummary) {
  const response = await fetch(`${API_BASE_URL}/investigations/${id}/status`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ status, outcome_summary: outcomeSummary || null }) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Failed to update investigation status."); }
  return response.json();
}

export async function getFieldVisits(investigationId) {
  const response = await fetch(`${API_BASE_URL}/investigations/${investigationId}/field-visits`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Failed to load field activity.");
  return response.json();
}

export async function createFieldVisit(investigationId, payload) {
  const response = await fetch(`${API_BASE_URL}/investigations/${investigationId}/field-visits`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Failed to record field visit."); }
  return response.json();
}

export async function createFieldObservation(fieldVisitId, payload) {
  const response = await fetch(`${API_BASE_URL}/field-visits/${fieldVisitId}/observations`, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(payload) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Failed to record field observation."); }
  return response.json();
}

export async function submitFieldVisit(fieldVisitId) {
  const response = await fetch(`${API_BASE_URL}/field-visits/${fieldVisitId}/submit`, { method: "POST", headers: authHeaders() });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Failed to submit field visit."); }
  return response.json();
}

export async function getMapObservations(scope) {
  const response = await fetch(
    `${API_BASE_URL}/observations/map${geographicQuery(scope)}`
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load map observations."
    );
  }

  return response.json();
}

export function getImageUrl(path) {
  if (!path) {
    return null;
  }

  if (path.startsWith("http")) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
}
export async function getObservation(id) {
  const response = await fetch(
    `${API_BASE_URL}/observations/${id}`
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load observation details."
    );
  }

  return response.json();
}
export async function analyzeObservation({
  image,
  latitude,
  longitude,
  locationAccuracy,
  locationCapturedAt,
  locationSource,
  expectedJurisdictionId,
  reporterSuggestedTaxonId,
}) {
  const formData = new FormData();

  formData.append("image", image);
  formData.append("latitude", latitude);
  formData.append("longitude", longitude);
  if (locationAccuracy != null) formData.append("location_accuracy_m", locationAccuracy);
  if (locationCapturedAt) formData.append("location_captured_at", locationCapturedAt);
  formData.append("location_source", locationSource || "MANUAL");
  if (expectedJurisdictionId) formData.append("expected_jurisdiction_id", expectedJurisdictionId);
  if (reporterSuggestedTaxonId) formData.append("reporter_suggested_taxon_id", reporterSuggestedTaxonId);

  const response = await fetch(
    `${API_BASE_URL}/observations/analyze`,
    {
      method: "POST",
      body: formData,
    }
  );

  if (!response.ok) {
    let message = "Observation analysis failed.";

    try {
      const data = await response.json();

      if (data.detail) {
        message = typeof data.detail === "string" ? data.detail : data.detail.message || message;
      }
    } catch {
      // Keep default message.
    }

    throw new Error(message);
  }

  return response.json();
}
export async function getReviewQueue(scope = { region: "caribbean", jurisdiction: "jamaica" }) {
  const response = await fetch(
    `${API_BASE_URL}/observations/review-queue${geographicQuery(scope)}`,
    { headers: authHeaders() }
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load review queue."
    );
  }

  return response.json();
}


export async function verifyObservation(
  id,
  verification
) {
  const response = await fetch(
    `${API_BASE_URL}/observations/${id}/verify`,
    {
      method: "PATCH",

      headers: authHeaders({
        "Content-Type": "application/json",
      }),

      body: JSON.stringify(
        verification
      ),
    }
  );

  if (!response.ok) {

    let message =
      "Failed to verify observation.";

    try {

      const data =
        await response.json();

      if (data.detail) {
        message = data.detail;
      }

    } catch {
      // Keep default message.
    }

    throw new Error(message);
  }

  return response.json();
}
export async function getHotspots(scope) {
  const response = await fetch(
    `${API_BASE_URL}/analytics/hotspots${geographicQuery(scope)}`
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load hotspots."
    );
  }

  return response.json();
}
export async function getAnalyticsSummary(scope) {
  const response = await fetch(
    `${API_BASE_URL}/analytics/summary${geographicQuery(scope)}`
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load monitoring summary."
    );
  }

  return response.json();
}

export async function resolveJurisdiction(latitude, longitude) {
  const params = new URLSearchParams({ latitude, longitude });
  const response = await fetch(`${API_BASE_URL}/geography/resolve?${params}`);
  if (!response.ok) throw new Error("Jurisdiction resolution failed.");
  return response.json();
}

export async function getSuitabilityGrid(
  scope,
  species = "Pterois volitans",
  modelVersion = "pterois-volitans-suitability-v3"
) {
  if (!scope || !scope.region || !scope.jurisdiction) {
    throw new Error("A jurisdiction scope is required to load habitat suitability.");
  }
  const params = new URLSearchParams({
    model_version: modelVersion,
    region_slug: scope.region,
    jurisdiction_slug: scope.jurisdiction,
  });
  const response = await fetch(
    `${API_BASE_URL}/predictions/species/${encodeURIComponent(species)}/suitability/grid?${params}`
  );

  if (!response.ok) {
    throw new Error(
      "Failed to load habitat suitability."
    );
  }

  return response.json();
}

export async function getMonitoringPriorityGrid(
  scope,
  species = "Pterois volitans",
  predictionVersion = "pterois-volitans-next-area-v1"
) {
  if (!scope || !scope.region || !scope.jurisdiction) {
    throw new Error("A jurisdiction scope is required to load monitoring priority.");
  }
  const params = new URLSearchParams({
    prediction_version: predictionVersion,
    region_slug: scope.region,
    jurisdiction_slug: scope.jurisdiction,
    limit: "391",
  });
  const response = await fetch(
    `${API_BASE_URL}/predictions/species/${encodeURIComponent(species)}/next-areas?${params}`
  );

  if (!response.ok) {
    const error = new Error(
      response.status === 404
        ? "No monitoring-priority snapshot is currently available."
        : "Failed to load monitoring priority."
    );
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function getMonitoringPrioritySummary(
  scope,
  species = "Pterois volitans",
  predictionVersion = "pterois-volitans-next-area-v1"
) {
  if (!scope || !scope.region || !scope.jurisdiction) {
    throw new Error("A jurisdiction scope is required to load monitoring-priority summary.");
  }
  const params = new URLSearchParams({
    prediction_version: predictionVersion,
    region_slug: scope.region,
    jurisdiction_slug: scope.jurisdiction,
  });
  const response = await fetch(
    `${API_BASE_URL}/predictions/species/${encodeURIComponent(species)}/next-areas/summary?${params}`
  );

  if (!response.ok) {
    const error = new Error(
      response.status === 404
        ? "No monitoring-priority snapshot is currently available."
        : "Failed to load monitoring-priority summary."
    );
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export async function getMonitoringPriorityFreshness(
  scope,
  species = "Pterois volitans",
  predictionVersion = "pterois-volitans-next-area-v1"
) {
  if (!scope || !scope.region || !scope.jurisdiction) {
    throw new Error("A jurisdiction scope is required to load monitoring-priority freshness.");
  }
  const params = new URLSearchParams({
    prediction_version: predictionVersion,
    region_slug: scope.region,
    jurisdiction_slug: scope.jurisdiction,
  });
  const response = await fetch(
    `${API_BASE_URL}/predictions/species/${encodeURIComponent(species)}/next-areas/freshness?${params}`
  );

  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? "No monitoring-priority snapshot is currently available."
        : "Unable to check snapshot freshness."
    );
  }

  return response.json();
}

export async function regenerateMonitoringPriorities(
  scope,
  species = "Pterois volitans",
  predictionVersion = "pterois-volitans-next-area-v1"
) {
  if (!scope || !scope.region || !scope.jurisdiction) {
    throw new Error("A jurisdiction scope is required to refresh monitoring priorities.");
  }
  const params = new URLSearchParams({
    prediction_version: predictionVersion,
    region_slug: scope.region,
    jurisdiction_slug: scope.jurisdiction,
  });
  const response = await fetch(
    `${API_BASE_URL}/predictions/species/${encodeURIComponent(species)}/next-areas/regenerate?${params}`,
    { method: "POST", headers: authHeaders() }
  );

  if (!response.ok) {
    let message = "Monitoring-priority refresh failed. The previous snapshot remains available.";
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // Keep the safe default message.
    }
    throw new Error(message);
  }

  return response.json();
}

async function governedMediaRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = "Unable to load governed visual-corpus data.";
    try { message = (await response.json()).detail || message; } catch { /* retain safe message */ }
    throw new Error(message);
  }
  return response.json();
}

export const getIdentificationMediaSources = () => governedMediaRequest("/admin/identification-corpus/media-sources");
export const getIdentificationCorpusPlans = () => governedMediaRequest("/admin/identification-corpus/plans");
export const getIdentificationAcquisitionRuns = () => governedMediaRequest("/admin/identification-corpus/acquisition-runs");
export const getIdentificationMediaAssets = (taxonId) => governedMediaRequest(`/admin/identification-corpus/assets${taxonId ? `?taxon_id=${taxonId}` : ""}`);
export const getIdentificationCorpora = () => governedMediaRequest("/admin/identification-corpus/corpora");
export const reviewIdentificationMediaAsset = (assetId, decision, reference) => governedMediaRequest(`/admin/identification-corpus/assets/${assetId}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, reference }) });
export const acquireCommonsTaxonomyEvidence = (assetId) => governedMediaRequest(`/admin/identification-corpus/assets/${assetId}/taxonomy-evidence/commons`, { method: "POST" });
export const resolveIdentificationMediaTaxonomy = (assetId, resolutionState, reason, evidenceIds) => governedMediaRequest(`/admin/identification-corpus/assets/${assetId}/taxonomy-resolution`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolution_state: resolutionState, reason, evidence_ids: evidenceIds }) });
export async function getIdentificationMediaContent(assetId) {
  const response = await fetch(`${API_BASE_URL}/admin/identification-corpus/assets/${assetId}/content`, { headers: authHeaders() });
  if (!response.ok) throw new Error("Controlled media content is unavailable.");
  return response.blob();
}
