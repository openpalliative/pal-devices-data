import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test, setSize } from "../../opsite/tests/fixtures.js";

const pages = JSON.parse(readFileSync(join(process.cwd(), "tests/e2e/pages.json"), "utf8"));
const OUT = join(process.cwd(), "..", "_reports", "shots", "pal-devices-data");
const WIDTHS = [360, 390, 768, 1024, 1440];
const THEMES = ["light", "dark"];
mkdirSync(OUT, { recursive: true });

function only(info, browser = "chromium") {
  if (info.project.name !== "desktop" || test.info().project.use.browserName !== browser) test.skip();
  test.setTimeout(180000);
}

async function snap(page, name) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(50);
  await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: true });
}

async function ask(page, text) {
  await page.fill("#dv-q", text);
  await page.press("#dv-q", "Enter");
  await page.locator(".dv-results > *").first().waitFor();
}

for (const p of [...pages.filter((x) => !x.path.includes("#")), { name: "404", path: "devices/000000/" }]) {
  test(`снимки ${p.name} на пяти ширинах в двух темах @shots`, async ({ page }, info) => {
    only(info);
    for (const w of WIDTHS) {
      await page.setViewportSize({ width: w, height: w < 600 ? 800 : 900 });
      for (const theme of THEMES) {
        await page.emulateMedia({ colorScheme: theme, media: "screen" });
        await page.goto(p.path);
        await snap(page, `${p.name}-${w}-${theme}`);
      }
    }
  });
}

test("снимки A++ на 390 @shots", async ({ page }, info) => {
  only(info);
  await setSize(page, "xl");
  await page.setViewportSize({ width: 390, height: 844 });
  for (const p of pages.filter((x) => ["home", "device-280360", "list", "nutrition"].includes(x.name))) {
    await page.goto(p.path);
    await snap(page, `${p.name}-390-xl`);
  }
});

test("снимки поиска: нашлось, неоднозначно, пусто, сбой @shots", async ({ page }, info) => {
  only(info);
  for (const w of [390, 1440]) {
    await page.setViewportSize({ width: w, height: 900 });
    for (const [name, word] of [["found", "кислородник"], ["ambiguous", "трубка"], ["empty", "абракадабра"]]) {
      await page.goto("");
      await ask(page, word);
      await snap(page, `search-${name}-${w}-light`);
    }
  }
  await page.route("**/data/v1/aliases.json", (r) => r.fulfill({ status: 404, body: "" }));
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("");
  await ask(page, "кислород");
  await snap(page, "search-error-390-light");
});

test("снимки печати листа: 1 и 6 позиций @shots", async ({ page }, info) => {
  only(info);
  await page.setViewportSize({ width: 794, height: 1123 });
  const six = ["280360", "303260", "207990", "113810", "191160", "233160"];
  for (const n of [1, 6]) {
    await page.emulateMedia({ media: "screen" });
    await page.goto("list/");
    await page.locator("dv-list[data-ready]").waitFor({ state: "attached" });
    for (const code of six.slice(0, n)) await page.locator(`#r${code} input[data-pick]`).check();
    await page.emulateMedia({ media: "print", colorScheme: "light" });
    await snap(page, `print-sheet-${n}`);
    await page.emulateMedia({ media: null });
    await page.pdf({ path: join(OUT, `print-sheet-${n}.pdf`), format: "A4", preferCSSPageSize: true });
  }
});

for (const browser of ["firefox", "webkit"]) {
  test.describe(browser, () => {
    test.use({ bypassCSP: browser === "webkit" });
    test(`снимки ${browser}: главная, карточка, перечень @shots`, async ({ page }, info) => {
      only(info, browser);
      for (const w of [390, 1440]) {
        await page.setViewportSize({ width: w, height: 900 });
        for (const p of ["", "devices/280360/", "list/"]) {
          await page.goto(p);
          await snap(page, `${browser}-${(p || "home").replace(/\/$/, "").replace(/\//g, "-")}-${w}`);
        }
      }
    });
  });
}
