import { ruDate } from "./format.js";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function unverifiedChip() {
  const chip = el("span", "op-status op-status--unverified op-status--inline");
  const tpl = document.getElementById("op-icon-circle-help");
  if (tpl) chip.append(tpl.content.cloneNode(true));
  chip.append(el("span", null, "Не проверено"));
  return chip;
}

function lineItem(line) {
  const li = el("li", `op-line${line.verified ? " op-line--verified" : ""}`);
  const a = el("a", "op-line__tel", line.number);
  a.href = `tel:${line.tel}`;
  li.append(a);
  if (!line.verified) li.append(unverifiedChip());
  if (line.what) li.append(el("span", "op-line__what", line.what));
  const meta = [line.is_24x7 ? "Круглосуточно" : line.hours || "", line.source || ""].filter(Boolean).join(". ");
  if (meta) li.append(el("span", "op-line__meta", meta));
  return li;
}

export async function renderLines(box, { iso, name, base, card }) {
  const roles = (box.dataset.roles || "").split(" ").filter(Boolean);
  let data = null;
  if (base) {
    try {
      const res = await fetch(`${base}${iso.toLowerCase()}.json`);
      if (res.ok) data = await res.json();
    } catch {}
  }
  const lines = (data?.lines || []).filter((l) => !roles.length || l.roles?.some((r) => roles.includes(r)));
  lines.sort((a, b) => Number(b.verified) - Number(a.verified));
  const out = [];
  if (lines.length) {
    if (!lines.some((l) => l.verified)) {
      out.push(el("p", "op-region__note", "По вашему региону проверенных номеров пока нет. Номера ниже взяты из открытого источника и ещё не сверены"));
    }
    const list = el("ul", "op-lines");
    list.append(...lines.map(lineItem));
    out.push(list);
    if (data.data_date) out.push(el("p", "op-line__meta", `Данные от ${ruDate(data.data_date)}`));
  }
  const more = el("p", "op-region__more");
  const a = el("a", null, lines.length ? "Все номера региона" : `Номера: ${name || iso}`);
  a.href = card;
  more.append(a);
  if (!lines.length) more.append(" в разделе «Куда звонить»");
  out.push(more);
  box.replaceChildren(...out);
}
