import test from "node:test";
import assert from "node:assert/strict";
import {
  applyOnboardingBatch,
  applyOnboardingPreparation,
  approveOnboardingPreparation,
  getAdminRegions,
  getOnboardingPreparation,
  getRegionOnboardingInventory,
  prepareRegionJurisdictions,
  getAdminRegionTaxa,
  getAdminJurisdictionTaxonReadiness,
  getAdminTaxa,
  prepareAdminTaxonomy,
  approveAdminTaxonomy,
  applyAdminTaxonomy,
  getAdminTaxonomyHistory,
  acquireCommonsTaxonomyEvidence,
  resolveIdentificationMediaTaxonomy,
} from "../src/services/api.js";
import {
  canApplyJurisdiction,
  canPrepareJurisdiction,
  scientificStateDescription,
  selectableJurisdictions,
} from "../src/utils/adminOnboarding.js";
import { hasProtectedAccess } from "../src/auth/access.js";

globalThis.sessionStorage = { getItem: () => "admin-token" };

test("admin console access requires a platform administrator", () => {
  assert.equal(hasProtectedAccess(null, "admin"), false);
  assert.equal(
    hasProtectedAccess({ is_platform_admin: false }, "admin", ["MANAGER"]),
    false,
  );
  assert.equal(hasProtectedAccess({ is_platform_admin: true }, "admin"), true);
});

function mockResponse(payload = {}, ok = true) {
  globalThis.fetch = async (url, options = {}) => ({
    ok,
    json: async () => payload,
    url,
    options,
  });
}

test("selection excludes blocked and ambiguous inventory entries", () => {
  const rows = [
    { canonical_identifier: "AG", status: "READY" },
    { canonical_identifier: "LC", status: "APPROVED", preparation_id: 2 },
    { canonical_identifier: "CU", status: "BLOCKED" },
    { canonical_identifier: "AW", status: "REQUIRES_REVIEW" },
  ];
  assert.equal(canPrepareJurisdiction(rows[0]), true);
  assert.equal(canApplyJurisdiction(rows[1]), true);
  assert.deepEqual(
    selectableJurisdictions(rows).map((row) => row.canonical_identifier),
    ["AG", "LC"],
  );
});

test("scientific empty state remains distinct from geographic onboarding", () => {
  assert.equal(
    scientificStateDescription("SCIENTIFICALLY_EMPTY"),
    "No species science inherited",
  );
});

test("region and inventory calls use centralized authenticated API client", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ results: [] }) };
  };
  await getAdminRegions();
  await getRegionOnboardingInventory(1);
  assert.match(calls[0].url, /\/admin\/regions$/);
  assert.match(
    calls[1].url,
    /\/admin\/regions\/1\/jurisdiction-onboarding\/prepare\?dry_run=true$/,
  );
  assert.equal(calls[1].options.headers.Authorization, "Bearer admin-token");
});

test("selected preparation is passed as governed canonical identifiers", async () => {
  let call;
  globalThis.fetch = async (url, options = {}) => {
    call = { url, options };
    return { ok: true, json: async () => ({ results: [] }) };
  };
  await prepareRegionJurisdictions(1, ["AG", "LC"]);
  assert.match(call.url, /canonical_identifiers=AG%2CLC/);
  assert.equal(call.options.method, "POST");
});

test("review, approve, single apply, and batch apply target controlled endpoints", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({}) };
  };
  await getOnboardingPreparation(7);
  await approveOnboardingPreparation(7, "fingerprint", "review-42");
  await applyOnboardingPreparation(7);
  await applyOnboardingBatch([7, 8]);
  assert.match(calls[0].url, /jurisdiction-onboarding\/7$/);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    expected_manifest_fingerprint: "fingerprint",
    approval_reference: "review-42",
  });
  assert.match(calls[2].url, /jurisdiction-onboarding\/7\/apply$/);
  assert.deepEqual(JSON.parse(calls[3].options.body), {
    preparation_ids: [7, 8],
  });
});

test("backend validation and conflict reasons are surfaced", async () => {
  mockResponse({ detail: "Approval is stale" }, false);
  await assert.rejects(
    () => approveOnboardingPreparation(7, "old", "review"),
    /Approval is stale/,
  );
});

test("taxonomy and jurisdiction readiness use read-only admin endpoints", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ taxa: [] }) };
  };
  await getAdminRegionTaxa(1);
  await getAdminJurisdictionTaxonReadiness(2, 3);
  assert.match(calls[0].url, /\/admin\/regions\/1\/taxa$/);
  assert.match(calls[1].url, /\/admin\/jurisdictions\/2\/taxa\/3\/readiness$/);
  assert.equal(calls[0].options.method, undefined);
  assert.equal(calls[1].options.method, undefined);
});

test("controlled taxonomy prepare, approve, apply, and history calls are separated", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({}) };
  };
  await getAdminTaxa();
  await prepareAdminTaxonomy(1, 1);
  await approveAdminTaxonomy(4, "fp", "review");
  await applyAdminTaxonomy(4);
  await getAdminTaxonomyHistory(1);
  assert.match(calls[0].url, /\/admin\/taxa$/);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    taxon_id: 1,
    region_id: 1,
  });
  assert.match(calls[2].url, /\/approve$/);
  assert.match(calls[3].url, /\/apply$/);
  assert.match(calls[4].url, /\/taxonomy-history$/);
});

test("media taxonomy evidence acquisition stays separate from human resolution", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({}) };
  };
  await acquireCommonsTaxonomyEvidence(17);
  await resolveIdentificationMediaTaxonomy(
    17,
    "AMBIGUOUS",
    "Conflicting provider evidence",
    [3, 4],
  );
  assert.match(calls[0].url, /assets\/17\/taxonomy-evidence\/commons$/);
  assert.equal(calls[0].options.method, "POST");
  assert.match(calls[1].url, /assets\/17\/taxonomy-resolution$/);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    resolution_state: "AMBIGUOUS",
    reason: "Conflicting provider evidence",
    evidence_ids: [3, 4],
  });
  assert.equal(calls[1].options.headers.Authorization, "Bearer admin-token");
});
