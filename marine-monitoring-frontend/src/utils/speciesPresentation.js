export function safeDisplayText(value, fallback = "") {
  if (typeof value === "string") {
    const text = value.trim();
    return text && !["undefined", "null", "[object Object]", "[object Promise]"].includes(text) ? text : fallback;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

export function formatTaxonomyLineage(taxonomy) {
  const lineage = taxonomy?.lineage || taxonomy?.classification;
  if (!Array.isArray(lineage)) return [];
  return lineage.flatMap((level) => {
    if (!level || typeof level !== "object" || Array.isArray(level)) return [];
    const rank = safeDisplayText(level.rank || level.taxonomic_rank);
    const name = safeDisplayText(level.scientific_name || level.name || level.canonical_name);
    return rank && name ? [`${rank}: ${name}`] : [];
  });
}

export function indexedTaxaLabel(count) {
  const numericCount = Number.isFinite(Number(count)) ? Number(count) : 0;
  return `${numericCount.toLocaleString()} indexed ${numericCount === 1 ? "taxon" : "taxa"}`;
}
