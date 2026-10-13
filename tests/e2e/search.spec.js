import { test, expect, setSize, noHorizontalScroll } from "../../opsite/tests/fixtures.js";
import { dataset } from "./data.js";

const devices = dataset("devices-398n").items;
const norm = (t) => String(t || "").toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const changed = devices.filter((d) => d.nkmi_name_now && norm(d.nkmi_name_now) !== norm(d.nkmi_name));
const renamed = changed.find((d) => d.code === "259910") || changed[0];
const wide = dataset("aliases").items.find((a) => !a.search_only && new Set(a.codes).size > 12);
const PAYLOADS = ["<img src=x onerror=alert(1)>", "'\"><script>alert(1)</script>"];

async function ask(page, text) {
  const field = page.getByLabel("Как вы это называете?");
  await field.fill(text);
  await field.press("Enter");
}

test.describe("поиск", () => {
  test("откашливатель ведёт на карточку, «Кто выдаёт» на первом экране телефона", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("");
    const before = page.url();
    await ask(page, "откашливатель");
    const first = page.locator(".dv-result").first();
    await expect(first).toContainText("303260");
    await expect(page.locator(".dv-results__head")).toContainText("Нашлось");
    expect(page.url()).toBe(before);
    await first.locator("a").click();
    await expect(page).toHaveURL(/devices\/303260\/$/);
    await expect(page.locator(".dv-who__answer")).toBeInViewport();
    await expect(page.locator(".dv-who__answer")).toContainText("Выдаёт медицинская организация");
  });

  test("поле и быстрые кнопки на первом экране 360x640", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("");
    await expect(page.locator("#dv-q")).toBeInViewport({ ratio: 1 });
    for (const chip of await page.locator(".dv-chip").all()) await expect(chip).toBeInViewport({ ratio: 1 });
  });

  test("кислородник даёт два концентратора", async ({ page }) => {
    await page.goto("");
    await ask(page, "кислородник");
    await expect(page.locator(".dv-result")).toHaveCount(2);
    const codes = await page.locator(".dv-result__code").allTextContents();
    expect(codes.sort()).toEqual(["113810", "191160"]);
  });

  test("трубка показывает разные изделия группами", async ({ page }) => {
    await page.goto("");
    await ask(page, "трубка");
    await expect(page.locator(".dv-results")).toContainText("означает разные изделия");
    expect(await page.locator(".dv-group").count()).toBeGreaterThan(1);
  });

  test("пустой результат предлагает название и предупреждает о приватности", async ({ page }) => {
    await page.goto("");
    await ask(page, "абракадабра");
    await expect(page.locator(".dv-empty")).toContainText("Такого названия мы не нашли");
    await expect(page.locator(".dv-empty")).toContainText("Не пишите в предложении имя, диагноз и регион");
    const suggest = page.locator(".dv-empty").getByRole("link", { name: "Предложить название" });
    await expect(suggest).toHaveAttribute("href", /issues\/new\?template=alias\.yml$/);
    expect(page.url()).not.toContain("абракадабра");
  });

  test("быстрая кнопка подставляет слово", async ({ page }) => {
    await page.goto("");
    await page.locator(".dv-chip", { hasText: "Откашливатель" }).click();
    await expect(page.getByLabel("Как вы это называете?")).toHaveValue("откашливатель");
    await expect(page.locator(".dv-result").first()).toContainText("303260");
    expect(new URL(page.url()).hash).toBe("");
  });

  test("код из шести цифр ищет код", async ({ page }) => {
    await page.goto("");
    await ask(page, "280360");
    await expect(page.locator(".dv-result")).toHaveCount(1);
    await expect(page.locator(".dv-result")).toContainText("Медорганизация или Соцфонд");
  });

  test("код со сменённым названием: предупреждение до строки канала", async ({ page }) => {
    test.skip(!renamed, "в данных нет кодов со сменённым названием");
    await page.goto("");
    await ask(page, renamed.code);
    const res = page.locator(".dv-result");
    await expect(res.locator(".dv-result__renamed")).toContainText("Росздравнадзор сменил название вида под этим кодом после выхода перечня");
    const order = await res.evaluate((li) => {
      const kids = [...li.children];
      return kids.indexOf(li.querySelector(".dv-result__renamed")) < kids.indexOf(li.querySelector(".dv-ch"));
    });
    expect(order).toBe(true);
  });

  test("сбой загрузки не выглядит как «не нашли», повторный ввод пробует снова", async ({ page }) => {
    let fail = true;
    await page.route("**/data/v1/aliases.json", (route) => (fail ? route.fulfill({ status: 404, body: "" }) : route.continue()));
    await page.goto("");
    await ask(page, "откашливатель");
    await expect(page.locator(".dv-results")).toContainText("Не получилось загрузить перечень. Обновите страницу");
    await expect(page.locator(".dv-results").getByRole("link", { name: "откройте весь перечень" })).toHaveAttribute("href", "list/");
    await expect(page.locator(".dv-empty")).not.toContainText("Такого названия мы не нашли");
    fail = false;
    await ask(page, "откашливатель ");
    await expect(page.locator(".dv-result").first()).toContainText("303260");
  });

  test("опасный ввод не исполняется и не уходит в адрес и хранилище", async ({ page }) => {
    const dialogs = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      d.dismiss();
    });
    await page.goto("");
    const before = page.url();
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }));
    for (const text of PAYLOADS) {
      await ask(page, text);
      await expect(page.locator(".dv-results")).not.toBeEmpty();
      await expect(page.locator(".dv-results img, .dv-results script")).toHaveCount(0);
    }
    await page.waitForTimeout(300);
    expect(dialogs).toEqual([]);
    expect(page.url()).toBe(before);
    expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).toBe(stored);
    expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage }))).toBe("{}");
  });

  test("без скриптов быстрые кнопки ведут в указатель названий @nojs", async ({ page }, info) => {
    test.skip(info.project.name !== "nojs");
    await page.goto("");
    const chip = page.locator(".dv-chip", { hasText: "Откашливатель" });
    const href = await chip.getAttribute("href");
    expect(href).toMatch(/^names\/#a-/);
    await chip.click();
    await expect(page).toHaveURL(/names\/#a-/);
    await expect(page.locator(`[id="${href.split("#")[1]}"]`)).toBeVisible();
    await expect(page.locator(`[id="${href.split("#")[1]}"] a`).first()).toHaveAttribute("href", /devices\/\d{6}\//);
  });

  test("A++ на 360: результаты поиска без горизонтальной прокрутки", async ({ page }, info) => {
    test.skip(info.project.name !== "mobile");
    await setSize(page, "xl");
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("");
    for (const word of ["трубка", "кислородник", "абракадабра", renamed ? renamed.code : "303260"]) {
      await ask(page, word);
      await page.locator(".dv-results > *").first().waitFor();
      await noHorizontalScroll(page);
    }
  });

  test("больше двенадцати изделий: честно говорим, что показаны не все", async ({ page }) => {
    test.skip(!wide);
    await page.goto("");
    await ask(page, wide.alias);
    const more = page.locator(".dv-results__more");
    await expect(more).toContainText(/Показаны первые 12 из \d+/);
    const total = Number((await more.innerText()).match(/из (\d+)/)[1]);
    expect(total).toBeGreaterThanOrEqual(new Set(wide.codes).size);
    await expect(more.getByRole("link", { name: "весь перечень" })).toHaveAttribute("href", /\/list\/$/);
  });
});
