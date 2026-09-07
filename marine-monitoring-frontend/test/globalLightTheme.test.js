import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");

test("the explicitly light application does not partially follow OS dark preference", () => {
  assert.match(styles, /color-scheme:\s*light;/);
  assert.match(styles, /--text-h:\s*#08060d;/);
  assert.match(styles, /--text:\s*#142932;/);
  assert.doesNotMatch(styles, /@media\s*\(prefers-color-scheme:\s*dark\)/);
  assert.doesNotMatch(styles, /--text-h:\s*#f3f4f6/);
});
