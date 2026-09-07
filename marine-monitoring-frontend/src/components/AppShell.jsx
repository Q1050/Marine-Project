import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { NAVIGATION, submissionRouteForScope } from "../config/navigation";
import { jurisdictionRoles, useAuth } from "../auth/AuthContext";
import { useJurisdiction } from "../geography/JurisdictionContext";
import { navigationSectionLabel, showPlatformAdminReturn } from "../config/shellPresentation";

export default function AppShell({ scope, viewportJurisdiction, children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const { activeRegion, activeJurisdiction, jurisdiction } = useJurisdiction();
  const roles = jurisdictionRoles(user, activeRegion, activeJurisdiction);
  const canReview =
    user?.is_platform_admin ||
    roles.some((role) => ["REVIEWER", "MANAGER"].includes(role));
  const canViewInvestigations =
    user?.is_platform_admin ||
    roles.some((role) => ["VIEWER", "REVIEWER", "MANAGER"].includes(role));
  const navigation = (NAVIGATION[scope] || NAVIGATION.public).map((item) => scope === "country" ? { ...item, to: `/region/${activeRegion}/${activeJurisdiction}/${item.id}` } : item).filter(
    (item) => (item.id !== "review" || canReview) &&
      (item.id !== "investigations" || canViewInvestigations) &&
      (!["scientific-readiness", "early-warning"].includes(item.id) || canViewInvestigations) &&
      (item.id !== "observation-operations" || user?.is_platform_admin || user?.operational_review?.enabled) &&
      (item.id !== "scientific-early-warning" || user?.is_platform_admin || user?.scientific_review?.enabled),
  );
  const isMapPage = location.pathname === "/region/caribbean" || (scope === "country" && location.pathname.endsWith("/map"));
  const context = shellContext(scope, viewportJurisdiction, jurisdiction);
  const submitUrl = submissionRouteForScope(scope, activeRegion, activeJurisdiction);
  const regionalUrl = (
    sessionStorage.getItem("caribbeanRegionalUrl") || "/region/caribbean"
  ).replace("/region/caribbean/map", "/region/caribbean");
  const isDemonstration = import.meta.env.VITE_APP_ENV === "DEMO";
  const navigationLabel = navigationSectionLabel(scope, context.jurisdictionName);

  return (
    <div className="app-shell min-h-screen bg-surface-subtle text-app-text lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="app-shell-sidebar sticky top-0 z-[1200] flex h-auto border-b border-app-border bg-white lg:h-screen lg:flex-col lg:border-b-0 lg:border-r">
        <button
          className="flex min-w-[220px] items-center gap-3 px-5 py-4 text-left"
          onClick={() => navigate(scope === "admin" ? "/admin" : regionalUrl)}
        >
          <span
            className="grid h-9 w-9 place-items-center rounded-xl bg-ocean-900 text-lg text-white"
            aria-hidden="true"
          >
            ≋
          </span>
          <span>
            <strong className="block text-sm leading-tight">
              {scope === "admin"
                ? "Platform Administration"
                : "Caribbean Marine Monitor"}
            </strong>
            <small className="text-xs text-app-muted">
              {context.workspace}
            </small>
          </span>
        </button>
        {showPlatformAdminReturn(scope, user) && (
          <NavLink
            to="/admin"
            className="mx-3 mb-1 rounded-lg border border-app-border px-3 py-2 text-xs font-bold text-teal-700 hover:bg-teal-50"
          >
            ← Back to Platform Administration
          </NavLink>
        )}
        {scope === "admin" && location.pathname !== "/admin" && (
          <NavLink
            to="/admin"
            className="mx-3 mb-1 rounded-lg border border-app-border px-3 py-2 text-xs font-bold text-teal-700 hover:bg-teal-50"
          >
            ← Back to Admin overview
          </NavLink>
        )}
        <nav
          className="flex flex-1 gap-1 overflow-x-auto px-2 pb-2 lg:block lg:overflow-visible lg:px-3 lg:py-3"
          aria-label="Primary navigation"
        >
          <p className="hidden px-3 pb-2 pt-4 text-[10px] font-bold uppercase tracking-[.16em] text-app-muted lg:block">
            {navigationLabel}
          </p>
          {navigation.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition lg:mb-1 lg:w-full ${isActive ? "bg-teal-100 text-teal-700" : "text-slate-600 hover:bg-slate-50 hover:text-app-text"}`
              }
            >
              <span className="w-5 text-center" aria-hidden="true">
                {item.icon}
              </span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        {scope !== "admin" && (
          <div className="hidden border-t border-app-border p-3 lg:block">
            <NavLink
              to={submitUrl}
              className="mb-3 block w-full rounded-lg bg-teal-700 px-4 py-3 text-center text-sm font-bold text-white hover:bg-teal-600"
            >
              ＋ Submit sighting
            </NavLink>
          </div>
        )}
      </aside>
      <section className="app-shell-content min-w-0">
        {isDemonstration && (
          <div className="bg-amber-100 px-4 py-2 text-center text-xs font-bold uppercase tracking-[.14em] text-amber-900" role="status">
            Demonstration data and workflows — not operational scientific evidence
          </div>
        )}
        <TopHeader
          scope={scope}
          context={context}
          user={user}
          onSignOut={async () => {
            await signOut();
            navigate("/region/caribbean");
          }}
          onSignIn={() => navigate("/login")}
          onBackToRegion={() => navigate(regionalUrl)}
        />
        <main
          className={
            isMapPage
              ? "h-[calc(100vh-137px)] lg:h-[calc(100vh-64px)]"
              : "p-4 sm:p-6 lg:p-8"
          }
        >
          {children}
        </main>
      </section>
      {scope !== "admin" && location.pathname !== "/submit" && !location.pathname.endsWith("/submit") && (
        <NavLink
          to={submitUrl}
          className="fixed bottom-4 right-4 z-[1300] rounded-full bg-teal-700 px-5 py-3 text-sm font-bold text-white shadow-lg lg:hidden"
        >
          ＋ Submit sighting
        </NavLink>
      )}
    </div>
  );
}

function TopHeader({ scope, context, user, onSignOut, onSignIn, onBackToRegion }) {
  return (
    <header className="app-top-header sticky top-[73px] z-[1100] flex h-16 items-center justify-between border-b border-app-border bg-white/95 px-4 backdrop-blur lg:top-0 lg:px-7">
      <div className="min-w-0">
        <p className="truncate text-[11px] font-bold uppercase tracking-[.15em] text-teal-700">
          {scope === "admin"
            ? "Platform administration"
            : "Invasive species tracker"}
        </p>
        <div className="flex items-baseline gap-1 text-xs text-app-muted">
          {scope === "country" ? (
            <>
              <button
                onClick={onBackToRegion}
                className="hover:text-teal-700 hover:underline"
              >
                Caribbean
              </button>
              <span>/</span>
              <strong className="text-app-text">{context.jurisdictionName}</strong>
            </>
          ) : (
            <strong className="text-app-text">{context.breadcrumb}</strong>
          )}
          <span className="hidden sm:inline">· {context.subtitle}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {user ? <><span className="hidden text-xs font-semibold sm:inline">{user.display_name}</span><button onClick={onSignOut} className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold text-teal-700">Sign out</button></> : <button onClick={onSignIn} className="rounded-lg border border-app-border px-3 py-2 text-xs font-bold text-teal-700">Partner sign in</button>}
        <button className="hidden rounded-full border border-app-border bg-slate-50 px-4 py-2 text-xs text-app-muted sm:block">
          ⌕ Search coordinates or IDs
        </button>
        <button className="rounded-full p-2" aria-label="Notifications">
          ●
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-full bg-slate-200 text-xs font-bold">
          {scope === "admin" ? "PA" : context.countryCode || "CM"}
        </span>
      </div>
    </header>
  );
}

function shellContext(scope, viewportJurisdiction, jurisdiction) {
  if (scope === "admin")
    return {
      workspace: "System and configuration",
      breadcrumb: "Platform Administration",
      subtitle: "Platform structure",
    };
  if (scope === "country")
    return {
      workspace: `${jurisdiction?.name || "Jurisdiction"} workspace`,
      breadcrumb: `${jurisdiction?.region?.name || "Caribbean"} / ${jurisdiction?.name || "Jurisdiction"}`,
      subtitle: "Monitoring workspace",
      jurisdictionName: jurisdiction?.name || "Jurisdiction",
      countryCode: jurisdiction?.country_code,
    };
  if (scope === "regional")
    return {
      workspace: viewportJurisdiction
        ? `Viewing ${viewportJurisdiction}`
        : "Regional monitoring",
      breadcrumb: viewportJurisdiction
        ? `Caribbean / ${viewportJurisdiction}`
        : "Caribbean",
      subtitle: "Regional monitoring",
    };
  return {
    workspace: "Public exploration",
    breadcrumb: "Caribbean",
    subtitle: "Public monitoring",
  };
}
