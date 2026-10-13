export const LIMIT = 12;

const SCORE = { exact: 100, prefix: 80, words: 60, name: 40, typo: 30, code: 100, codePrefix: 50 };

export function normalize(text) {
  return String(text ?? "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function words(text) {
  return text ? text.split(" ") : [];
}

export function distanceAtMostOne(a, b) {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  while (i < la && i < lb && a[i] === b[i]) i++;
  if (la === lb) return a.slice(i + 1) === b.slice(i + 1);
  return la > lb ? a.slice(i + 1) === b.slice(i) : a.slice(i) === b.slice(i + 1);
}

export function buildIndex({ devices = [], aliases = [], diff = [] }) {
  const byCode = new Map(devices.map((d) => [d.code, d]));
  const aliasById = new Map(aliases.map((a) => [a.id, a]));
  const aliasEntries = aliases.map((a) => {
    const n = normalize(a.norm_text || a.alias);
    return { alias: a, n, words: words(n) };
  });
  const deviceEntries = devices.map((d) => ({ device: d, words: words(normalize(d.nkmi_name)) }));
  const removed = new Map(diff.filter((x) => x.status === "removed" && x.verified).map((x) => [x.code, x]));
  return { byCode, aliasById, aliasEntries, deviceEntries, removed };
}

function aliasScore(entry, q, qWords) {
  if (entry.n === q) return SCORE.exact;
  if (q.length >= 3 && entry.n.startsWith(q)) return SCORE.prefix;
  if (q.length >= 3 && qWords.every((w) => entry.words.some((aw) => aw.startsWith(w)))) return SCORE.words;
  if (entry.alias.kind === "household" && qWords.length === entry.words.length &&
      qWords.every((w, i) => (w.length >= 6 && entry.words[i].length >= 6 && distanceAtMostOne(w, entry.words[i])) ||
        w === entry.words[i]) &&
      qWords.some((w) => w.length >= 6)) {
    return SCORE.typo;
  }
  return 0;
}

function nameScore(entry, qWords) {
  if (!qWords.length || qWords.some((w) => w.length < 3)) return 0;
  return qWords.every((w) => entry.words.some((dw) => dw.startsWith(w))) ? SCORE.name : 0;
}

function searchCode(index, q) {
  const device = index.byCode.get(q);
  if (device) return { kind: "code", items: [{ code: q, score: SCORE.code, device, alias: null, via: "code" }] };
  const gone = index.removed.get(q);
  if (gone) return { kind: "removed", items: [], removed: [gone] };
  return { kind: "empty", items: [] };
}

function searchCodePrefix(index, q) {
  const items = [];
  for (const device of index.byCode.values()) {
    if (device.code.startsWith(q)) items.push({ code: device.code, score: SCORE.codePrefix, device, alias: null, via: "code" });
  }
  items.sort((a, b) => a.device.order - b.device.order);
  return items.length ? { kind: "results", items: items.slice(0, LIMIT), total: items.length } : { kind: "empty", items: [] };
}

function grouped(items) {
  const groups = [];
  const seen = new Map();
  for (const it of items) {
    const title = it.device.subgroup_title || it.device.group_title;
    if (!seen.has(title)) {
      seen.set(title, { title, items: [] });
      groups.push(seen.get(title));
    }
    seen.get(title).items.push(it);
  }
  return groups;
}

export function search(index, query, { limit = LIMIT } = {}) {
  const q = normalize(query);
  if (!q) return { kind: "none", query: "", items: [] };
  if (/^\d{6}$/.test(q)) return { query: q, ...searchCode(index, q) };
  if (/^\d+$/.test(q)) return { query: q, ...(q.length >= 3 ? searchCodePrefix(index, q) : { kind: "empty", items: [] }) };

  const qWords = words(q);
  const hits = new Map();
  const removed = new Map();
  let top = null;

  const put = (code, score, alias, via, rank = 0) => {
    const device = index.byCode.get(code);
    if (!device) {
      const gone = index.removed.get(code);
      if (gone && score >= SCORE.words) removed.set(code, gone);
      return;
    }
    const prev = hits.get(code);
    if (!prev || prev.score < score) hits.set(code, { code, score, device, alias, via, rank });
  };

  for (const entry of index.aliasEntries) {
    const score = aliasScore(entry, q, qWords);
    if (!score) continue;
    if (!top || score > top.score) top = { alias: entry.alias, score };
    (entry.alias.codes || []).forEach((code, i) => put(code, score, entry.alias, "alias", i));
  }
  for (const entry of index.deviceEntries) {
    const score = nameScore(entry, qWords);
    if (score) put(entry.device.code, score, null, "name");
  }

  let items = [...hits.values()];
  if (items.some((it) => it.score === SCORE.exact)) items = items.filter((it) => it.score > SCORE.typo);
  items.sort((a, b) => b.score - a.score || a.rank - b.rank || a.device.order - b.device.order);
  const total = items.length;
  items = items.slice(0, limit);
  const gone = [...removed.values()];

  if (!items.length) return { kind: gone.length ? "removed" : "empty", query: q, items: [], removed: gone };

  if (top && top.score >= SCORE.prefix) {
    const topItems = items.filter((it) => it.alias === top.alias);
    const subgroups = new Set(topItems.map((it) => it.device.subgroup_title || it.device.group_title));
    if (top.alias.ambiguous || subgroups.size > 1) {
      return { kind: "group", query: q, alias: top.alias, ambiguous: Boolean(top.alias.ambiguous), items, total,
               groups: grouped(items), removed: gone };
    }
  }
  return { kind: "results", query: q, items, total, removed: gone };
}

export function channelKind(device) {
  return (device.channel_ids || []).includes("sfr-pp240") ? "both" : "mo";
}
