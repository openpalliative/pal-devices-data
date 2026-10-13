import { test } from "node:test";
import assert from "node:assert/strict";
import { ruDate } from "../../opsite/ui/js/format.js";

test("платформа подключена", () => {
  assert.equal(ruDate("2026-10-11"), "11.10.2026");
});
