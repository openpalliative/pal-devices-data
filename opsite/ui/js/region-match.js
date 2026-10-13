export function normalize(value) {
  return String(value ?? "").toLowerCase().replaceAll("ё", "е").replace(/[^a-zа-я0-9]+/g, " ").trim();
}

export function scoreRegion(query, region) {
  const q = normalize(query);
  if (!q) return 0;
  const all = [region.name, region.capital, ...(region.aliases || []), region.id?.slice(3)]
    .filter(Boolean).map(normalize);
  if (all.includes(q)) return 3;
  const hay = all.flatMap((t) => t.split(" "));
  if (!q.split(" ").every((w) => hay.some((h) => h.startsWith(w)))) return all.some((t) => t.includes(q)) ? 0.5 : 0;
  return all.some((t) => t.startsWith(q)) ? 2 : 1;
}

export function matchRegion(query, regions) {
  const scored = regions.map((r, i) => ({ r, score: scoreRegion(query, r), i }));
  const floor = scored.some((x) => x.score >= 1) ? 1 : 0.5;
  return scored.filter((x) => x.score >= floor).sort((a, b) => b.score - a.score || a.i - b.i).map((x) => x.r);
}
