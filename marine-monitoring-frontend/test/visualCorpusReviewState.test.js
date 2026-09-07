import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  filterMediaAssets,
  nextSelectionAfterDisposition,
  nextTaxonomySelectionAfterResolution,
  normalizeResolutionReason,
  reviewNavigationAssets,
  TAXONOMY_RESOLUTION_ACTIONS,
  taxonomyNavigationAssets,
} from "../src/components/admin/visualCorpusReviewState.js";

const asset = (id, review_state) => ({ id, review_state });
const taxonomyAsset = (id, resolved = false) => ({
  id,
  review_state: "TAXONOMY_REVIEW_REQUIRED",
  taxonomy_history: {
    evidence: [{ id: id * 10, provider: "WIKIMEDIA_COMMONS" }],
    resolutions: resolved
      ? [{ id: id * 100, resolution_state: "AMBIGUOUS" }]
      : [],
  },
});

test("focused taxonomy review renders evidence provenance and governed controls", () => {
  const source = readFileSync(
    new URL("../src/components/admin/VisualCorpusPanel.jsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /Taxonomy review \(\$\{taxonomyReviewCount\}\)/);
  assert.match(source, /Taxonomy evidence/);
  assert.match(source, /Evidence source/);
  assert.match(source, /Provider page/);
  assert.match(source, /taxonomy_history\?\.resolutions/);
  assert.match(source, /TAXONOMY_RESOLUTION_ACTIONS\.map/);
});

test("taxonomy review is independent when ordinary pending is empty", () => {
  const assets = [1, 2, 3, 4, 5, 6, 7].map((id) => taxonomyAsset(id));
  assert.equal(filterMediaAssets(assets, "REVIEWABLE").length, 0);
  assert.equal(filterMediaAssets(assets, "TAXONOMY_REVIEW").length, 7);
  assert.deepEqual(
    taxonomyNavigationAssets(assets).map((item) => item.id),
    [1, 2, 3, 4, 5, 6, 7],
  );
  assert.equal(
    assets[0].taxonomy_history.evidence[0].provider,
    "WIKIMEDIA_COMMONS",
  );
});

test("taxonomy workflow exposes all governed actions and requires a reason", () => {
  assert.deepEqual(
    TAXONOMY_RESOLUTION_ACTIONS.map(([state]) => state),
    [
      "CONFIRMED_TARGET_TAXON",
      "DIFFERENT_TAXON",
      "AMBIGUOUS",
      "INSUFFICIENT_EVIDENCE",
    ],
  );
  assert.equal(normalizeResolutionReason("   "), "");
  assert.equal(normalizeResolutionReason(null), "");
  assert.equal(
    normalizeResolutionReason("  evidence checked  "),
    "evidence checked",
  );
});

test("taxonomy disposition advances and the last resolution closes", () => {
  const before = [taxonomyAsset(17), taxonomyAsset(19)];
  const afterFirst = [taxonomyAsset(17, true), taxonomyAsset(19)];
  assert.equal(
    nextTaxonomySelectionAfterResolution({
      reviewedId: 17,
      beforeAssets: before,
      afterAssets: afterFirst,
    }),
    19,
  );
  const afterLast = [taxonomyAsset(17, true), taxonomyAsset(19, true)];
  assert.equal(
    nextTaxonomySelectionAfterResolution({
      reviewedId: 19,
      beforeAssets: afterFirst,
      afterAssets: afterLast,
    }),
    null,
  );
  assert.equal(filterMediaAssets(afterLast, "TAXONOMY_REVIEW").length, 0);
  assert.equal(filterMediaAssets(afterLast, "ALL").length, 2);
});

test("authoritative refreshed resolution history controls taxonomy queue membership", () => {
  const staleClientAsset = taxonomyAsset(24);
  const refreshedAsset = taxonomyAsset(24, true);
  assert.equal(
    filterMediaAssets([staleClientAsset], "TAXONOMY_REVIEW").length,
    1,
  );
  assert.equal(
    filterMediaAssets([refreshedAsset], "TAXONOMY_REVIEW").length,
    0,
  );
});

test("open, approve, then continue with the next reviewable asset", () => {
  const before = [
    asset(1, "READY_FOR_REVIEW"),
    asset(2, "READY_FOR_REVIEW"),
    asset(3, "EXCLUDED"),
  ];
  const after = [
    asset(1, "APPROVED"),
    asset(2, "READY_FOR_REVIEW"),
    asset(3, "EXCLUDED"),
  ];
  const selectedId = nextSelectionAfterDisposition({
    selectedId: 1,
    reviewedId: 1,
    beforeAssets: before,
    afterAssets: after,
  });
  assert.equal(selectedId, 2);
  assert.deepEqual(
    reviewNavigationAssets(after, selectedId).map((item) => item.id),
    [2],
  );
});

test("selected asset disappearing from a pending filter advances without stale selection", () => {
  const before = [asset(11, "READY_FOR_REVIEW"), asset(12, "REVIEW_REQUIRED")];
  const refreshed = [asset(12, "REVIEW_REQUIRED")];
  assert.deepEqual(
    filterMediaAssets(refreshed, "REVIEWABLE").map((item) => item.id),
    [12],
  );
  assert.equal(
    nextSelectionAfterDisposition({
      selectedId: 11,
      reviewedId: 11,
      beforeAssets: before,
      afterAssets: refreshed,
    }),
    12,
  );
});

test("last reviewable disposition closes the focused workspace", () => {
  const before = [asset(1, "READY_FOR_REVIEW"), asset(2, "APPROVED")];
  const after = [asset(1, "EXCLUDED"), asset(2, "APPROVED")];
  assert.equal(
    nextSelectionAfterDisposition({
      selectedId: 1,
      reviewedId: 1,
      beforeAssets: before,
      afterAssets: after,
    }),
    null,
  );
});

test("reviewing one asset does not disturb an unrelated open selection", () => {
  const before = [asset(1, "READY_FOR_REVIEW"), asset(2, "READY_FOR_REVIEW")];
  const after = [asset(1, "APPROVED"), asset(2, "READY_FOR_REVIEW")];
  assert.equal(
    nextSelectionAfterDisposition({
      selectedId: 2,
      reviewedId: 1,
      beforeAssets: before,
      afterAssets: after,
    }),
    2,
  );
});

test("approved and excluded assets remain inspectable but use inspection navigation", () => {
  const assets = [
    asset(1, "APPROVED"),
    asset(2, "EXCLUDED"),
    asset(3, "READY_FOR_REVIEW"),
  ];
  assert.deepEqual(
    filterMediaAssets(assets, "APPROVED").map((item) => item.id),
    [1],
  );
  assert.deepEqual(
    filterMediaAssets(assets, "EXCLUDED").map((item) => item.id),
    [2],
  );
  assert.deepEqual(
    reviewNavigationAssets(assets, 1).map((item) => item.id),
    [1, 2, 3],
  );
  assert.deepEqual(
    reviewNavigationAssets(assets, 3).map((item) => item.id),
    [3],
  );
});
