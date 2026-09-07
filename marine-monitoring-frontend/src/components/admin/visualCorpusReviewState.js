export const REVIEWABLE_MEDIA_STATES = new Set([
  "READY_FOR_REVIEW",
  "REVIEW_REQUIRED",
]);
export const TAXONOMY_RESOLUTION_ACTIONS = [
  ["CONFIRMED_TARGET_TAXON", "Confirm target taxon"],
  ["DIFFERENT_TAXON", "Different taxon"],
  ["AMBIGUOUS", "Ambiguous"],
  ["INSUFFICIENT_EVIDENCE", "Insufficient evidence"],
];

export function normalizeResolutionReason(reason) {
  return typeof reason === "string" ? reason.trim() : "";
}

export function isMediaReviewable(asset) {
  return Boolean(asset && REVIEWABLE_MEDIA_STATES.has(asset.review_state));
}

export function isTaxonomyReviewable(asset) {
  return Boolean(
    asset &&
    asset.review_state === "TAXONOMY_REVIEW_REQUIRED" &&
    (asset.taxonomy_history?.resolutions || []).length === 0,
  );
}

export function reviewNavigationAssets(assets, selectedId) {
  const selected = assets.find((asset) => asset.id === selectedId);
  return isMediaReviewable(selected)
    ? assets.filter(isMediaReviewable)
    : assets;
}

export function nextSelectionAfterDisposition({
  selectedId,
  reviewedId,
  beforeAssets,
  afterAssets,
}) {
  if (selectedId !== reviewedId) {
    return afterAssets.some((asset) => asset.id === selectedId)
      ? selectedId
      : null;
  }

  const beforeReviewable = beforeAssets.filter(isMediaReviewable);
  const afterReviewableIds = new Set(
    afterAssets.filter(isMediaReviewable).map((asset) => asset.id),
  );
  const reviewedIndex = beforeReviewable.findIndex(
    (asset) => asset.id === reviewedId,
  );

  if (reviewedIndex >= 0) {
    const later = beforeReviewable
      .slice(reviewedIndex + 1)
      .find((asset) => afterReviewableIds.has(asset.id));
    if (later) return later.id;
    const earlier = beforeReviewable
      .slice(0, reviewedIndex)
      .reverse()
      .find((asset) => afterReviewableIds.has(asset.id));
    if (earlier) return earlier.id;
  }

  return afterAssets.find(isMediaReviewable)?.id ?? null;
}

export function filterMediaAssets(assets, filter) {
  if (filter === "REVIEWABLE") return assets.filter(isMediaReviewable);
  if (filter === "TAXONOMY_REVIEW") return assets.filter(isTaxonomyReviewable);
  if (filter === "APPROVED")
    return assets.filter((asset) => asset.review_state === "APPROVED");
  if (filter === "EXCLUDED")
    return assets.filter((asset) => asset.review_state === "EXCLUDED");
  return assets;
}

export function taxonomyNavigationAssets(assets) {
  return assets.filter(isTaxonomyReviewable);
}

export function nextTaxonomySelectionAfterResolution({
  reviewedId,
  beforeAssets,
  afterAssets,
}) {
  const before = taxonomyNavigationAssets(beforeAssets);
  const remainingIds = new Set(
    taxonomyNavigationAssets(afterAssets).map((asset) => asset.id),
  );
  const index = before.findIndex((asset) => asset.id === reviewedId);
  const later = before
    .slice(index + 1)
    .find((asset) => remainingIds.has(asset.id));
  if (later) return later.id;
  const earlier = before
    .slice(0, Math.max(index, 0))
    .reverse()
    .find((asset) => remainingIds.has(asset.id));
  return earlier?.id ?? null;
}
