export function deviceLocationProposal(position) {
  return {
    latitude: position.coords.latitude.toFixed(6),
    longitude: position.coords.longitude.toFixed(6),
    source: "DEVICE_GEOLOCATION",
    accuracy: position.coords.accuracy ?? null,
    capturedAt: new Date(position.timestamp || Date.now()).toISOString(),
    confirmed: false,
    resolution: null,
  };
}

export function adjustedLocation(latitude, longitude, source) {
  return {
    latitude: String(latitude),
    longitude: String(longitude),
    source,
    accuracy: null,
    capturedAt: null,
    confirmed: false,
    resolution: null,
  };
}

export function confirmedLocation(location, resolution) {
  return { ...location, confirmed: true, resolution };
}
