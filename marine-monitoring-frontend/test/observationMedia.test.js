import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const panel = readFileSync(new URL("../src/components/ObservationPanel.jsx", import.meta.url), "utf8");
const review = readFileSync(new URL("../src/pages/ReviewPage.jsx", import.meta.url), "utf8");
const hook = readFileSync(new URL("../src/hooks/useObservationImage.js", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/services/api.js", import.meta.url), "utf8");
const backend = readFileSync(new URL("../../api.py", import.meta.url), "utf8");

test("Country map observation panel loads submitted media through the protected contract", () => {
  assert.match(panel, /useObservationImage\(observationId, imageUrl\)/);
  assert.match(panel, /observationRecord\.id \|\| observation\.id/);
  assert.match(api, /\/observations\/\$\{id\}\/image/);
  assert.match(api, /startsWith\("image\/"\)/);
});

test("Monitoring Map and Country Review Queue share protected blob loading and cleanup", () => {
  assert.match(review, /useObservationImage\(observationId, url\)/);
  assert.match(review, /<LargeImage observationId=\{record\.id\}/);
  assert.match(hook, /getJurisdictionObservationImage\(observationId\)/);
  assert.match(hook, /URL\.revokeObjectURL\(objectUrl\)/);
  assert.match(hook, /requestKey.*observationId/);
});

test("submitted media remains authenticated, jurisdiction-scoped, and keeps its missing fallback", () => {
  assert.match(backend, /@app\.get\("\/observations\/\{observation_id\}\/image"\)/);
  assert.match(backend, /require_authenticated_user/);
  assert.match(backend, /require_roles\(db,current_user,observation\.jurisdiction_id,\{"VIEWER","REVIEWER","MANAGER"\}\)/);
  assert.match(panel, /Image unavailable/);
  assert.match(panel, /The submitted image could not be loaded\./);
});
