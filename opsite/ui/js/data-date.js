import { daysBetween, todayIso } from "./format.js";

class OpDataDate extends HTMLElement {
  connectedCallback() {
    const date = this.getAttribute("datetime");
    const limit = Number(this.getAttribute("stale-after") || 90);
    const age = daysBetween(date, todayIso());
    if (!Number.isFinite(age) || age <= limit || this.querySelector(".op-status")) return;
    this.setAttribute("data-stale", "");
    const status = document.createElement("div");
    status.className = "op-status op-status--stale";
    const tpl = document.getElementById("op-icon-history");
    if (tpl) status.append(tpl.content.cloneNode(true));
    const p = document.createElement("p");
    const word = document.createElement("strong");
    word.className = "op-status__word";
    word.textContent = "Снимок устарел.";
    p.append(word, ` Снимок данных старше ${limit} дней. Сверьте с источником по ссылке`);
    status.append(p);
    this.append(status);
  }
}

if (!customElements.get("op-data-date")) customElements.define("op-data-date", OpDataDate);
