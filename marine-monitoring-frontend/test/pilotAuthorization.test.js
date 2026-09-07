import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { hasProtectedAccess } from "../src/auth/access.js";
import { navigationSectionLabel, showPlatformAdminReturn } from "../src/config/shellPresentation.js";

const reviewer={is_platform_admin:false,operational_review:{enabled:true}};
const publicUser={is_platform_admin:false,operational_review:{enabled:false}};
const admin={is_platform_admin:true,operational_review:{enabled:true}};
const scientist={is_platform_admin:false,operational_review:{enabled:false},scientific_review:{enabled:true}};

test("pilot route authorization separates public, reviewer, and platform admin",()=>{
  assert.equal(hasProtectedAccess(null,"observation-review"),false);
  assert.equal(hasProtectedAccess(publicUser,"observation-review"),false);
  assert.equal(hasProtectedAccess(reviewer,"observation-review"),true);
  assert.equal(hasProtectedAccess(reviewer,"admin"),false);
  assert.equal(hasProtectedAccess(admin,"admin"),true);
  assert.equal(hasProtectedAccess(scientist,"scientific-review"),true);
  assert.equal(hasProtectedAccess(reviewer,"scientific-review"),false);
  assert.equal(hasProtectedAccess(scientist,"observation-review"),false);
});

test("critical reviewer controls use server-authorized contracts",()=>{
  const source=readFileSync(new URL("../src/pages/AdminObservationOperationsPage.jsx",import.meta.url),"utf8");
  assert.match(source,/getEligibleObservationReviewers/);
  assert.match(source,/reporter_response_url/);
  assert.match(source,/Copy link/i);
  assert.match(source,/closeAdminObservation/);
  assert.match(source,/Reopen case/);
  assert.match(source,/No cases match these filters/);
  assert.match(source,/role="alert"/);
});

test("routes expose reviewer home but retain admin guard for reviewer management",()=>{
  const app=readFileSync(new URL("../src/App.jsx",import.meta.url),"utf8");
  assert.match(app,/path="\/reviewer"[^\n]+access="observation-review"/);
  assert.match(app,/path="\/admin\/reviewers"[^\n]+access="admin"/);
  assert.match(app,/path="\/scientific-review\/early-warning"[^\n]+access="scientific-review"/);
});

test("early-warning experience includes governed map and conservative language",()=>{
  const page=readFileSync(new URL("../src/pages/AdminEarlyWarningPage.jsx",import.meta.url),"utf8");
  const api=readFileSync(new URL("../src/services/api.js",import.meta.url),"utf8");
  assert.match(page,/MapContainer/);
  assert.match(page,/Governed baseline/);
  assert.match(page,/not an invasive declaration, emergency, or confirmed range expansion/);
  assert.match(api,/\/scientific-review\/early-warning/);
  assert.match(api,/\/admin\/early-warning\/events\/summary/);
});

test("13D closure exposes governed administration, layers, and observation context",()=>{
  const page=readFileSync(new URL("../src/pages/AdminEarlyWarningPage.jsx",import.meta.url),"utf8");
  const operations=readFileSync(new URL("../src/pages/AdminObservationOperationsPage.jsx",import.meta.url),"utf8");
  assert.match(page,/Scientific Early-Warning Reviewers/);
  assert.match(page,/Configuration history/);
  assert.match(page,/Environmental suitability/);
  assert.match(page,/No scientific assessments are awaiting review/);
  assert.match(operations,/Early-warning \/ scientific context/);
  assert.match(operations,/Eligibility is not itself an anomaly/);
});

test("all Early Warning tabs tolerate empty API collections and expose truthful empty states",()=>{
  const page=readFileSync(new URL("../src/pages/AdminEarlyWarningPage.jsx",import.meta.url),"utf8");
  for(const tab of ["Assessment review","Scientific reviewers","Configurations","Controlled events"]){
    assert.match(page,new RegExp(tab));
  }
  assert.match(page,/arrayFrom\(u,"users","items"\)/);
  assert.match(page,/No scientific assessments are awaiting review/);
  assert.match(page,/No scientific reviewer grants are configured/);
  assert.match(page,/No early-warning configurations are currently active/);
  assert.match(page,/No controlled scientific events have been recorded/);
});

test("Country shell identifies agency context and only platform admins receive the admin return",()=>{
  assert.equal(navigationSectionLabel("country","Jamaica"),"Jamaica agency workspace");
  assert.equal(showPlatformAdminReturn("country",admin),true);
  assert.equal(showPlatformAdminReturn("country",reviewer),false);
  assert.equal(showPlatformAdminReturn("country",publicUser),false);
  assert.equal(showPlatformAdminReturn("regional",admin),false);
});

test("agency roles do not gain Admin scientific-readiness or taxonomy routes",()=>{
  const app=readFileSync(new URL("../src/App.jsx",import.meta.url),"utf8");
  assert.match(app,/path="\/admin\/scientific-readiness"[^\n]+access="admin"/);
  assert.match(app,/path="\/admin\/taxonomy"[^\n]+access="admin"/);
  assert.equal(hasProtectedAccess(reviewer,"admin"),false);
});

test("agency science navigation uses Country-scoped read-only routes",()=>{
  const navigation=readFileSync(new URL("../src/config/navigation.js",import.meta.url),"utf8");
  const app=readFileSync(new URL("../src/App.jsx",import.meta.url),"utf8");
  const page=readFileSync(new URL("../src/pages/AgencySciencePage.jsx",import.meta.url),"utf8");
  assert.match(navigation,/id: "scientific-readiness", label: "Scientific readiness"/);
  assert.match(navigation,/id: "early-warning", label: "Early warning"/);
  assert.match(app,/jurisdictionSlug\/scientific-readiness[^\n]+access="investigations"/);
  assert.match(app,/jurisdictionSlug\/early-warning[^\n]+access="investigations"/);
  assert.match(page,/getJurisdictionSpeciesIntelligence/);
  assert.match(page,/Read-only jurisdiction/);
  assert.match(page,/Automatic scientific evaluation is disabled/);
  assert.doesNotMatch(page,/createEarlyWarning|reviewEarlyWarning|transitionEarlyWarning|grantScientific/);
});
