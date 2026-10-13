const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
  "сентября", "октября", "ноября", "декабря"];

export function parseIsoDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ""));
  if (!m) return null;
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

export function toIsoDate(date) {
  return date.toISOString().slice(0, 10);
}

export function ruDate(value) {
  const d = value instanceof Date ? value : parseIsoDate(value);
  if (!d) return "";
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${d.getUTCFullYear()}`;
}

export function ruDateLong(value) {
  const d = value instanceof Date ? value : parseIsoDate(value);
  if (!d) return "";
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function plural(n, one, few, many, withNumber = true) {
  const m10 = Math.abs(n) % 10;
  const m100 = Math.abs(n) % 100;
  let word = many;
  if (m10 === 1 && m100 !== 11) word = one;
  else if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) word = few;
  return withNumber ? `${n} ${word}` : word;
}

export function phoneHref(value) {
  let digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 11 && digits[0] === "8") digits = "7" + digits.slice(1);
  return digits.length === 11 ? `tel:+${digits}` : `tel:${digits}`;
}

export function daysBetween(from, to) {
  const a = from instanceof Date ? from : parseIsoDate(from);
  const b = to instanceof Date ? to : parseIsoDate(to);
  if (!a || !b) return NaN;
  return Math.round((Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate()) -
    Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), a.getUTCDate())) / 86400000);
}

export function todayIso(now = new Date()) {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
