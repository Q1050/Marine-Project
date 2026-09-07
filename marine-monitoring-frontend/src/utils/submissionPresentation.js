export const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export function validateObservationImage(file) {
  if (!file) return "Please select an image.";
  if (!ACCEPTED_IMAGE_TYPES.has(file.type)) return "Image must be JPEG, PNG, or WEBP.";
  if (file.size > MAX_IMAGE_BYTES) return "Image exceeds the 10 MB upload-size limit.";
  return null;
}

export function canSubmitObservation({ image, latitude, longitude, locationConfirmed, resolution, submitting }) {
  return Boolean(image && latitude !== "" && longitude !== "" && locationConfirmed && resolution?.status === "RESOLVED" && !submitting);
}

export function similarityLabel(value) {
  if (value === null || value === undefined || value === "") return "Not available";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(3) : "Not available";
}

export function alternativeCandidates(identification) {
  const primary = identification?.species;
  return (identification?.candidates || []).filter((candidate) => candidate?.scientific_name && candidate.scientific_name !== primary).slice(0, 4);
}
