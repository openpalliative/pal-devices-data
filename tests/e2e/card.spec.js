import { test, expect } from "../../opsite/tests/fixtures.js";
import { dataset } from "./data.js";

const devices = dataset("devices-398n").items;
const norm = (t) => String(t || "").toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
const renamed = devices.filter((d) => d.nkmi_name_now && norm(d.nkmi_name_now) !== norm(d.nkmi_name));
const FRAMES = ".dv-who, .op-quote, .op-status:not(.op-status--inline), .op-card, .dv-ed, .dv-path, .dv-result";

test.describe("карточка изделия", () => {
  test("без сноски: одна строка крупно и «Почему так» свёрнуто", async ({ page }) => {
    await page.goto("devices/303260/");
    const who = page.locator(".dv-who");
    await expect(who.locator(".dv-who__answer")).toContainText("медицинская организация");
    await expect(who.locator(".dv-who__basis a[href='#q-row']")).toBeVisible();
    const why = who.locator("details.dv-why");
    await expect(why).not.toHaveAttribute("open", "");
    await why.locator("summary").click();
    await expect(why.locator(".op-status--info")).toBeVisible();
    await expect(why.getByRole("link", { name: /пункт 26/ })).toHaveAttribute("href", "../../channels/#q-208n-p26");
  });

  test("со сноской: обе ветки одной строкой, строка перечня и сноска 2 целиком", async ({ page }) => {
    await page.goto("devices/280360/");
    await expect(page.locator(".dv-who__answer")).toContainText("при инвалидности может выдать Соцфонд");
    const why = page.locator("details.dv-why");
    await why.locator("summary").click();
    await expect(why.locator(".op-status--unverified").first()).toContainText("Не проверено");
    await expect(page.locator("#q-row blockquote")).toContainText("280360");
    await expect(page.locator("#q-398n-fn2 blockquote")).toBeVisible();
    await expect(page.locator("#q-398n-fn2 blockquote")).toContainText("Пункт 26");
    const more = page.locator(".dv-basis-more a");
    expect(await more.evaluateAll((a) => a.map((x) => x.getAttribute("href")))).toEqual(
      expect.arrayContaining(["../../channels/#q-208n-p25", "../../channels/#q-208n-p26"]));
  });

  test("номер публикации и код от 16px", async ({ page }) => {
    await page.goto("devices/280360/");
    for (const sel of [".dv-card__kind .dv-code", "#q-row .op-cite__eo", "#q-row .dv-code"]) {
      const size = await page.locator(sel).first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(size, sel).toBeGreaterThanOrEqual(16);
    }
    await expect(page.locator("#q-row .op-cite__eo")).toBeVisible();
  });

  test("не больше двух уровней рамок", async ({ page }) => {
    for (const code of ["303260", "280360", "259910"]) {
      await page.goto(`devices/${code}/`);
      const depth = await page.locator("main").evaluate((main, sel) => {
        let max = 0;
        for (const el of main.querySelectorAll(sel)) {
          let n = 1;
          for (let p = el.parentElement; p && p !== main; p = p.parentElement) if (p.matches(sel)) n += 1;
          max = Math.max(max, n);
        }
        return max;
      }, FRAMES);
      expect(depth, code).toBeLessThanOrEqual(2);
    }
  });

  test("кнопки «Что дальше»", async ({ page }) => {
    await page.goto("devices/303260/");
    const link = page.getByRole("link", { name: /Не выдают\?/ });
    await expect(link).toHaveAttribute("href", "/obrashchenie-kit/case/#new=1&s=oral-refusal&device=303260");
    await expect(page.getByRole("link", { name: /Добавить в лист/ })).toHaveAttribute("href", "../../list/#device=303260");
    await expect(page.locator(".dv-next .op-btn--primary")).toHaveCount(1);
  });

  test("возврат к ситуации по back= и очистка адреса", async ({ page }) => {
    await page.goto("devices/303260/#back=device");
    await expect(page.locator("dv-back")).toBeVisible();
    await expect(page.locator("dv-back a:visible")).toHaveAttribute("href", "/s/device/");
    expect(new URL(page.url()).hash).toBe("");
  });

  for (const [path, id] of [["./", "discharge"], ["changes/", "device"]]) {
    test(`возврат к ситуации с ${path} по back=${id}`, async ({ page }) => {
      await page.goto(`${path}#back=${id}`);
      await expect(page.locator("dv-back a:visible")).toHaveAttribute("href", `/s/${id}/`);
      expect(new URL(page.url()).hash).toBe("");
    });
  }

  test("код со сменённым названием: предупреждение до строки канала", async ({ page }) => {
    test.skip(!renamed.length, "в данных нет кодов со сменённым названием");
    const codes = renamed.map((d) => d.code);
    if (devices.some((d) => d.code === "259910" && d.nkmi_name_now)) expect(codes).toContain("259910");
    for (const d of renamed) {
      await page.goto(`devices/${d.code}/`);
      const warn = page.locator(".dv-renamed");
      await expect(warn).toContainText("Росздравнадзор сменил название вида под этим кодом после выхода перечня");
      await expect(warn).toContainText(d.nkmi_name_now);
      const before = await page.evaluate(() => {
        const a = document.querySelector(".dv-renamed");
        const b = document.querySelector(".dv-who");
        return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      expect(before).toBe(true);
      await expect(page.locator("main")).not.toContainText("записал под этим кодом в своём справочнике другой вид");
    }
  });

  test("основание дословно без скриптов @nojs", async ({ page }, info) => {
    test.skip(info.project.name !== "nojs");
    await page.goto("devices/280360/");
    await expect(page.locator("#q-row blockquote")).toBeVisible();
    await expect(page.locator("#q-398n-fn2 blockquote")).toBeVisible();
    await expect(page.locator(".dv-who__answer")).toBeVisible();
  });

  test("карточка на телефоне 390 не длиннее 4500px", async ({ page }, info) => {
    test.skip(info.project.name !== "mobile");
    const longest = [...devices].sort((a, b) => b.nkmi_name.length - a.nkmi_name.length).slice(0, 2).map((d) => d.code);
    for (const code of [...new Set(["280360", "207990", ...longest])]) {
      await page.goto(`devices/${code}/`);
      await page.evaluate(() => document.fonts.ready);
      const h = await page.evaluate(() => document.documentElement.scrollHeight);
      expect(h, code).toBeLessThanOrEqual(4500);
    }
  });
});
