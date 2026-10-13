import { test as base, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const LOCAL = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//;

export const test = base.extend({
  blocked: [async ({ context }, use) => {
    const blocked = [];
    await context.route("**/*", (route) => {
      const url = route.request().url();
      if (LOCAL.test(url) || url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
      blocked.push(url);
      return route.abort("blockedbyclient");
    });
    await use(blocked);
    expect(blocked, "запросы за пределы своего адреса").toEqual([]);
  }, { auto: true }],
  cspViolations: [async ({ context }, use) => {
    const violations = [];
    await context.exposeBinding("__opCspViolation", (_source, v) => violations.push(v));
    await context.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (e) => {
        window.__opCspViolation?.(`${e.violatedDirective} ${e.blockedURI || ""} ${e.sourceFile || ""}:${e.lineNumber || 0}`);
      });
    });
    await use(violations);
    expect(violations, "нарушения CSP").toEqual([]);
  }, { auto: true }],
  consoleErrors: [async ({ page }, use) => {
    const errors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !/Failed to load resource: the server responded with a status of 404/.test(msg.text())) {
        errors.push(msg.text());
      }
    });
    page.on("pageerror", (err) => errors.push(String(err)));
    await use(errors);
    expect(errors, "ошибки в консоли").toEqual([]);
  }, { auto: true }],
});

export { expect };

export async function checkA11y(page, { exclude = [] } = {}) {
  let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]);
  for (const sel of exclude) builder = builder.exclude(sel);
  const result = await builder.analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const moderate = result.violations.filter((v) => !bad.includes(v));
  if (moderate.length) {
    test.info().annotations.push({ type: "axe-moderate", description: moderate.map((v) => v.id).join(", ") });
  }
  expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join("; ")})`)).toEqual([]);
}

export async function pdfPages(page) {
  const buf = await page.pdf({ format: "A4", preferCSSPageSize: true, printBackground: false });
  return (buf.toString("latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
}

export async function shot(page, name, { themes = ["light", "dark"], print = false } = {}) {
  const project = test.info().project.name;
  const dir = join(process.cwd(), "_reports", "shots");
  mkdirSync(dir, { recursive: true });
  for (const theme of themes) {
    await page.emulateMedia({ colorScheme: theme, media: "screen" });
    await page.waitForTimeout(50);
    await page.screenshot({ path: join(dir, `${project}-${theme}-${name}.png`), fullPage: true });
  }
  if (print) {
    await page.emulateMedia({ colorScheme: "light", media: "print" });
    await page.screenshot({ path: join(dir, `${project}-light-${name}-print.png`), fullPage: true });
    await page.emulateMedia({ media: "screen" });
  }
}

export async function noHorizontalScroll(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "горизонтальная прокрутка страницы").toBeLessThanOrEqual(0);
}

export async function setSize(page, size) {
  await page.addInitScript((s) => {
    try {
      localStorage.setItem("op:prefs", JSON.stringify({ size: s }));
    } catch {}
  }, size);
}

export async function smallPlatformText(page, min) {
  return page.evaluate((min) => {
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) continue;
      const el = node.parentElement;
      if (!el || el.closest("svg, .op-visually-hidden, [hidden], template, .op-print-only, .op-doc, .op-sheet, script, style")) continue;
      let owner = el;
      while (owner && !(owner.className && typeof owner.className === "string" && owner.className.trim())) owner = owner.parentElement;
      if (!owner || !owner.className.split(/\s+/).some((c) => c.startsWith("op-"))) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (!el.checkVisibility({ visibilityProperty: true }) || !r.width || !r.height) continue;
      const size = parseFloat(cs.fontSize);
      if (size < min - 0.01) out.push(`${owner.className.split(/\s+/)[0]} ${size}px «${node.textContent.trim().slice(0, 24)}»`);
    }
    return [...new Set(out)];
  }, min);
}

export async function smallPlatformTargets(page) {
  return page.evaluate(() => {
    const out = [];
    const scope = ".op-header, .op-footer, .op-tools-bottom, .op-now, .op-crumbs, .op-draft, .op-region, .op-steps, .op-actions, .op-cite, .op-status, .op-toc, .op-subnav";
    for (const el of document.querySelectorAll("a, button, summary, label")) {
      if (!el.closest(scope) || el.closest(".op-prose, [hidden], template, .op-visually-hidden, .op-prefs__panel")) continue;
      if (el.matches("label.op-field__label, .op-date__part label")) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height || !el.checkVisibility({ visibilityProperty: true })) continue;
      if (r.height >= 43.5) continue;
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const hit = (y) => {
        if (y < 0 || y > innerHeight) return true;
        const at = document.elementFromPoint(cx, y);
        return at && (at === el || el.contains(at));
      };
      if (hit(cy - 21) && hit(cy + 21)) continue;
      out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} «${el.textContent.trim().slice(0, 24)}» ${Math.round(r.height)}px`);
    }
    return out;
  });
}

export async function lightTextInPrint(page) {
  return page.evaluate(() => {
    const lum = (rgb) => {
      const m = rgb.match(/[\d.]+/g);
      if (!m) return 0;
      const [r, g, b] = m.slice(0, 3).map((v) => {
        const c = Number(v) / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const out = [];
    for (const el of document.querySelectorAll("main *")) {
      if (!el.childNodes.length || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      const cs = getComputedStyle(el);
      if (!el.checkVisibility({ visibilityProperty: true })) continue;
      if (lum(cs.color) > 0.4) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} ${cs.color}`);
    }
    return [...new Set(out)].slice(0, 10);
  });
}
