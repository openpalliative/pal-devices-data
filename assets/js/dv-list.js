import { readParams } from "../../ui/js/xparams.js";
import { showBack } from "./dv-back.js";

const OLD = { yes: "было", no: "новое" };

function norm(text) {
  return String(text).toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function plural(n, one, few, many) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

class DvList extends HTMLElement {
  async connectedCallback() {
    this.picked = new Set();
    this.rows = [];
    this.byCode = new Map();
    this.loading = this.querySelector("[data-loading]");
    this.loading.hidden = false;
    let devices;
    try {
      const res = await fetch(new URL("../../data/v1/devices-398n.json", import.meta.url));
      if (!res.ok) throw new Error(String(res.status));
      devices = (await res.json()).items;
    } catch {
      this.loading.textContent = "Не получилось загрузить перечень. Откройте таблицы по группам по ссылкам ниже";
      return;
    }
    this.loading.remove();
    this.build(devices);
    this.wire();
    this.takeParams(true);
    window.addEventListener("hashchange", () => this.takeParams(false));
    this.filter();
    this.update();
    this.dataset.ready = "";
  }

  takeParams(first) {
    const known = (code) => this.byCode.has(code);
    const params = readParams(["device", "back"], { device: known });
    if (first) showBack(params.back);
    if (!params.device) return;
    this.toggle(params.device, true);
    const row = this.byCode.get(params.device);
    row.hidden = false;
    row.closest("details").hidden = false;
    row.closest("details").open = true;
    row.scrollIntoView({ block: "center" });
    row.querySelector("input[data-pick]").focus({ preventScroll: true });
    if (!first) this.update();
  }

  build(devices) {
    const tpl = document.getElementById("dv-tpl-row").content.firstElementChild;
    const base = new URL("../../", import.meta.url);
    const sorted = [...devices].sort((a, b) => a.order - b.order);
    const bodies = new Map();
    const head = document.getElementById("dv-tpl-thead").content.firstElementChild;
    for (const group of this.querySelectorAll("details[data-group]")) {
      const body = group.querySelector("tbody");
      body.before(head.cloneNode(true));
      bodies.set(Number(group.dataset.group), body);
      group.querySelector("[data-nojs]")?.remove();
      group.querySelector(".op-table-wrap").hidden = false;
    }
    for (const d of sorted) {
      const body = bodies.get(d.group_no);
      if (!body) continue;
      const tr = tpl.cloneNode(true);
      tr.id = `r${d.code}`;
      tr.dataset.c = d.code;
      const link = tr.querySelector("a");
      link.href = new URL(`devices/${d.code}/`, base).pathname;
      link.textContent = d.nkmi_name;
      tr.querySelector("[data-name]").textContent = d.nkmi_name;
      tr.querySelector("input").value = d.code;
      tr.querySelector(".dv-k").textContent = d.code;
      const both = d.channel_ids.includes("sfr-pp240");
      const ch = tr.querySelector(".dv-c");
      ch.textContent = both ? "Медорганизация или Соцфонд" : "Медорганизация";
      if (both) ch.classList.add("dv-c--2");
      tr.querySelector(".dv-o").textContent = OLD[d.in_348n] || "не проверено";
      if (!d.verified) tr.querySelector("[data-u]").hidden = false;
      tr._d = d;
      tr._text = norm(`${d.nkmi_name} ${d.code}`);
      body.append(tr);
      this.rows.push(tr);
      this.byCode.set(d.code, tr);
    }
  }

  wire() {
    this.find = this.querySelector("#dv-find");
    this.onlyFn2 = this.querySelector("#dv-only-fn2");
    this.onlyNew = this.querySelector("#dv-only-new");
    this.count = this.querySelector("#dv-count");
    this.tray = this.querySelector(".dv-tray");
    this.trayCount = this.tray.querySelector("[data-count]");
    this.clear = this.tray.querySelector("[data-clear]");
    this.sheet = this.querySelector("[data-sheet]");
    this.none = this.querySelector("[data-none]");
    this.querySelector(".dv-filters").hidden = false;
    this.tray.hidden = false;
    let timer = 0;
    this.find.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => this.filter(), 120);
    });
    this.onlyFn2.addEventListener("change", () => this.filter());
    this.onlyNew.addEventListener("change", () => this.filter());
    this.clear.addEventListener("click", () => {
      for (const code of [...this.picked]) this.toggle(code, false);
      this.update();
    });
    this.addEventListener("change", (e) => {
      const box = e.target.closest("input[data-pick]");
      if (!box) return;
      this.toggle(box.value, box.checked);
      this.update();
    });
  }

  toggle(code, on) {
    const row = this.byCode.get(code);
    if (!row) return;
    row.querySelector("input[data-pick]").checked = on;
    row.classList.toggle("is-picked", on);
    if (on) this.picked.add(code);
    else this.picked.delete(code);
  }

  filter() {
    const words = norm(this.find.value).split(" ").filter(Boolean);
    let shown = 0;
    for (const row of this.rows) {
      const d = row._d;
      const ok = words.every((w) => row._text.includes(w)) &&
        (!this.onlyFn2.checked || d.fn2) &&
        (!this.onlyNew.checked || d.in_348n === "no");
      row.hidden = !ok;
      shown += ok;
    }
    for (const group of this.querySelectorAll("details[data-group]")) {
      group.hidden = !group.querySelector("tbody tr:not([hidden])");
    }
    const total = this.rows.length;
    this.count.textContent = shown === total
      ? `Показаны все ${total} ${plural(total, "позиция", "позиции", "позиций")}`
      : `Показано ${shown} из ${total}`;
    this.none.hidden = shown > 0;
  }

  update() {
    const n = this.picked.size;
    this.trayCount.textContent = n
      ? `В листе ${n} ${plural(n, "изделие", "изделия", "изделий")}`
      : "Отметьте изделия в таблице, и мы соберём лист для печати";
    this.clear.disabled = n === 0;
    this.tray.classList.toggle("is-active", n > 0);
    const printBtn = this.tray.querySelector("op-print button");
    if (printBtn) printBtn.disabled = n === 0;
    document.documentElement.classList.toggle("dv-has-sheet", n > 0);
    this.renderSheet();
  }

  renderSheet() {
    const items = [];
    for (const row of this.rows) {
      if (!this.picked.has(row.dataset.c)) continue;
      const d = row._d;
      if (!d.verified) {
        const skip = document.getElementById("dv-tpl-sheet-skip").content.firstElementChild.cloneNode(true);
        skip.querySelector("[data-name]").textContent = `${d.nkmi_name}, код ${d.code}`;
        items.push(skip);
        continue;
      }
      const el = document.getElementById("dv-tpl-sheet").content.firstElementChild.cloneNode(true);
      el.querySelector("[data-name]").textContent = d.nkmi_name;
      el.querySelector("[data-code]").textContent = d.code;
      el.querySelector("[data-page]").textContent = d.scan_page;
      const kind = d.channel_ids.includes("sfr-pp240") ? "both" : "mo";
      for (const p of el.querySelectorAll("[data-ch]")) if (p.dataset.ch !== kind) p.remove();
      items.push(el);
    }
    this.sheet.replaceChildren(...items);
  }
}

if (!customElements.get("dv-list")) customElements.define("dv-list", DvList);
