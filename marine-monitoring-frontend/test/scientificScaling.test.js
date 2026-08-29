import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const page=readFileSync(new URL("../src/pages/AdminScientificReadinessPage.jsx",import.meta.url),"utf8");
const api=readFileSync(new URL("../src/services/api.js",import.meta.url),"utf8");
const visual=readFileSync(new URL("../src/components/admin/VisualCorpusPanel.jsx",import.meta.url),"utf8");
test("scientific scaling dashboard exposes nine categorical dimensions and filters",()=>{
 assert.match(page,/Readiness matrix/);assert.match(page,/Work queue/);assert.match(page,/Jurisdiction inventory/);
 for(const dimension of ["taxonomy","occurrence","ecology","public_directory","imagery","identification","environmental","suitability","early_warning"])assert.match(page,new RegExp(dimension));
 assert.match(page,/Taxonomic group/);assert.match(page,/Readiness state/);assert.match(page,/Search/);assert.doesNotMatch(page,/overallReadinessPercent/);
});
test("scientific scaling calls are admin-authenticated read endpoints",()=>{
 for(const path of ["scientific-scaling/summary","scientific-scaling/inventory","scientific-scaling/matrix","scientific-scaling/work-queue"])assert.match(api,new RegExp(path));
 assert.match(api,/getScientificScalingMatrix[^\n]+adminRequest/);
});
test("dashboard preserves the scientific interpretation firewall",()=>{
 assert.match(page,/Regional identification support does not establish jurisdiction presence/);
 assert.match(page,/Occurrence evidence does not establish ecological status/);
 assert.match(page,/does not indicate an anomaly/);
});
test("visual corpus workspace is admin-governed and scientifically bounded",()=>{
 assert.match(page,/Visual corpus/);assert.match(visual,/Identification media does not establish jurisdiction presence/);
 assert.match(visual,/reviewIdentificationMediaAsset/);assert.match(api,/\/admin\/identification-corpus\/assets/);
});
