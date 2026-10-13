import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const repo = new URL("../../", import.meta.url).pathname;
const python = join(repo, ".venv", "bin", "python");
const EO = "0001201812250098";

function buildWithQuote(quote) {
  const root = mkdtempSync(join(tmpdir(), "dv-nutq-"));
  for (const p of ["site.yaml", "site_hooks.py", "templates", "content", "assets", "lib", "pipeline", "data", "vendor", "tests/fixtures"]) {
    if (existsSync(join(repo, p))) cpSync(join(repo, p), join(root, p), { recursive: true });
  }
  const v = join(root, "vendor", "pal-norms", "v1");
  const acts = JSON.parse(readFileSync(join(v, "acts.json"), "utf8"));
  const base = acts.items.find((a) => a.id === "323-fz");
  acts.items.push({ ...base, id: "test-amending-law", eoNumber: EO, url: `http://publication.pravo.gov.ru/document/${EO}` });
  writeFileSync(join(v, "acts.json"), JSON.stringify(acts));
  const quotes = { ...acts, dataset: "quotes", items: [quote], counts: { items: 1, unverified: quote.verified ? 0 : 1, excluded: 0 } };
  writeFileSync(join(v, "quotes.json"), JSON.stringify(quotes));
  writeFileSync(join(v, "quotes.schema.json"), JSON.stringify({ type: "object" }));
  const r = spawnSync(python, ["-m", "opsite", "--root", root, "build"], { cwd: repo, encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr || r.stdout);
  return root;
}

const quote = {
  id: "323fz-37-15", verified: true, verified_at: "2026-10-11", source_ref: "pravo-test", act_id: "test-amending-law",
  point: "часть 15 статьи 37", page: 8, text: "Тестовый текст для проверки сборки: решение принимает врачебной комиссии.",
};

test("цитата ч. 15 ст. 37 из снимка норм: текст, номер публикации, страница, шаги", { skip: !existsSync(python) }, () => {
  const root = buildWithQuote(quote);
  try {
    const html = readFileSync(join(root, "_site", "nutrition", "index.html"), "utf8");
    const section = html.slice(html.indexOf('id="notlisted"'), html.indexOf('id="adult"'));
    assert.match(section, /id="q-323fz-37-15"/);
    assert.match(section, /Тестовый текст для проверки сборки/);
    assert.match(section, new RegExp(`Номер публикации ${EO}`));
    assert.match(section, /стр\. 8 публикации/);
    assert.match(section, /Черновик\./);
    assert.match(section, /Кто решает\./);
    assert.match(section, /На что сослаться\./);
    assert.doesNotMatch(section, /не сверили/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("цитата не сверена: статус «Не проверено», без шагов", { skip: !existsSync(python) }, () => {
  const root = buildWithQuote({ ...quote, verified: false });
  try {
    const html = readFileSync(join(root, "_site", "nutrition", "index.html"), "utf8");
    const section = html.slice(html.indexOf('id="notlisted"'), html.indexOf('id="adult"'));
    assert.match(section, /Не проверено/);
    assert.doesNotMatch(section, /Кто решает\./);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
