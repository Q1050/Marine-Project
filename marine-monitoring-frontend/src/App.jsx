import { useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import AppShell from "./components/AppShell";
import RegionalMapPage from "./pages/RegionalMapPage";
import RegionalAnalyticsPage from "./pages/RegionalAnalyticsPage";
import RegionalSpeciesIntelligencePage from "./pages/RegionalSpeciesIntelligencePage";
import JurisdictionSpeciesPage from "./pages/JurisdictionSpeciesPage";
import OverviewPage from "./pages/OverviewPage";
import MapPage from "./pages/MapPage";
import SubmitPage from "./pages/SubmitPage";
import ReviewPage from "./pages/ReviewPage";
import ObservationsPage from "./pages/ObservationsPage";
import InvestigationsPage from "./pages/InvestigationsPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import { AdminOverviewPage, OrganizationsRegistryPage, RegionsRegistryPage, SpeciesProgramsRegistryPage, UsersRegistryPage } from "./pages/AdminRegistryPage";
import AdminJurisdictionOnboardingPage from "./pages/AdminJurisdictionOnboardingPage";
import AdminScientificReadinessPage from "./pages/AdminScientificReadinessPage";
import AgencySciencePage from "./pages/AgencySciencePage";
import AdminEarlyWarningPage from "./pages/AdminEarlyWarningPage";
import AdminTaxonomyPage from "./pages/AdminTaxonomyPage";
import AdminObservationOperationsPage from "./pages/AdminObservationOperationsPage";
import ReviewerHomePage from "./pages/ReviewerHomePage";
import AdminReviewerAccessPage from "./pages/AdminReviewerAccessPage";
import AdminSystemStatusPage from "./pages/AdminSystemStatusPage";
import ReporterStatusPage from "./pages/ReporterStatusPage";
import LoginPage from "./pages/LoginPage";
import { PublicJurisdictionPage, PublicRegionPage, PublicRegionsPage, PublicSpeciesDetailPage, PublicSpeciesDirectoryPage } from "./pages/PublicDirectoryPages";
import { jurisdictionRoles, useAuth } from "./auth/AuthContext";
import { hasProtectedAccess } from "./auth/access";
import { JurisdictionProvider, useJurisdiction } from "./geography/JurisdictionContext";
import "./App.css";

const COUNTRY_PLACEHOLDERS = {
  analytics: ["Monitoring analytics", "Operational metrics for the active jurisdiction.", "Analytics foundation", "Dedicated country analytics will expand as backend summary endpoints are added."],
};
const ADMIN_PAGES = {
  overview: ["Platform Administration", "Manage the monitoring platform structure.", "Administration foundation", "No administrative backend actions are configured."],
  regions: ["Regions", "Manage geographic monitoring regions.", "Caribbean · Active", "Region management APIs are not configured."],
  jurisdictions: ["Jurisdictions", "Manage countries and territories within monitoring regions.", "Jamaica · Configured", "Jurisdiction management APIs are not configured."],
  organizations: ["Organizations", "Manage participating authorities and research partners.", "No organization directory configured", "Organizations will participate in shared country workspaces."],
  users: ["Users", "Manage trusted platform users and future access roles.", "User administration not configured", "Authentication and permissions are outside this task."],
  "species-programs": ["Scientific deployments", "Validated per-jurisdiction scientific deployments of monitored species.", "Pterois volitans", "Program administration APIs are not configured."],
  system: ["System", "Platform configuration and operational settings.", "Configuration foundation", "No destructive system controls are exposed."],
};

export default function App() {
  return <JurisdictionProvider><Application /></JurisdictionProvider>;
}

function Application() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const geographicContext = useJurisdiction();
  const { scope, activeRegion, activeJurisdiction } = geographicContext;
  const [mapRefreshKey, setMapRefreshKey] = useState(0);
  const [regionalJurisdiction, setRegionalJurisdiction] = useState(null);
  const refreshMap = () => setMapRefreshKey((value) => value + 1);
  const countryNavigate = (page, region = activeRegion, jurisdiction = activeJurisdiction) => navigate(`/region/${region}/${jurisdiction}/${page}`);

  if (location.pathname === "/login") return <LoginPage />;
  if (location.pathname.startsWith("/admin") && authLoading) return <div className="grid min-h-screen place-items-center text-sm text-app-muted">Checking platform access…</div>;
  if (location.pathname.startsWith("/admin") && !user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  const reviewerRoute = location.pathname === "/admin/observations" || location.pathname.startsWith("/admin/observations/");
  if (location.pathname.startsWith("/admin") && !reviewerRoute && !user.is_platform_admin) return <Navigate to="/region/caribbean/jamaica/overview" replace />;

  return <AppShell scope={scope} viewportJurisdiction={regionalJurisdiction}>
    <Routes>
      <Route path="/" element={<Navigate to="/region/caribbean" replace />} />
      <Route path="/regions" element={<PublicRegionsPage />} />
      <Route path="/regions/:regionSlug" element={<PublicRegionPage />} />
      <Route path="/jurisdictions/:jurisdiction" element={<PublicJurisdictionPage />} />
      <Route path="/jurisdictions/:jurisdictionId/marine-species" element={<PublicSpeciesDirectoryPage />} />
      <Route path="/jurisdictions/:jurisdictionId/invasive-species" element={<PublicSpeciesDirectoryPage invasive />} />
      <Route path="/jurisdictions/:jurisdictionId/species/:taxonId" element={<PublicSpeciesDetailPage />} />
      <Route path="/region/caribbean" element={<RegionalMapPage onOpenJurisdiction={(jurisdiction) => countryNavigate("map", "caribbean", jurisdiction)} onGeographicContextChange={setRegionalJurisdiction} />} />
      <Route path="/region/caribbean/observations" element={<ObservationsPage scope="regional" onOpenMap={() => navigate("/region/caribbean")} />} />
      <Route path="/region/caribbean/species" element={<RegionalSpeciesIntelligencePage />} />
      <Route path="/region/caribbean/analytics" element={<RegionalAnalyticsPage />} />
      <Route path="/region/caribbean/submit" element={<SubmitPage onObservationCreated={refreshMap} />} />

      <Route path="/region/:regionSlug/:jurisdictionSlug/overview" element={<JurisdictionReady><OverviewPage onNavigate={countryNavigate} /></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/map" element={<JurisdictionReady><MapPage refreshKey={mapRefreshKey} /></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/observations" element={<JurisdictionReady><ObservationsPage scope="country" onOpenMap={() => countryNavigate("map")} /></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/review" element={<JurisdictionReady><ProtectedRoute access="review"><ReviewPage onObservationUpdated={refreshMap} /></ProtectedRoute></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/investigations" element={<JurisdictionReady><ProtectedRoute access="investigations"><InvestigationsPage /></ProtectedRoute></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/submit" element={<JurisdictionReady><SubmitPage onObservationCreated={refreshMap} /></JurisdictionReady>} />
      {Object.entries(COUNTRY_PLACEHOLDERS).map(([path, values]) => <Route key={path} path={`/region/:regionSlug/:jurisdictionSlug/${path}`} element={<JurisdictionReady><ConfiguredPlaceholder values={values} /></JurisdictionReady>} />)}
      <Route path="/region/:regionSlug/:jurisdictionSlug/species" element={<JurisdictionReady><JurisdictionSpeciesPage /></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/scientific-readiness" element={<JurisdictionReady><ProtectedRoute access="investigations"><AgencySciencePage view="scientific-readiness" /></ProtectedRoute></JurisdictionReady>} />
      <Route path="/region/:regionSlug/:jurisdictionSlug/early-warning" element={<JurisdictionReady><ProtectedRoute access="investigations"><AgencySciencePage view="early-warning" /></ProtectedRoute></JurisdictionReady>} />

      <Route path="/submit" element={<SubmitPage onObservationCreated={refreshMap} />} />
      <Route path="/reporter/status/:token" element={<ReporterStatusPage />} />
      <Route path="/admin" element={<ProtectedRoute access="admin"><AdminOverviewPage /></ProtectedRoute>} />
      <Route path="/admin/regions" element={<ProtectedRoute access="admin"><RegionsRegistryPage /></ProtectedRoute>} />
      <Route path="/admin/jurisdictions" element={<ProtectedRoute access="admin"><AdminJurisdictionOnboardingPage /></ProtectedRoute>} />
      <Route path="/admin/organizations" element={<ProtectedRoute access="admin"><OrganizationsRegistryPage /></ProtectedRoute>} />
      <Route path="/admin/users" element={<ProtectedRoute access="admin"><UsersRegistryPage /></ProtectedRoute>} />
      <Route path="/admin/species-programs" element={<ProtectedRoute access="admin"><SpeciesProgramsRegistryPage /></ProtectedRoute>} />
      <Route path="/admin/scientific-readiness" element={<ProtectedRoute access="admin"><AdminScientificReadinessPage /></ProtectedRoute>} />
      <Route path="/admin/early-warning" element={<ProtectedRoute access="admin"><AdminEarlyWarningPage /></ProtectedRoute>} />
      <Route path="/scientific-review/early-warning" element={<ProtectedRoute access="scientific-review"><AdminEarlyWarningPage scientific /></ProtectedRoute>} />
      <Route path="/admin/taxonomy" element={<ProtectedRoute access="admin"><AdminTaxonomyPage /></ProtectedRoute>} />
      <Route path="/admin/observations" element={<ProtectedRoute access="observation-review"><AdminObservationOperationsPage /></ProtectedRoute>} />
      <Route path="/reviewer" element={<ProtectedRoute access="observation-review"><ReviewerHomePage /></ProtectedRoute>} />
      <Route path="/admin/reviewers" element={<ProtectedRoute access="admin"><AdminReviewerAccessPage /></ProtectedRoute>} />
      <Route path="/admin/system" element={<ProtectedRoute access="admin"><AdminSystemStatusPage /></ProtectedRoute>} />
      {Object.entries(ADMIN_PAGES).filter(([path]) => !["overview", "regions", "jurisdictions", "organizations", "users", "species-programs"].includes(path)).map(([path, values]) => <Route key={path} path={`/admin/${path}`} element={<ProtectedRoute access="admin"><ConfiguredPlaceholder values={values} /></ProtectedRoute>} />)}

      <Route path="/map" element={<Navigate to="/region/caribbean/jamaica/map" replace />} />
      <Route path="/region/caribbean/map" element={<LegacyRegionalRedirect />} />
      <Route path="/observations" element={<Navigate to="/region/caribbean/observations" replace />} />
      <Route path="/review" element={<Navigate to="/region/caribbean/jamaica/review" replace />} />
      <Route path="*" element={<Navigate to="/region/caribbean" replace />} />
    </Routes>
  </AppShell>;
}

function ProtectedRoute({ access, children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  const { activeRegion, activeJurisdiction } = useJurisdiction();
  if (loading) return <div className="grid min-h-[50vh] place-items-center text-sm text-app-muted">Checking trusted access…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  const roles = jurisdictionRoles(user, activeRegion, activeJurisdiction);
  const allowed = hasProtectedAccess(user, access, roles);
  return allowed ? children : <Navigate to={`/region/${activeRegion}/${activeJurisdiction}/overview`} replace />;
}

function JurisdictionReady({ children }) {
  const { loading, error } = useJurisdiction();
  if (loading) return <div className="grid min-h-[50vh] place-items-center text-sm text-app-muted">Loading jurisdiction…</div>;
  if (error) return <Navigate to="/region/caribbean" replace />;
  return children;
}

function LegacyRegionalRedirect() {
  const location = useLocation();
  return <Navigate to={`/region/caribbean${location.search}`} replace />;
}

function ConfiguredPlaceholder({ values }) {
  const { scope, jurisdiction } = useJurisdiction();
  const [title, description, emptyTitle, emptyText] = values;
  const eyebrow = scope === "admin" ? "Platform administration" : scope === "regional" ? "Caribbean regional monitoring" : `${jurisdiction?.name || "Jurisdiction"} workspace`;
  return <PlaceholderPage eyebrow={eyebrow} title={title} description={description} emptyTitle={emptyTitle} emptyText={emptyText} />;
}
