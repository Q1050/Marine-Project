import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

test("basemap configuration uses one environment key and a safe fallback", () => {
  const config = read("../src/config/basemap.js");
  assert.match(config, /VITE_CARTO_API_KEY/);
  assert.match(config, /tile\.openstreetmap\.org/);
  assert.doesNotMatch(config, /eyJ[a-zA-Z0-9_-]{20,}/);

  for (const source of [
    "../src/components/MarineMap.jsx",
    "../src/components/SightingLocationPicker.jsx",
    "../src/pages/RegionalMapPage.jsx",
    "../src/pages/PublicDirectoryPages.jsx",
  ]) {
    assert.match(read(source), /BASEMAP/);
  }
});

test("regional entry point states workflow and jurisdiction science boundary", () => {
  const page = read("../src/pages/RegionalMapPage.jsx");
  assert.match(page, /Report → Identify → Verify → Govern → Map → Assess → Review/);
  assert.match(page, /there is no Caribbean-wide prediction model/);
});

test("demo environment is unmistakably labeled", () => {
  const shell = read("../src/components/AppShell.jsx");
  assert.match(shell, /VITE_APP_ENV === "DEMO"/);
  assert.match(shell, /Demonstration data and workflows/);
  assert.match(shell, /not operational scientific evidence/);
});

test("empty invasive directory describes absence of governed assertion", () => {
  const page = read("../src/pages/PublicDirectoryPages.jsx");
  assert.match(page, /No governed invasive-species assertions/);
  assert.match(page, /until source review is complete/);
});

test("a persisted taxonomy manifest can be reopened after refresh", () => {
  const panel = read("../src/components/admin/RegionalTaxonManifestPanel.jsx");
  assert.match(panel, /Existing governed run ID/);
  assert.match(panel, /Load prepared run/);
  assert.match(panel, /getRegionalTaxonManifest\(Number\(existingRunId\)\)/);
});

test("submission result does not present compatibility ecology as governed truth", () => {
  const page = read("../src/pages/SubmitPage.jsx");
  assert.match(page, /Submitted for expert review/);
  assert.match(page, /Governed ecological status/);
  assert.match(page, /Not established by this submission/);
  assert.match(page, /Expert verification and governed ecological-status review are separate decisions/);
  assert.doesNotMatch(page, /<strong>\{result\.ecological_status\}<\/strong>/);
});
