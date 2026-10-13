import { defineConfig } from "@playwright/test";

const port = 8702;
const repo = "pal-devices-data";
const browserName = process.env.OP_BROWSER || "chromium";
const suffix = browserName === "chromium" ? "" : `-${browserName}`;
const touch = { hasTouch: true, isMobile: browserName !== "firefox" };

export default defineConfig({
  workers: process.env.CI ? undefined : 2,
  testDir: ".",
  timeout: browserName === "chromium" ? 60000 : 90000,
  testMatch: ["tests/e2e/**/*.spec.js", "opsite/tests/pages.spec.js"],
  testIgnore: ["scripts/**", "node_modules/**", "vendor/**"],
  outputDir: `_reports/pw${suffix}`,
  reporter: [["list"], ["json", { outputFile: `_reports/e2e${suffix}.json` }]],
  use: { baseURL: `http://127.0.0.1:${port}/${repo}/`, headless: true, locale: "ru-RU", timezoneId: "Europe/Moscow" },
  webServer: {
    command: "uv run python -m opsite serve --no-open",
    url: `http://127.0.0.1:${port}/${repo}/`,
    reuseExistingServer: true,
  },
  projects: [
    { name: "desktop", use: { browserName, viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { browserName, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, ...touch } },
    { name: "nojs", use: { browserName, viewport: { width: 1280, height: 800 }, javaScriptEnabled: false }, grep: /@nojs/ },
  ],
});
