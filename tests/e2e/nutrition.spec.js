import { test, expect } from "../../opsite/tests/fixtures.js";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { dataset } from "./data.js";

const vq = join(process.cwd(), "vendor", "pal-norms", "v1", "quotes.json");
const fromNorms = existsSync(vq) ? JSON.parse(readFileSync(vq, "utf8")).items.find((q) => q.id === "323fz-37-15") : null;

const editions = dataset("nutrition-3551r").items;
const base = editions.find((n) => n.kind === "base") || editions[0];
const ru = (iso) => iso.split("-").reverse().join(".");

test.describe("лечебное питание", () => {
  test("все редакции с номером, датой и номером публикации", async ({ page }) => {
    await page.goto("nutrition/");
    const cards = page.locator(".dv-ed");
    await expect(cards).toHaveCount(editions.length);
    for (const n of editions) {
      const card = cards.filter({ hasText: n.id });
      await expect(card).toHaveCount(1);
      await expect(card.locator(".dv-ed__title")).toContainText(`№ ${n.number}`);
      await expect(card.locator(".dv-ed__title")).toContainText(ru(n.date));
      if (n.kind === "amendment" && n.items_from) {
        const range = n.items_to !== n.items_from ? `${n.items_from}-${n.items_to}` : `${n.items_from}`;
        await expect(card.locator(".dv-ed__change")).toContainText(`Дополняет перечень пунктами ${range}`);
        await expect(card.locator(".dv-ed__change")).toContainText(`стр. ${n.items_scan_pages}`);
      }
    }
    await expect(page.locator("main")).not.toContainText("не сверили");
  });

  test("«Продукта нет в перечне»: цитата ч. 15 ст. 37 или честное «Не проверено»", async ({ page }) => {
    await page.goto("nutrition/");
    const section = page.locator(".dv-notlisted");
    const quote = section.locator("#q-323fz-37-15 blockquote");
    if (fromNorms && fromNorms.verified === true) await expect(quote).toHaveCount(1);
    if (await quote.count()) {
      await expect(quote).not.toBeEmpty();
      await expect(section.locator(".dv-legal-mark")).toContainText("Черновик");
      await expect(section.locator("#q-323fz-37-15 .op-cite__eo")).toContainText("0001201812250098");
      await expect(section.locator("#q-323fz-37-15 .op-cite__link")).toHaveAttribute("href", /publication\.pravo\.gov\.ru/);
      await expect(section.locator("#q-323fz-37-15 .op-cite")).toContainText("стр.");
    } else {
      await expect(section.locator(".op-status--unverified")).toContainText("Не проверено");
      await expect(section.locator(".dv-qsteps")).toHaveCount(0);
    }
    await expect(section).not.toContainText("не сверили");
  });

  test("кнопка «Отказали в питании» с базовой редакцией", async ({ page }) => {
    await page.goto("nutrition/");
    await expect(page.getByRole("link", { name: "Отказали в питании" })).toHaveAttribute(
      "href", `/obrashchenie-kit/case/#new=1&s=oral-refusal&nut=${base.id}`);
  });

  test("страницы всех редакций", async ({ page }) => {
    for (const n of editions) {
      await page.goto(`nutrition/${n.id}/`);
      await expect(page.locator("h1")).toContainText(`№ ${n.number}`);
      await expect(page.locator(".dv-req")).toContainText(n.id);
      await expect(page.getByRole("link", { name: "Открыть официальную публикацию" })).toHaveAttribute("href", n.url);
    }
  });

  test("без скриптов всё на месте @nojs", async ({ page }, info) => {
    test.skip(info.project.name !== "nojs");
    await page.goto("nutrition/");
    await expect(page.locator(".dv-ed")).toHaveCount(editions.length);
    await expect(page.locator(".dv-notlisted")).toBeVisible();
    await expect(page.getByRole("link", { name: "Отказали в питании" })).toBeVisible();
  });
});
