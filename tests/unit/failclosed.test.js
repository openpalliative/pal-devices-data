import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const repo = new URL("../../", import.meta.url).pathname;
const python = join(repo, ".venv", "bin", "python");

function buildWith(acts) {
  const root = mkdtempSync(join(tmpdir(), "dv-failclosed-"));
  for (const p of ["site.yaml", "site_hooks.py", "templates", "content", "assets", "lib", "pipeline", "data", "tests/fixtures"]) {
    if (existsSync(join(repo, p))) cpSync(join(repo, p), join(root, p), { recursive: true });
  }
  const v = join(root, "vendor", "pal-norms", "v1");
  mkdirSync(v, { recursive: true });
  writeFileSync(join(v, "acts.json"), JSON.stringify(acts));
  writeFileSync(join(v, "acts.schema.json"), JSON.stringify({ type: "object" }));
  const r = spawnSync(python, ["-m", "opsite", "--root", root, "build"], {
    cwd: repo, env: { ...process.env, OP_FIXTURES: "1" }, encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr || r.stdout);
  return root;
}

const repealed = JSON.parse(readFileSync(new URL("./fixtures/acts-398n-repealed.json", import.meta.url), "utf8"));

test("норма канала не действует: канал закрыт на карточке", { skip: !existsSync(python) }, () => {
  const root = buildWith(repealed);
  try {
    const mo = readFileSync(join(root, "_site", "devices", "303260", "index.html"), "utf8");
    assert.match(mo, /Основание изменилось, проверяется/);
    assert.doesNotMatch(mo, /class="dv-who__answer"/);
    const both = readFileSync(join(root, "_site", "devices", "280360", "index.html"), "utf8");
    assert.match(both, /Основание изменилось, проверяется/);
    assert.doesNotMatch(both, /class="dv-branches"/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("норма действует: канал виден, ссылка ведёт в «Нормы и сроки»", { skip: !existsSync(python) }, () => {
  const ok = structuredClone(repealed);
  ok.items[0].status = "in_force";
  const root = buildWith(ok);
  try {
    const mo = readFileSync(join(root, "_site", "devices", "303260", "index.html"), "utf8");
    assert.doesNotMatch(mo, /Основание изменилось/);
    assert.match(mo, /class="dv-who__answer"/);
    assert.match(mo, /href="\/pal-norms\/acts\/398n\/"/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
