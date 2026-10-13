import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  test, expect, checkA11y, pdfPages, noHorizontalScroll, setSize, smallPlatformText, smallPlatformTargets,
  lightTextInPrint,
} from "./fixtures.js";

const root = process.cwd();
const pages = JSON.parse(readFileSync(join(root, "tests/e2e/pages.json"), "utf8"));
const siteYaml = readFileSync(join(root, "site.yaml"), "utf8");
const isHub = /^repo:\s*openpalliative\.github\.io\s*$/m.test(siteYaml);
const isPwa = /^pwa:\s*true\s*$/m.test(siteYaml);
const phone = { width: 360, height: 640 };

for (const p of pages) {
  test.describe(p.name, () => {
    test(`страница ${p.name} @nojs`, async ({ page }, info) => {
      const nojs = info.project.name === "nojs";
      if (nojs && !p.nojs) test.skip();
      const response = await page.goto(p.path);
      expect(response?.status()).toBeLessThan(400);
      await expect(page.locator("html")).toHaveAttribute("lang", p.lang || "ru");
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.locator("main")).not.toBeEmpty();
      if (!nojs) {
        await noHorizontalScroll(page);
        await checkA11y(page);
        await page.emulateMedia({ colorScheme: "dark" });
        await checkA11y(page);
      } else {
        const draft = page.locator(".op-draft__body").first();
        if (await draft.count()) await expect(draft).toBeVisible();
      }
      if (typeof p.print_pages === "number" && !nojs) {
        expect(await pdfPages(page)).toBe(p.print_pages);
      }
    });

    test(`телефон ${p.name}: шапка, шрифты, цели нажатия`, async ({ page }, info) => {
      test.skip(info.project.name !== "mobile");
      await page.setViewportSize(phone);
      await page.goto(p.path);
      const header = await page.locator(".op-header").boundingBox();
      expect(header.y + header.height, "низ шапки").toBeLessThanOrEqual(isHub ? 130 : 200);
      const draft = page.locator(".op-draft").first();
      if (await draft.count()) expect((await draft.boundingBox()).height, "свёрнутый черновик").toBeLessThanOrEqual(76);
      const now = page.locator(".op-now--compact").first();
      if (await now.count()) expect((await now.boundingBox()).height, "компактный блок номеров").toBeLessThanOrEqual(200);
      expect(await smallPlatformText(page, 16), "текст мельче 16px при A").toEqual([]);
      await page.setViewportSize({ width: 390, height: 844 });
      expect(await smallPlatformTargets(page), "цели нажатия ниже 44px").toEqual([]);
    });

    test(`телефон ${p.name}: размер A++`, async ({ page }, info) => {
      test.skip(info.project.name !== "mobile");
      await setSize(page, "xl");
      await page.setViewportSize(phone);
      await page.goto(p.path);
      await expect(page.locator("html")).toHaveAttribute("data-size", "xl");
      await noHorizontalScroll(page);
      expect(await smallPlatformText(page, 18), "текст мельче 18px при A++").toEqual([]);
      const now = page.locator(".op-header__now");
      const lines = await now.evaluate((a) => {
        const span = a.querySelector("span");
        const lh = parseFloat(getComputedStyle(span).lineHeight);
        return Math.round(span.getBoundingClientRect().height / lh);
      });
      expect(lines, "ссылка «прямо сейчас» в строках").toBeLessThanOrEqual(2);
      expect(parseFloat(await now.evaluate((a) => getComputedStyle(a).fontSize))).toBeGreaterThanOrEqual(20);
    });

    test(`формы ${p.name} не уходят запросом`, async ({ page }, info) => {
      test.skip(info.project.name !== "desktop");
      await page.goto(p.path);
      await page.waitForLoadState("load");
      const before = page.url().split("#")[0];
      const requests = [];
      page.on("request", (r) => {
        if (r.url().includes("?")) requests.push(r.url());
      });
      const submitted = await page.evaluate(() => {
        let n = 0;
        for (const form of document.querySelectorAll("form")) {
          if ((form.getAttribute("method") || "").toLowerCase() === "dialog") continue;
          form.requestSubmit();
          n += 1;
        }
        return n;
      });
      await page.waitForTimeout(submitted ? 300 : 0);
      expect(page.url().split("#")[0]).toBe(before);
      expect(requests).toEqual([]);
    });

    test(`печать ${p.name} из тёмной темы чёрным по белому`, async ({ page }, info) => {
      test.skip(info.project.name !== "desktop");
      await page.emulateMedia({ colorScheme: "dark", media: "print" });
      await page.goto(p.path);
      expect(await lightTextInPrint(page)).toEqual([]);
    });

    test(`номера прямо сейчас ${p.name} один раз`, async ({ page }, info) => {
      test.skip(info.project.name !== "desktop");
      await page.goto(p.path);
      const inMain = await page.locator("main .op-now").count();
      const footerTels = await page.locator(".op-footer__tels").count();
      if (inMain) {
        expect(footerTels).toBe(0);
        await expect(page.locator('a[href="tel:112"]')).toHaveCount(1);
      } else {
        expect(footerTels).toBe(1);
      }
      const shown = await page.locator('a[href^="tel:"]').evaluateAll((links) => links.map((a) =>
        (a.querySelector(".op-now__num")?.textContent || a.textContent).replace(/\s+/g, " ").trim()));
      const odd = shown.filter((t) => t && !/^(\d{2,6}|8 \d{3,5} (\d{1,3}-)?\d{2}-\d{2})(,? .+)?$/.test(t));
      expect(odd, "номера в разном виде").toEqual([]);
    });
  });
}

