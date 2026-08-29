import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const system=readFileSync(new URL("../src/pages/AdminSystemStatusPage.jsx",import.meta.url),"utf8");
const app=readFileSync(new URL("../src/App.jsx",import.meta.url),"utf8");
const api=readFileSync(new URL("../src/services/api.js",import.meta.url),"utf8");

test("system status remains platform-admin guarded and exposes conservative automation state",()=>{
  assert.match(app,/\/admin\/system.*access="admin"/);
  assert.match(system,/Global automatic evaluation gate/);
  assert.match(system,/No scientific automation is enabled here implicitly/);
});

test("frontend API origin is deployment configurable and admin backup is controlled",()=>{
  assert.match(api,/VITE_API_BASE_URL/);
  assert.match(api,/\/admin\/system\/backups/);
});
