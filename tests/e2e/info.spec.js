import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect } from "../../opsite/tests/fixtures.js";
import { dataset } from "./data.js";

const devices = dataset("devices-398n").items;
const diff = dataset("devices-348n-diff").items;
const acts = JSON.parse(readFileSync(join(process.cwd(), "vendor/pal-norms/v1/acts.json"), "utf8")).items;
const norm = (t) => String(t || "").toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

test.describe("что изменилось", () => {
  test("числа сходятся с данными", async ({ page }) => {
    const old = diff.filter((x) => x.status === "kept" || x.status === "removed");
    const checked = old.filter((x) => x.verified);
    const kept = checked.filter((x) => x.status === "kept").length;
    const removed = checked.filter((x) => x.status === "removed").length;
    const added = devices.filter((d) => d.in_348n === "no").length;
    await page.goto("changes/");
    const stats = await page.locator(".dv-stats__n").allTextContents();
    expect(stats.map(Number)).toEqual([kept + removed, devices.length, kept, added, removed]);
    await expect(page.locator("#added ~ ul li, section:has(#added) li")).toHaveCount(added);
    await expect(page.locator("section:has(#gone) li[id^='c-']")).toHaveCount(removed);
    if (checked.length === old.length) {
      await expect(page.locator("main")).not.toContainText("сверен не полностью");
      await expect(page.locator(".dv-checked")).toContainText(`${old.length} из ${old.length}`);
    }
  });

  test("код со сменённым названием в «Новое» с пометкой", async ({ page }) => {
    const d = devices.find((x) => x.in_348n === "no" && x.nkmi_name_now && norm(x.nkmi_name_now) !== norm(x.nkmi_name));
    test.skip(!d, "нет такого кода");
    await page.goto("changes/");
    const item = page.locator("section:has(#added) li", { hasText: d.code });
    await expect(item.locator(".dv-mark")).toContainText("сменил название");
  });
});

test.describe("данные и источники", () => {
  test("неразобранные документы только из снимка норм", async ({ page }) => {
    await page.goto("data/");
    const pending = page.locator("h3:has-text('Документы, которые мы ещё не разобрали') + p + ul li");
    const titles = await pending.allTextContents();
    for (const a of acts.filter((x) => x.verified)) {
      for (const t of titles) expect(t).not.toContain(a.short_title);
    }
    expect(titles.join(" ")).not.toContain("охраны здоровья");
  });

  test("ссылки на issues только с шаблоном и предупреждением", async ({ page }) => {
    for (const path of ["data/", "names/"]) {
      await page.goto(path);
      const hrefs = await page.locator("a[href*='/issues/new']").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
      expect(hrefs.length).toBeGreaterThan(0);
      for (const h of hrefs) expect(h).toMatch(/\/issues\/new\?template=[a-z-]+\.yml$/);
    }
    await page.goto("data/");
    await expect(page.locator(".dv-privacy")).toContainText("Не пишите имя, диагноз и регион");
    await expect(page.getByRole("link", { name: "Сообщить об ошибке" })).toHaveAttribute("href", /template=data-error\.yml$/);
  });
});

test.describe("указатель названий", () => {
  test("отдельная страница, главная без указателя @nojs", async ({ page }) => {
    await page.goto("names/");
    await expect(page.locator("h1")).toHaveText("Названия по алфавиту");
    expect(await page.locator(".dv-az__list > li[id^='a-']").count()).toBeGreaterThan(20);
    await page.goto("");
    await expect(page.locator(".dv-az")).toHaveCount(0);
    for (const href of await page.locator(".dv-chip").evaluateAll((a) => a.map((x) => x.getAttribute("href")))) {
      expect(href).toMatch(/^names\/(#a-[\w-]+)?$/);
    }
  });
});

test.describe("через кого получают", () => {
  test("цитаты видны без скриптов, основания не дублируются @nojs", async ({ page }) => {
    await page.goto("channels/");
    for (const id of ["q-208n-p25", "q-208n-p26", "q-398n-p1", "q-398n-fn2"]) {
      await expect(page.locator(`#${id} blockquote`)).toBeVisible();
    }
    for (const card of await page.locator(".dv-path").all()) {
      const links = await card.locator("a.op-norm, a.dv-norm").evaluateAll((a) => a.map((x) => x.getAttribute("href")));
      expect(new Set(links).size).toBe(links.length);
    }
  });
});

test.describe("404", () => {
  test("несуществующий адрес ведёт к поиску", async ({ page }) => {
    const res = await page.goto("devices/000000/");
    expect(res.status()).toBe(404);
    await expect(page.locator("h1")).toHaveText("Такой страницы нет");
    await expect(page.getByRole("link", { name: /Кто выдаёт изделия/ }).last()).toHaveAttribute("href", "/pal-devices-data/");
  });
});
