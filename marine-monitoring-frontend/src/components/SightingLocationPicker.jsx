import { useEffect, useMemo } from "react";
import L from "leaflet";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import { BASEMAP } from "../config/basemap";

import "leaflet/dist/leaflet.css";

const markerIcon = L.divIcon({
  className: "",
  html: '<span class="block h-6 w-6 rounded-full border-[3px] border-white bg-teal-600 shadow-lg ring-2 ring-teal-800"></span>',
  iconAnchor: [12, 12],
  iconSize: [24, 24],
});

function MapInteraction({ position, onSelect }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.setView(position, Math.max(map.getZoom(), 11));
  }, [map, position]);
  useMapEvents({ click: (event) => onSelect(event.latlng.lat, event.latlng.lng) });
  return position ? (
    <Marker
      draggable
      position={position}
      icon={markerIcon}
      eventHandlers={{
        dragend: (event) => {
          const point = event.target.getLatLng();
          onSelect(point.lat, point.lng);
        },
      }}
    />
  ) : null;
}

export default function SightingLocationPicker({ latitude, longitude, onSelect }) {
  const position = useMemo(() => {
    const lat = Number(latitude);
    const lng = Number(longitude);
    return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null;
  }, [latitude, longitude]);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      <MapContainer
        center={position || [18.1096, -77.2975]}
        zoom={position ? 11 : 7}
        minZoom={4}
        maxZoom={18}
        className="h-64 w-full sm:h-72"
        scrollWheelZoom
      >
        <TileLayer
          attribution={BASEMAP.attribution}
          url={BASEMAP.url}
        />
        <MapInteraction position={position} onSelect={onSelect} />
      </MapContainer>
      <p className="border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
        Tap the map or drag the marker to the place where the sighting occurred.
      </p>
    </div>
  );
}
