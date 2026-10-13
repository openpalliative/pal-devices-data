import { getRegion, setRegion } from "./region-store.js";
import { matchRegion } from "./region-match.js";

const LIMIT = 8;
const SLUG = /regions\/(ru-[a-z]{2,3})\/?$/;

export { getRegion, setRegion };
export { matchRegion };

class OpRegion extends HTMLElement {
  connectedCallback() {
    const $ = (s) => this.querySelector(s);
    const details = $(".op-region__pick");
    const prompt = $(".op-region__prompt");
    const current = $(".op-region__current");
    const nameEl = $("[data-region-name]");
    const cardLink = $("[data-region-link]");
    const search = $(".op-region__search");
    const input = search?.querySelector("input");
    const suggest = search?.querySelector(".op-region__suggest");
    const count = search?.querySelector(".op-region__count");
    const linesBox = $(".op-region__lines");
    const base = this.dataset.base || "";
    const links = [...this.querySelectorAll(".op-region__list a")].filter((a) => SLUG.test(a.getAttribute("href")));
    const regions = links.map((a) => {
      a.dataset.region = SLUG.exec(a.getAttribute("href"))[1].toUpperCase();
      return { id: a.dataset.region, name: a.textContent.trim(), capital: "", aliases: [], href: a.getAttribute("href") };
    });
    const byId = new Map(regions.map((r) => [r.id, r]));
    let found = [];
    let active = -1;
    let shown = null;
    let indexLoad = null;

    const loadIndex = () => {
      if (!indexLoad && this.dataset.index) {
        indexLoad = fetch(this.dataset.index).then((r) => (r.ok ? r.json() : [])).then((rows) => {
          for (const row of rows) {
            const r = byId.get(row.id);
            if (r) Object.assign(r, { capital: row.capital || "", aliases: row.aliases || [] });
          }
        }).catch(() => {});
      }
      return indexLoad || Promise.resolve();
    };

    const cardHref = (iso) => `${base}${iso.toLowerCase()}/`;

    const showLines = (iso) => {
      if (!linesBox) return;
      if (!iso) {
        shown = null;
        linesBox.replaceChildren();
        return;
      }
      if (shown === iso) return;
      shown = iso;
      import("./region-lines.js").then(({ renderLines }) => {
        if (shown === iso) renderLines(linesBox, { iso, name: byId.get(iso)?.name, base: this.dataset.lines || "", card: cardHref(iso) });
      }).catch(() => {});
    };

    const render = () => {
      const iso = getRegion();
      const region = iso ? byId.get(iso) : null;
      const known = Boolean(region && current && nameEl);
      if (known) {
        nameEl.textContent = region.name;
        if (cardLink) cardLink.href = cardHref(iso);
      }
      if (current) current.hidden = !known;
      if (prompt) prompt.hidden = known;
      if (search) search.hidden = known || !input;
      if (details) details.hidden = known;
      showLines(known ? iso : null);
    };

    const closeSuggest = () => {
      found = [];
      active = -1;
      if (suggest) {
        suggest.hidden = true;
        suggest.replaceChildren();
      }
      input?.setAttribute("aria-expanded", "false");
      input?.removeAttribute("aria-activedescendant");
    };

    const choose = (iso) => {
      setRegion(iso);
      if (input) input.value = "";
      if (count) count.textContent = "";
      closeSuggest();
      render();
      current?.querySelector("a")?.focus();
    };

    const highlight = (i) => {
      const items = [...suggest.querySelectorAll("a")];
      active = items.length ? (i + items.length) % items.length : -1;
      items.forEach((a, j) => a.setAttribute("aria-selected", String(j === active)));
      if (active >= 0) input.setAttribute("aria-activedescendant", items[active].id);
    };

    const apply = () => {
      const q = input.value.trim();
      if (!q) {
        closeSuggest();
        if (count) count.textContent = "";
        return;
      }
      found = matchRegion(q, regions);
      suggest.replaceChildren(...found.slice(0, LIMIT).map((r, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "presentation");
        const a = document.createElement("a");
        a.textContent = r.name;
        a.id = `${input.id}-opt-${i}`;
        a.href = r.href;
        a.dataset.pick = r.id;
        a.tabIndex = -1;
        a.setAttribute("role", "option");
        a.setAttribute("aria-selected", "false");
        li.append(a);
        return li;
      }));
      suggest.hidden = found.length === 0;
      input.setAttribute("aria-expanded", String(found.length > 0));
      active = -1;
      if (count) {
        count.textContent = !found.length ? "Такого региона нет. Попробуйте другое слово или откройте все регионы списком"
          : found.length > LIMIT ? `Подходит регионов: ${found.length}. Уточните название` : `Подходит регионов: ${found.length}`;
      }
    };

    if (input && suggest) {
      input.addEventListener("focus", loadIndex, { once: true });
      input.addEventListener("input", () => loadIndex().then(apply));
      input.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          if (!found.length) return;
          event.preventDefault();
          highlight(active + (event.key === "ArrowDown" ? 1 : -1));
        } else if (event.key === "Enter") {
          event.preventDefault();
          const pick = active >= 0 ? found[active] : found.length === 1 ? found[0] : null;
          if (pick) choose(pick.id);
        } else if (event.key === "Escape") {
          closeSuggest();
        }
      });
      suggest.addEventListener("click", (event) => {
        const a = event.target.closest("[data-pick]");
        if (!a) return;
        event.preventDefault();
        choose(a.dataset.pick);
      });
    }
    for (const a of links) {
      a.addEventListener("click", (event) => {
        if (!linesBox) {
          setRegion(a.dataset.region);
          return;
        }
        event.preventDefault();
        if (details) details.open = false;
        choose(a.dataset.region);
      });
    }
    $("[data-region-change]")?.addEventListener("click", () => {
      if (current) current.hidden = true;
      if (prompt) prompt.hidden = false;
      if (search && input) search.hidden = false;
      if (details) details.hidden = false;
      (input || details?.querySelector("summary"))?.focus();
    });
    $("[data-region-forget]")?.addEventListener("click", () => {
      setRegion(null);
      render();
      (input || details?.querySelector("summary"))?.focus();
    });
    document.addEventListener("op-region-change", (event) => {
      if (event.detail?.region === getRegion()) render();
    });
    render();
  }
}

if (!customElements.get("op-region")) customElements.define("op-region", OpRegion);
