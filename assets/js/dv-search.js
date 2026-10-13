const LIB = new URL("../../lib/search.js", import.meta.url).href;

const DATA = ["aliases", "devices-398n", "devices-348n-diff"];

function cap(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

class DvSearch extends HTMLElement {
  connectedCallback() {
    this.form = this.querySelector("form");
    this.input = this.querySelector("#dv-q");
    this.out = this.querySelector(".dv-results");
    this.base = new URL(this.dataset.base || "./", document.baseURI);
    this.index = null;
    this.loading = null;
    this.timer = 0;
    this.form.hidden = false;
    const hint = this.querySelector("#dv-q-hint");
    if (hint) hint.hidden = false;
    this.querySelector("[data-nojs]")?.remove();
    this.input.addEventListener("focus", () => this.load(), { once: true });
    this.input.addEventListener("input", () => {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.run(), 150);
    });
    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      this.run();
    });
    for (const chip of this.querySelectorAll(".dv-chip")) {
      chip.addEventListener("click", (e) => {
        e.preventDefault();
        this.input.value = chip.dataset.word;
        this.run();
        this.input.focus({ preventScroll: true });
      });
    }
  }

  load() {
    if (!this.loading) {
      const url = (name) => new URL(`../../data/v1/${name}.json`, import.meta.url);
      const files = DATA.map((n) => fetch(url(n)).then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      }));
      this.loading = Promise.all([import(LIB), ...files])
        .then(([lib, aliases, devices, diff]) => {
          this.lib = lib;
          this.aliases = new Map(aliases.items.map((a) => [a.id, a]));
          this.index = lib.buildIndex({ aliases: aliases.items, devices: devices.items, diff: diff.items });
        })
        .catch(() => {
          this.index = null;
          this.loading = null;
        });
    }
    return this.loading;
  }

  async run() {
    const query = this.input.value;
    if (!query.trim()) {
      this.out.replaceChildren();
      return;
    }
    const slow = setTimeout(() => {
      this.out.textContent = "Ищем";
    }, 300);
    await this.load();
    clearTimeout(slow);
    if (query !== this.input.value) return;
    if (!this.index) {
      this.out.replaceChildren(this.tpl("dv-tpl-error"));
      return;
    }
    this.render(this.lib.search(this.index, query), query.trim());
  }

  tpl(id) {
    return document.getElementById(id).content.firstElementChild.cloneNode(true);
  }

  item(hit) {
    const d = hit.device;
    const li = this.tpl("dv-tpl-result");
    const link = li.querySelector("a");
    link.href = new URL(`devices/${d.code}/`, this.base).pathname;
    li.querySelector(".dv-result__title").textContent = d.nkmi_name;
    li.querySelector(".dv-result__code").textContent = d.code;
    const primary = d.primary_alias ? this.aliases.get(d.primary_alias) : null;
    const sayer = hit.alias && hit.alias.alias !== d.nkmi_name.toLowerCase() ? hit.alias : primary;
    const aliasEl = li.querySelector(".dv-result__alias");
    if (sayer) aliasEl.textContent = ` · так называют: ${sayer.alias}${sayer.verified === false ? " (название не проверено)" : ""}`;
    else aliasEl.remove();
    const now = d.nkmi_name_now ? this.lib.normalize(d.nkmi_name_now) : "";
    if (!now || now === this.lib.normalize(d.nkmi_name)) li.querySelector("[data-renamed]").remove();
    const kind = this.lib.channelKind(d);
    for (const el of li.querySelectorAll("[data-ch]")) if (el.dataset.ch !== kind) el.remove();
    const nv = li.querySelector("[data-unverified]");
    if (d.verified) nv.remove();
    else {
      const why = d.nkmi_status === "mismatch" || d.nkmi_status === "missing" ? d.nkmi_status : "scan";
      for (const el of nv.querySelectorAll("[data-why]")) if (el.dataset.why !== why) el.remove();
    }
    return li;
  }

  list(hits) {
    const ul = document.createElement("ul");
    ul.className = "dv-results__list";
    for (const hit of hits) ul.append(this.item(hit));
    return ul;
  }

  head(text) {
    const p = this.tpl("dv-tpl-head");
    p.textContent = text;
    return p;
  }

  more(result) {
    const p = document.createElement("p");
    p.className = "dv-results__more";
    const a = document.createElement("a");
    a.href = new URL("list/", this.base).pathname;
    a.textContent = "весь перечень";
    p.append(`Показаны первые ${result.items.length} из ${result.total}. Уточните слово или откройте `, a);
    return p;
  }

  render(result, query) {
    const nodes = [];
    if (result.kind === "empty" || result.kind === "none") {
      nodes.push(this.tpl("dv-tpl-empty"));
    } else if (result.kind === "group") {
      const box = this.tpl("dv-tpl-ambiguous");
      box.querySelector("[data-text]").textContent = result.ambiguous
        ? `Слово «${query}» означает разные изделия. Выберите своё`
        : `По слову «${query}» подходит несколько видов изделий. Выберите своё`;
      nodes.push(box);
      for (const g of result.groups) {
        const sec = this.tpl("dv-tpl-group");
        sec.querySelector(".dv-group__title").textContent = cap(g.title);
        sec.querySelector("ul").replaceWith(this.list(g.items));
        nodes.push(sec);
      }
    } else if (result.items.length) {
      const n = result.total || result.items.length;
      nodes.push(this.head(n === 1 ? "Нашлось одно изделие" : `Нашлось изделий: ${n}`));
      nodes.push(this.list(result.items));
    }
    if (result.total > result.items.length) nodes.push(this.more(result));
    for (const gone of result.removed || []) {
      const box = this.tpl("dv-tpl-removed");
      box.querySelector("[data-code]").textContent = gone.code;
      box.querySelector("[data-link]").href = `${new URL("changes/", this.base).pathname}#c-${gone.code}`;
      nodes.push(box);
    }
    if (result.kind === "removed" && !(result.removed || []).length) nodes.push(this.tpl("dv-tpl-empty"));
    this.out.replaceChildren(...nodes);
  }
}

if (!customElements.get("dv-search")) customElements.define("dv-search", DvSearch);
