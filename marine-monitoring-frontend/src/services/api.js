const API_BASE_URL = "http://127.0.0.1:8000";

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
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: authHeaders(options.body ? { "Content-Type": "application/json", ...(options.headers || {}) } : options.headers || {}) });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Administrative request failed."); }
  return response.json();
}

export const getAdminOverview = () => adminRequest("/admin/overview");
export const getAdminRegions = () => adminRequest("/admin/regions");
export const createAdminRegion = (payload) => adminRequest("/admin/regions", { method: "POST", body: JSON.stringify(payload) });
export const updateAdminRegion = (id, payload) => adminRequest(`/admin/regions/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const getAdminJurisdictions = () => adminRequest("/admin/jurisdictions");
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
}) {
  const formData = new FormData();

  formData.append("image", image);
  formData.append("latitude", latitude);
  formData.append("longitude", longitude);
  if (locationAccuracy != null) formData.append("location_accuracy_m", locationAccuracy);
  if (locationCapturedAt) formData.append("location_captured_at", locationCapturedAt);
  formData.append("location_source", locationSource || "MANUAL");

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
