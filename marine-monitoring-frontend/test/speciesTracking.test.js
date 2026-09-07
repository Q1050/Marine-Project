import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { formatTaxonomyLineage, indexedTaxaLabel, safeDisplayText } from "../src/utils/speciesPresentation.js";

const map = readFileSync(new URL("../src/pages/RegionalMapPage.jsx", import.meta.url), "utf8");
const species = readFileSync(new URL("../src/pages/RegionalSpeciesIntelligencePage.jsx", import.meta.url), "utf8");
const countrySpecies = readFileSync(new URL("../src/pages/JurisdictionSpeciesPage.jsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/services/api.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/App.css", import.meta.url), "utf8");
const backend = readFileSync(new URL("../../public_media_service.py", import.meta.url), "utf8");

test("species tracking renders dynamic confirmed layers and marker navigation", () => {
  assert.match(map, /SpeciesTrackingPanel/);
  assert.match(map, /confirmed_location_count/);
  assert.match(map, /verification_status/);
  assert.match(map, /returnLat/);
  assert.match(map, /Open species intelligence/);
});

test("catalog search and real record count use public read contracts", () => {
  assert.match(api, /getSpeciesCatalog/);
  assert.match(species, /catalog\.count/);
  assert.match(species, /authoritative_identifier/);
  assert.doesNotMatch(species, /2,840|Queen Conch|Tiger Prawn|Nassau Grouper|Elkhorn Coral/);
});

test("missing scientific assertions remain explicit", () => {
  assert.match(species, /Ecological status: Not available/);
  assert.match(species, /Monitoring priority: Not available/);
  assert.match(species, /diagnostic reference are not yet available/);
});

test("tracking and catalog provide narrow-width fallbacks", () => {
  assert.match(css, /species-tracking-launcher/);
  assert.match(css, /@media \(max-width: 850px\)/);
  assert.match(css, /species-catalog-page/);
});

test("structured taxonomy levels render as human-readable rank and name pairs", () => {
  const result = formatTaxonomyLineage({ classification: [
    { aphia_id: "2", rank: "Kingdom", scientific_name: "Animalia" },
    { rank: "Phylum", scientific_name: "Chordata" },
    { rank: null, scientific_name: "Skipped" },
    { rank: "Class", scientific_name: { unexpected: true } },
  ] });
  assert.deepEqual(result, ["Kingdom: Animalia", "Phylum: Chordata"]);
  assert.equal(result.join(" › ").includes("[object Object]"), false);
});

test("indexed taxon count uses singular and plural backend-derived grammar", () => {
  assert.equal(indexedTaxaLabel(1), "1 indexed taxon");
  assert.equal(indexedTaxaLabel(0), "0 indexed taxa");
  assert.equal(indexedTaxaLabel(27), "27 indexed taxa");
});

test("unsafe object and sentinel values cannot reach presentation text", () => {
  for (const value of [{ value: "raw" }, undefined, null, "[object Object]", "[object Promise]"]) {
    assert.equal(safeDisplayText(value, "Unavailable"), "Unavailable");
  }
});

test("species common name and section headings have explicit readable contrast", () => {
  assert.match(species, /species-intelligence__names/);
  assert.match(css, /\.species-intelligence__names h1[^}]*color:#172635[^}]*font-weight:800/);
  assert.match(css, /\.species-intelligence__section h2[^}]*color:#172635[^}]*font-weight:750/);
});

test("reference gallery uses governed public-compatible visual corpus media", () => {
  assert.match(species, /Reference imagery/);
  assert.match(species, /getPublicTaxonMedia/);
  assert.match(species, /attribution_text/);
  assert.match(species, /license_url/);
  assert.match(backend, /review_state=="APPROVED"/);
  assert.match(backend, /quality_state=="VALID"/);
  assert.match(backend, /PUBLIC_REFERENCE_LICENSES/);
  assert.match(backend, /PUBLIC_REFERENCE_TAXONOMY/);
});

test("life-stage labels come only from stored media metadata", () => {
  assert.match(species, /safeDisplayText\(item\.life_stage\)/);
  assert.doesNotMatch(species, /life_stage.*juvenile|juvenile.*life_stage/i);
});

test("Country species reuses shared intelligence with jurisdiction-scoped operational context", () => {
  assert.match(species, /export function SpeciesCard/);
  assert.match(species, /export function SpeciesIntelligence/);
  assert.match(countrySpecies, /SpeciesCard, SpeciesIntelligence/);
  assert.match(countrySpecies, /getJurisdictionSpeciesIntelligence/);
  assert.match(countrySpecies, /getSpeciesCatalogDetail/);
  assert.match(countrySpecies, /getPublicTaxonMedia/);
  assert.match(countrySpecies, /verifiedReports: evidence\.verified_or_corrected/);
  assert.match(species, /Species program/);
  assert.match(species, /Habitat suitability/);
  assert.match(species, /Monitoring priority/);
  assert.match(countrySpecies, /do not resolve to the canonical Country catalog/);
});
