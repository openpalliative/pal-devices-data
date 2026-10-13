const KEY = "op:prefs";

function read() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

function write(prefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {}
}

export function applyPrefs(prefs, root = document.documentElement) {
  root.setAttribute("data-theme", prefs.theme === "light" || prefs.theme === "dark" ? prefs.theme : "auto");
  root.setAttribute("data-size", prefs.size === "l" || prefs.size === "xl" ? prefs.size : "m");
}

const SIZES = [["m", "A", "обычный"], ["l", "A+", "крупнее"], ["xl", "A++", "самый крупный"]];
const THEMES = [["auto", "monitor", "Как на устройстве"], ["light", "sun", "Светлая"], ["dark", "moon", "Тёмная"]];

function node(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children);
  return el;
}

function iconNode(sprite, name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "op-icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", `${sprite}#${name}`);
  svg.append(use);
  return svg;
}

function group(legend, name, cls, items) {
  return node("fieldset", { class: "op-prefs__group" }, node("legend", {}, legend), node("div", { class: cls }, ...items.map(
    ([value, label]) => node("label", {}, node("input", { type: "radio", name, value }), ...label))));
}

export function buildPanel(panel, sprite) {
  if (panel.childElementCount) return;
  panel.append(
    group("Размер текста", "op-size", "op-seg", SIZES.map(([value, a, hint], i) => [value, [
      node("span", { class: `op-seg__a${i ? ` op-seg__a--${value}` : ""}` }, a),
      node("span", { class: "op-visually-hidden" }, ` ${hint}`)]])),
    group("Тема", "op-theme", "op-seg op-seg--wide", THEMES.map(([value, icon, text]) => [value, [
      iconNode(sprite, icon), node("span", {}, text)]])),
  );
}

class OpPrefs extends HTMLElement {
  connectedCallback() {
    const prefs = { theme: "auto", size: "m", ...read() };
    const panel = this.querySelector(".op-prefs__panel");
    if (panel) buildPanel(panel, this.dataset.icons || "");
    for (const input of this.querySelectorAll("input[type=radio]")) {
      const key = input.name === "op-theme" ? "theme" : "size";
      input.checked = prefs[key] === input.value;
      input.addEventListener("change", () => {
        prefs[key] = input.value;
        write(prefs);
        applyPrefs(prefs);
      });
    }
    const details = this.querySelector("details");
    this.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && details?.open) {
        details.open = false;
        details.querySelector("summary")?.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (details?.open && !this.contains(event.target)) details.open = false;
    });
    this.hidden = false;
  }
}

if (!customElements.get("op-prefs")) customElements.define("op-prefs", OpPrefs);