test.describe("CSP и подвал", () => {
  test("CSP запрещает отправку форм и инлайн-стили", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.goto(pages[0].path);
    const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content");
    expect(csp).toContain("form-action 'none'");
    expect(csp).toContain("style-src 'self';");
    expect(csp).not.toContain("unsafe-inline");
  });
});

test.describe("service worker", () => {
  test.skip(!isPwa, "сайт без офлайна");
  test.use({ serviceWorkers: "allow" });
  test.describe.configure({ mode: "serial" });

  test("первый заход не перезагружает страницу и не теряет ввод", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    let loads = 0;
    page.on("load", () => { loads += 1; });
    const target = pages.find((p) => /^(night|case)\/$/.test(p.path)) || pages.find((p) => !p.path.includes("?")) || pages[0];
    await page.goto(target.path, { waitUntil: "domcontentloaded" });
    const field = page.locator("main input:visible:not([type=radio]):not([type=checkbox]), main textarea:visible").first();
    const typed = (await field.count()) > 0;
    if (typed) await field.fill("проверка", { timeout: 500 });
    await page.waitForTimeout(3000);
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 5000 }).toBe(true);
    expect(loads).toBe(1);
    if (typed) await expect(field).toHaveValue("проверка");
  });

  test("«Обновить» перезагружает ровно один раз", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    const swPath = join(root, "_site", "sw.js");
    const original = readFileSync(swPath, "utf8");
    try {
      await page.goto(pages[0].path);
      await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 5000 }).toBe(true);
      await page.reload();
      await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 5000 }).toBe(true);
      writeFileSync(swPath, original.replace('const VERSION = "', 'const VERSION = "next-'), "utf8");
      let loads = 0;
      page.on("load", () => { loads += 1; });
      await page.evaluate(() => navigator.serviceWorker.getRegistration().then((r) => r.update()));
      await expect(page.locator(".op-update")).toBeVisible({ timeout: 10000 });
      expect(loads).toBe(0);
      await page.locator(".op-update button").click();
      await page.waitForEvent("load", { timeout: 10000 });
      await page.waitForTimeout(1500);
      expect(loads).toBe(1);
    } finally {
      writeFileSync(swPath, original, "utf8");
    }
  });

  test("кэш без адресов со строкой запроса и чужих путей", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.goto(pages[0].path);
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), { timeout: 5000 }).toBe(true);
    await page.goto("./?test=1");
    await page.evaluate(() => fetch("/not-this-site/").catch(() => null));
    const keys = await page.evaluate(async () => {
      const out = [];
      for (const name of await caches.keys()) {
        for (const req of await (await caches.open(name)).keys()) out.push(req.url);
      }
      return { urls: out, scope: (await navigator.serviceWorker.getRegistration()).scope };
    });
    expect(keys.urls.filter((u) => u.includes("?"))).toEqual([]);
    expect(keys.urls.filter((u) => !u.startsWith(keys.scope))).toEqual([]);
  });
});
