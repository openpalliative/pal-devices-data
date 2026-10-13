import { todayIso } from "./format.js";

const part = (fs, p) => fs.querySelector(`[data-part="${p}"]`)?.value.trim() ?? "";

function limit(value) {
  if (!value) return null;
  return value === "today" ? todayIso() : value;
}

export function checkDate3(d, m, y, { min = null, max = null } = {}) {
  if (!d && !m && !y) return { iso: null, error: "Укажите дату: день, месяц и год" };
  const dn = Number(d);
  const mn = Number(m);
  const yn = Number(y);
  if (!/^\d{1,2}$/.test(d) || !mn || !/^\d{4}$/.test(y) || !dn) {
    return { iso: null, error: "Заполните день, месяц и год. Год четырьмя цифрами, например 2026" };
  }
  const dt = new Date(Date.UTC(yn, mn - 1, dn));
  if (dt.getUTCFullYear() !== yn || dt.getUTCMonth() !== mn - 1 || dt.getUTCDate() !== dn) {
    return { iso: null, error: "Такой даты нет. Проверьте день и месяц" };
  }
  const iso = dt.toISOString().slice(0, 10);
  const hi = limit(max);
  const lo = limit(min);
  if (hi && iso > hi) {
    return { iso: null, error: max === "today" ? "Дата не может быть позже сегодняшней" : "Дата слишком поздняя. Проверьте год" };
  }
  if (lo && iso < lo) return { iso: null, error: "Дата слишком давняя. Проверьте год" };
  return { iso, error: "" };
}

export function showDate3Error(fs, error) {
  const box = fs.querySelector(".op-field__error");
  if (box) {
    box.hidden = !error;
    const slot = box.querySelector("[data-error]");
    if (slot) slot.textContent = error;
  }
  for (const input of fs.querySelectorAll("input, select")) {
    if (error) {
      input.setAttribute("aria-invalid", "true");
      if (box?.id) input.setAttribute("aria-describedby", box.id);
    } else {
      input.removeAttribute("aria-invalid");
    }
  }
}

export function readDate3(fs, options = {}) {
  const result = checkDate3(part(fs, "d"), part(fs, "m"), part(fs, "y"), {
    min: options.min ?? fs.dataset.min ?? null,
    max: options.max ?? fs.dataset.max ?? null,
  });
  showDate3Error(fs, result.error);
  return result;
}

export function setDate3(fs, iso) {
  const [y, m, d] = iso ? String(iso).slice(0, 10).split("-") : ["", "", ""];
  fs.querySelector('[data-part="d"]').value = d ? String(Number(d)) : "";
  fs.querySelector('[data-part="m"]').value = m ? String(Number(m)) : "";
  fs.querySelector('[data-part="y"]').value = y || "";
}

export function wireDates(root = document) {
  for (const fs of root.querySelectorAll(".op-date[data-date3]")) {
    const quick = fs.querySelector(".op-date__quick");
    if (!quick || quick.dataset.wired) continue;
    quick.dataset.wired = "1";
    quick.hidden = false;
    quick.addEventListener("click", (event) => {
      const button = event.target.closest("[data-quick]");
      if (!button) return;
      const t = new Date(`${todayIso()}T00:00:00Z`);
      t.setUTCDate(t.getUTCDate() + Number(button.dataset.quick));
      setDate3(fs, t.toISOString().slice(0, 10));
      showDate3Error(fs, "");
    });
  }
}

if (typeof document !== "undefined") wireDates();
