const cartoApiKey = import.meta.env.VITE_CARTO_API_KEY?.trim();

export const BASEMAP = cartoApiKey
  ? {
      provider: "CARTO",
      url: `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(cartoApiKey)}`,
      attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
      configured: true,
    }
  : {
      provider: "OpenStreetMap fallback",
      url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: "&copy; OpenStreetMap contributors",
      configured: false,
    };
