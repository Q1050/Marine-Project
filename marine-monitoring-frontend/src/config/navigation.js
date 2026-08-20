export const NAVIGATION = {
  public: [
    { id: "explore", label: "Explore", icon: "◇", to: "/region/caribbean" },
    { id: "observations", label: "Observations", icon: "◉", to: "/region/caribbean/observations" },
    { id: "species", label: "Species", icon: "♧", to: "/region/caribbean/species" },
  ],
  regional: [
    { id: "overview", label: "Overview", icon: "◇", to: "/region/caribbean", end: true },
    { id: "observations", label: "Observations", icon: "◉", to: "/region/caribbean/observations" },
    { id: "species", label: "Species", icon: "♧", to: "/region/caribbean/species" },
    { id: "analytics", label: "Analytics", icon: "▥", to: "/region/caribbean/analytics" },
  ],
  country: [
    { id: "overview", label: "Overview", icon: "◇" },
    { id: "map", label: "Monitoring map", icon: "⌖" },
    { id: "observations", label: "Observations", icon: "◉" },
    { id: "review", label: "Review queue", icon: "☑" },
    { id: "investigations", label: "Investigations", icon: "⌕" },
    { id: "species", label: "Species", icon: "♧" },
    { id: "analytics", label: "Analytics", icon: "▥" },
  ],
  admin: [
    { id: "admin-overview", label: "Overview", icon: "◇", to: "/admin", end: true },
    { id: "regions", label: "Regions", icon: "◎", to: "/admin/regions" },
    { id: "jurisdictions", label: "Jurisdictions", icon: "⌖", to: "/admin/jurisdictions" },
    { id: "organizations", label: "Organizations", icon: "▦", to: "/admin/organizations" },
    { id: "users", label: "Users", icon: "◉", to: "/admin/users" },
    { id: "species-programs", label: "Scientific deployments", icon: "♧", to: "/admin/species-programs" },
    { id: "system", label: "System", icon: "⚙", to: "/admin/system" },
  ],
};

export function routeContext(pathname) {
  if (pathname.startsWith("/admin")) return { scope: "admin", activeRegion: null, activeJurisdiction: null };
  const countryMatch = pathname.match(/^\/region\/([^/]+)\/([^/]+)\/(overview|map|observations|review|submit|investigations|species|analytics)(?:\/|$)/);
  if (countryMatch) return { scope: "country", activeRegion: countryMatch[1], activeJurisdiction: countryMatch[2] };
  if (pathname.startsWith("/region/caribbean")) return { scope: "regional", activeRegion: "caribbean", activeJurisdiction: null };
  if (pathname === "/submit") return { scope: "public", activeRegion: "caribbean", activeJurisdiction: null };
  return { scope: "public", activeRegion: null, activeJurisdiction: null };
}
