import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { alternativeCandidates, canSubmitObservation, similarityLabel, validateObservationImage } from "../src/utils/submissionPresentation.js";

const page = readFileSync(new URL("../src/pages/SubmitPage.jsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/App.css", import.meta.url), "utf8");

test("empty workflow requires a real image and confirmed resolved location", () => {
  assert.equal(canSubmitObservation({ image: null, latitude: "", longitude: "", locationConfirmed: false, resolution: null, submitting: false }), false);
  assert.match(page, /Choose or capture a marine image/);
  assert.match(page, /Preliminary species suggestion/);
});

test("selected image supports preview, replace, remove, and accepted upload constraints", () => {
  assert.equal(validateObservationImage({ type: "image/jpeg", size: 1024 }), null);
  assert.match(validateObservationImage({ type: "application/pdf", size: 1024 }), /JPEG, PNG, or WEBP/);
  assert.match(validateObservationImage({ type: "image/png", size: 11 * 1024 * 1024 }), /10 MB/);
  assert.match(page, /Selected marine observation/);
  assert.match(page, /Replace image/);
  assert.match(page, /Remove/);
});

test("location selection and manual-map behavior remain wired", () => {
  assert.match(page, /useCurrentLocation/);
  assert.match(page, /SightingLocationPicker/);
  assert.match(page, /selectOnMap/);
  assert.match(page, /Confirm location/);
  assert.match(page, /resolution\?\.status === "RESOLVED"/);
});

test("CTA state prevents missing-input and duplicate submissions", () => {
  const complete = { image: {}, latitude: "18", longitude: "-77", locationConfirmed: true, resolution: { status: "RESOLVED" }, submitting: false };
  assert.equal(canSubmitObservation(complete), true);
  assert.equal(canSubmitObservation({ ...complete, submitting: true }), false);
  assert.match(page, /if \(submitting\) return/);
  assert.match(page, /Analyzing and submitting/);
});

test("AI output uses raw similarity semantics and real alternatives", () => {
  assert.equal(similarityLabel(0.963185), "0.963");
  assert.equal(similarityLabel(null), "Not available");
  const alternatives = alternativeCandidates({ species: "Taxon A", candidates: [{ scientific_name: "Taxon A", score: 0.9 }, { scientific_name: "Taxon B", score: 0.7 }] });
  assert.deepEqual(alternatives, [{ scientific_name: "Taxon B", score: 0.7 }]);
  assert.match(page, />Similarity</);
  assert.doesNotMatch(page, /confidence|score\s*\*\s*100|% confidence/i);
});

test("result preserves AI warning, alternatives, review pathway, and submission route", () => {
  assert.match(page, /AI Suggestion — Not Authoritative/);
  assert.match(page, /Alternative candidates/);
  assert.match(page, /Submitted observation/);
  assert.match(page, /Expert review/);
  assert.match(page, /Scientific assessment where eligible/);
  assert.match(page, /reporter\/status/);
});

test("submission success opens a mobile sheet and dismissal cannot resubmit", () => {
  assert.match(page, /setResultOpen\(true\)/);
  assert.match(page, /role="dialog"/);
  assert.match(page, /aria-modal="true"/);
  assert.match(page, /setResultOpen\(false\)/);
  assert.match(page, /submission-sheet-done/);
  assert.doesNotMatch(page, /submission-sheet-(done|close)[^>]*type="submit"/);
  assert.match(css, /@media \(max-width:900px\)/);
  assert.match(css, /max-height:calc\(100dvh - 42px\)/);
});

test("submission failure is visible and Stitch scientific mock values are absent", () => {
  assert.match(page, /role="alert"/);
  assert.match(page, /backend may be unavailable/);
  assert.doesNotMatch(page, /Red Lionfish|Montego Bay|0\.950|142 records|GPS Lock Active|Known Established Invasive/);
});
