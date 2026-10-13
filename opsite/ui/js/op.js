import "./prefs.js";

export const LAZY = [
  ["op-data-date", "./data-date.js"],
  ["op-copy", "./copy.js"],
  ["op-share", "./share.js"],
  ["op-print", "./print.js"],
  ["op-wipe", "./wipe.js"],
  ["op-region", "./region.js"],
  ["op-date", "./date3.js"],
  ["manifest", "./sw-client.js"],
];

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const method = (event.submitter?.getAttribute("formmethod") || form.getAttribute("method") || "").toLowerCase();
  if (method === "dialog" || form.hasAttribute("data-allow-submit")) return;
  event.preventDefault();
}, true);

for (const details of document.querySelectorAll(".op-draft__details")) {
  if (!details.hasAttribute("data-keep-open")) details.open = false;
  details.dataset.opReady = "";
}

for (const [name, module] of LAZY.slice(0, -1)) {
  const selector = name === "op-date" ? ".op-date[data-date3]" : name;
  if (document.querySelector(selector)) import(module).catch(() => {});
}

if (document.querySelector('link[rel="manifest"]')) {
  import("./sw-client.js").then(({ registerServiceWorker }) => registerServiceWorker(new URL("../../sw.js", import.meta.url)));
}
