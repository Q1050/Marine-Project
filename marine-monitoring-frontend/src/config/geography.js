export const REGIONS = {
  caribbean: {
    id: "caribbean",
    name: "Caribbean",
    bounds: [[8.0, -89.5], [27.8, -57.0]],
    defaultCenter: [17.9, -73.25],
    defaultZoom: 5,
    jurisdictions: [
      { id: "jamaica", name: "Jamaica", region: "caribbean", bounds: [[17.65, -78.45], [18.65, -76.15]], center: [18.1096, -77.2975], configured: true, status: "monitoring-active", route: "/region/caribbean/jamaica/map" },
      { id: "bahamas", name: "The Bahamas", contextName: "Bahamas", region: "caribbean", bounds: [[20.8, -79.0], [27.0, -72.4]], center: [24.25, -76.0], configured: false, status: "planned" },
      { id: "barbados", name: "Barbados", region: "caribbean", bounds: [[12.8, -59.75], [13.4, -59.35]], center: [13.19, -59.54], configured: false, status: "planned" },
      { id: "dominican-republic", name: "Dominican Republic", region: "caribbean", bounds: [[17.45, -72.05], [19.95, -68.25]], center: [18.74, -70.16], configured: false, status: "planned" },
      { id: "trinidad-and-tobago", name: "Trinidad and Tobago", region: "caribbean", bounds: [[9.8, -62.1], [11.45, -60.45]], center: [10.44, -61.31], configured: false, status: "planned" },
    ],
  },
};

export function isValidRegionalViewport(viewport, region = REGIONS.caribbean) {
  if (!viewport || !Number.isFinite(viewport.lat) || !Number.isFinite(viewport.lng) || !Number.isFinite(viewport.zoom)) return false;
  const [[south, west], [north, east]] = region.bounds;
  const geographicMargin = 4;
  return viewport.lat >= south - geographicMargin && viewport.lat <= north + geographicMargin
    && viewport.lng >= west - geographicMargin && viewport.lng <= east + geographicMargin
    && viewport.zoom >= 4 && viewport.zoom <= 10;
}

export function jurisdictionForViewport(center, zoom, region = REGIONS.caribbean) {
  if (zoom < 6.75) return null;
  return region.jurisdictions.find((jurisdiction) => {
    const [[south, west], [north, east]] = jurisdiction.bounds;
    return center.lat >= south && center.lat <= north && center.lng >= west && center.lng <= east;
  }) || null;
}
