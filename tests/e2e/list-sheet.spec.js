import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect, pdfPages } from "../../opsite/tests/fixtures.js";
import { dataset } from "./data.js";

const devices = dataset("devices-398n").items;
const acts = JSON.parse(readFileSync(join(process.cwd(), "vendor/pal-norms/v1/acts.json"), "utf8")).items;
const act398 = acts.find((a) => a.id === "398n");
const MM = 96 / 25.4;
const PT = 96 / 72;

async function ready(page, path = "list/") {
  await page.goto(path);
  await expect(page.locator("dv-list[data-ready]")).toHaveCount(1);
}

async function pick(page, codes) {
  for (const code of codes) await page.locator(`#r${code} input[data-pick]`).check();
}

const six = () => devices.filter((d) => d.verified).sort((a, b) => b.nkmi_name.length - a.nkmi_name.length).slice(0, 6).map((d) => d.code);

test.describe("весь перечень и лист", () => {
  test("все строки на месте, фильтр по сноске", async ({ page }) => {
    await ready(page);
    await expect(page.locator("tbody tr[data-c]")).toHaveCount(devices.length);
    await expect(page.locator("thead")).toHaveCount(await page.locator("details[data-group]").count());
    await page.getByLabel("Только со сноской о Соцфонде").check();
    await expect(page.locator("tbody tr[data-c]:visible")).toHaveCount(devices.filter((d) => d.fn2).length);
    await page.getByLabel("Только со сноской о Соцфонде").uncheck();
    await page.getByLabel("Найти в перечне").fill("303260");
    await expect(page.locator("tbody tr[data-c]:visible")).toHaveCount(1);
  });

  test("непроверенные строки одной строкой, без второго большого блока", async ({ page }) => {
    const raw = devices.filter((d) => !d.verified).length;
    await page.goto("list/");
    await expect(page.locator(".dv-listpage > .op-status")).toHaveCount(0);
    if (raw) await expect(page.locator(".dv-nvline")).toContainText("Не проверено");
    else await expect(page.locator(".dv-nvline")).toHaveCount(0);
  });

  test("#device= отмечает строку и уходит из адреса", async ({ page }) => {
    await ready(page, "list/#device=303260");
    await expect(page.locator("#r303260 input[data-pick]")).toBeChecked();
    expect(new URL(page.url()).hash).toBe("");
    await expect(page.locator(".dv-tray")).toContainText("В листе 1 изделие");
  });

  test("чужие параметры молча отброшены", async ({ page }) => {
    for (const hash of ["#device=999999", "#foo=1", "#device=abc", "#device=%3Cimg%20src%3Dx%3E"]) {
      await page.goto("about:blank");
      await ready(page, `list/${hash}`);
      await expect(page.locator("input[data-pick]:checked")).toHaveCount(0);
      expect(new URL(page.url()).hash).toBe("");
    }
  });

  test("опасный ввод в фильтр не исполняется и не уходит в адрес", async ({ page }) => {
    const dialogs = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      d.dismiss();
    });
    await ready(page);
    const before = page.url();
    for (const text of ["<img src=x onerror=alert(1)>", "'\"><script>alert(1)</script>"]) {
      await page.getByLabel("Найти в перечне").fill(text);
      await expect(page.locator("[data-none]")).toBeVisible();
    }
    await expect(page.locator("dv-list img, dv-list script")).toHaveCount(0);
    expect(dialogs).toEqual([]);
    expect(page.url()).toBe(before);
  });

  test("печать листа с одной позицией: реквизиты акта, дата, строки для ручки", async ({ page, browserName }) => {
    await ready(page, "list/#device=303260");
    if (browserName === "chromium") expect(await pdfPages(page)).toBe(1);
    await page.emulateMedia({ media: "print" });
    const sheet = page.locator(".dv-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.locator(".op-draft")).toBeVisible();
    const lead = sheet.locator(".dv-sheet__lead");
    await expect(lead).toContainText(`№ ${act398.number}`);
    await expect(lead).toContainText(act398.doc_date.split("-").reverse().join("."));
    await expect(lead).toContainText(act398.eoNumber);
    await expect(lead).toContainText("Приказ");
    await expect(sheet.locator(".op-sheet-footer")).toContainText("Данные от");
    await expect(sheet.locator(".op-sheet-footer")).toContainText("сверьте до");
    await expect(sheet.locator(".dv-sheet__item")).toHaveCount(1);
    await expect(sheet.locator(".dv-sheet__write p")).toHaveText(["Куда обратились", "Дата", "Что ответили"]);
    for (const box of await sheet.locator(".dv-sheet__write p").all()) {
      expect((await box.boundingBox()).height).toBeGreaterThanOrEqual(14 * MM - 0.5);
    }
    const sizes = await sheet.locator(".dv-sheet__item p, .dv-sheet__item h3, .dv-sheet__lead").evaluateAll((els) =>
      els.map((el) => parseFloat(getComputedStyle(el).fontSize)));
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11 * PT - 0.1);
    await expect(page.locator(".dv-filters")).toBeHidden();
  });

  test("шесть позиций: целиком, не больше двух страниц A4", async ({ page, browserName }) => {
    await ready(page);
    const codes = six();
    test.skip(codes.length < 6, "в данных меньше шести сверенных строк");
    await pick(page, codes);
    await expect(page.locator(".dv-tray")).toContainText("В листе 6 изделий");
    if (browserName === "chromium") expect(await pdfPages(page)).toBeLessThanOrEqual(2);
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".dv-sheet__item")).toHaveCount(6);
    const avoid = await page.locator(".dv-sheet__item").first().evaluate((el) => getComputedStyle(el).breakInside);
    expect(avoid).toBe("avoid");
  });

  test("непроверенная позиция не попадает в лист", async ({ page }) => {
    const raw = devices.find((d) => !d.verified);
    test.skip(!raw, "все строки сверены");
    await ready(page);
    await page.locator(`#r${raw.code} input[data-pick]`).check();
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".dv-sheet")).toContainText("Пункт не проверен и в лист не включён");
    await expect(page.locator(".dv-sheet__item")).toHaveCount(0);
  });

  test("очистить выбор", async ({ page }) => {
    await ready(page, "list/#device=303260");
    await page.getByRole("button", { name: "Очистить выбор" }).click();
    await expect(page.locator("input[data-pick]:checked")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Распечатать или сохранить PDF" })).toBeDisabled();
  });

  test("выбор нигде не хранится", async ({ page }) => {
    await ready(page, "list/#device=303260");
    await pick(page, ["280360"]);
    const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => !k.startsWith("op:prefs")));
    expect(stored).toEqual([]);
    expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
    await page.reload();
    await expect(page.locator("dv-list[data-ready]")).toHaveCount(1);
    await expect(page.locator("input[data-pick]:checked")).toHaveCount(0);
  });

  test("без скриптов группы открываются ссылками @nojs", async ({ page }, info) => {
    test.skip(info.project.name !== "nojs");
    await page.goto("list/");
    await page.locator(".dv-grp__open a").first().click();
    await expect(page).toHaveURL(/list\/1\/$/);
    await expect(page.locator(".dv-table tbody tr").first()).toBeVisible();
  });
});
