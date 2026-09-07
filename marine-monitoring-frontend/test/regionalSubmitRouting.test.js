import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { routeContext, submissionRouteForScope } from "../src/config/navigation.js";

const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const shell = readFileSync(new URL("../src/components/AppShell.jsx", import.meta.url), "utf8");

for (const sourcePath of [
  "/region/caribbean",
  "/region/caribbean/species",
  "/region/caribbean/observations",
]) {
  test(`${sourcePath} submits through the regional shell`, () => {
    const source = routeContext(sourcePath);
    const destination = submissionRouteForScope(source.scope, source.activeRegion, source.activeJurisdiction);
    assert.equal(destination, "/region/caribbean/submit");
    assert.equal(routeContext(destination).scope, "regional");
  });
}

test("direct public submission remains in the public shell", () => {
  assert.equal(submissionRouteForScope("public", "caribbean", null), "/submit");
  assert.equal(routeContext("/submit").scope, "public");
});

test("regional and public routes render the same shared SubmitPage", () => {
  assert.match(app, /path="\/region\/caribbean\/submit" element={<SubmitPage onObservationCreated={refreshMap} \/>}/);
  assert.match(app, /path="\/submit" element={<SubmitPage onObservationCreated={refreshMap} \/>}/);
  assert.match(shell, /const submitUrl = submissionRouteForScope\(scope, activeRegion, activeJurisdiction\)/);
});

test("judge-facing shell removes inert settings and help placeholders", () => {
  assert.doesNotMatch(shell, />[^<]*Settings[^<]*<\/div>/);
  assert.doesNotMatch(shell, />[^<]*Help center[^<]*<\/div>/);
  assert.match(shell, /＋ Submit sighting/);
});
