export const ALLOWED = {
  s: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  doc: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  device: /^\d{6}$/,
  nut: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  region: /^RU-[A-Z]{2,3}$/,
  rule: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  from: /^\d{4}-\d{2}-\d{2}$/,
  norm: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  back: /^[a-z0-9]+(-[a-z0-9]+)*$/,
  new: /^1$/,
  id: /^[a-z0-9]{10}$/,
};

export function xurl(repo, path = "", params = null, { orgRoot = "/", hubRepo = "openpalliative.github.io" } = {}) {
  const base = orgRoot + (repo === hubRepo || repo === "hub" ? "" : `${repo}/`) + String(path).replace(/^\/+/, "");
  if (!params) return base;
  const parts = [];
  for (const [key, value] of Object.entries(params)) {
    if (!(key in ALLOWED)) throw new Error(`Параметр ${key} нельзя передавать в адресе`);
    if (value === null || value === undefined || value === "") continue;
    parts.push(`${key}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `${base}#${parts.join("&")}` : base;
}

export function parseFragment(hash) {
  const text = String(hash || "").replace(/^#/, "");
  if (!text.includes("=")) return null;
  const out = {};
  for (const pair of text.split("&")) {
    const i = pair.indexOf("=");
    if (i <= 0) continue;
    try {
      out[pair.slice(0, i)] = decodeURIComponent(pair.slice(i + 1));
    } catch {}
  }
  return out;
}

function todayUtc() {
  const now = new Date();
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
}

function validFrom(value) {
  const t = Date.parse(`${value}T00:00:00Z`);
  if (Number.isNaN(t)) return false;
  return t <= todayUtc() && t >= todayUtc() - 3 * 366 * 86400000;
}

export function readParams(allowed, validators = {}, { location: loc = globalThis.location, history: hist = globalThis.history } = {}) {
  const raw = parseFragment(loc?.hash);
  if (!raw) return {};
  const out = {};
  for (const key of allowed) {
    const value = raw[key];
    if (value === undefined || !(key in ALLOWED) || !ALLOWED[key].test(value)) continue;
    if (key === "from" && !validFrom(value)) continue;
    if (validators[key] && !validators[key](value)) continue;
    out[key] = value;
  }
  if (hist?.replaceState && loc) hist.replaceState(hist.state, "", loc.pathname + loc.search);
  return out;
}

export function watchParams(allowed, callback, validators = {}, { target = globalThis } = {}) {
  const run = () => {
    const params = readParams(allowed, validators);
    if (Object.keys(params).length) callback(params);
  };
  run();
  target?.addEventListener?.("hashchange", run);
  return () => target?.removeEventListener?.("hashchange", run);
}
