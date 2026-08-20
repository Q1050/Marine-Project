import assert from "node:assert/strict";
import test from "node:test";

import { adjustedLocation, confirmedLocation, deviceLocationProposal } from "../src/utils/sightingLocation.js";

test("device proposal retains accuracy only when accepted unchanged", () => {
  const proposal = deviceLocationProposal({ coords: { latitude: 18, longitude: -77, accuracy: 14 }, timestamp: Date.parse("2026-08-17T12:00:00Z") });
  const confirmed = confirmedLocation(proposal, { status: "RESOLVED" });
  assert.equal(confirmed.source, "DEVICE_GEOLOCATION");
  assert.equal(confirmed.accuracy, 14);
  assert.equal(confirmed.confirmed, true);
});

test("map adjustment clears device provenance and invalidates confirmation", () => {
  const moved = adjustedLocation(18.1, -77.1, "MAP_SELECTED");
  assert.equal(moved.source, "MAP_SELECTED");
  assert.equal(moved.accuracy, null);
  assert.equal(moved.capturedAt, null);
  assert.equal(moved.confirmed, false);
  assert.equal(moved.resolution, null);
});

test("typed coordinates are manual and unconfirmed", () => {
  const manual = adjustedLocation("18.2", "-77.2", "MANUAL");
  assert.equal(manual.source, "MANUAL");
  assert.equal(manual.confirmed, false);
});
