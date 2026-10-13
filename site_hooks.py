import csv
import datetime as dt
import io
import re
from pathlib import Path

import yaml

TOKEN = re.compile(r"\[\[n:([a-z0-9-]+)\]\]")
DATASET_TITLES = {
    "devices-398n": "Перечень изделий для дома",
    "devices-348n-diff": "Что изменилось по сравнению со старым перечнем",
    "aliases": "Бытовые названия изделий",
    "channels": "Через кого получают",
    "warnings": "Предупреждения на карточках",
    "quotes": "Дословные цитаты норм",
    "nutrition-3551r": "Редакции перечня лечебного питания",
    "entrypoints": "Входы для главной страницы проекта",
}
CSV_FIELDS = ["code", "nkmi_name", "group_no", "group_title", "subgroup_title", "order", "scan_page", "fn2",
              "tsr_2347r", "in_348n", "nkmi_status", "verified", "verified_at", "legal_reviewed"]
CHANNEL_WARNINGS = ("no-fn2-ipra", "fn2-sfr", "tsr-unknown", "sfr-ipra")


def normalize(text: str) -> str:
    text = str(text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w]+|_", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def segments(text) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = str(text or "")
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            out.append(("t", text[pos:m.start()]))
        out.append(("n", m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append(("t", text[pos:]))
    return out


def _items(ctx, name: str) -> list[dict]:
    env = ctx.data.get(name)
    return env["items"] if env else []


def _sources(ctx) -> dict:
    out: dict[str, dict] = {}
    for env in ctx.data.values():
        for s in env.get("source", []):
            out.setdefault(s["id"], {}).update(s)
    path = ctx.root / "data" / "sources.yaml"
    if path.is_file():
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) or []
        for s in raw if isinstance(raw, list) else raw.get("sources", []):
            out.setdefault(s["id"], {}).update({k: v for k, v in s.items() if v != ""})
    return out


def _norms(ctx, sources: dict, fallback: dict) -> dict:
    acts = {a["id"]: a for a in ctx.vendor.get("pal-norms", {}).get("acts", {}).get("items", [])}
    norms: dict[str, dict] = {}
    for nid, title in fallback.items():
        norms[nid] = {"id": nid, "title": title, "url": "", "in_vendor": False, "status": None, "safe": False}
    for s in sources.values():
        nid = s.get("norm_id")
        if nid:
            norms[nid] = {"id": nid, "title": s.get("short_title") or s.get("title") or nid,
                          "url": s.get("url", ""), "in_vendor": False, "status": None, "safe": False}
    for nid, act in acts.items():
        n = norms.setdefault(nid, {"id": nid, "title": nid, "url": "", "in_vendor": False})
        n.update({"in_vendor": True, "status": act.get("status"),
                  "safe": act.get("status") == "in_force" and act.get("verified") is True,
                  "title": act.get("short_title") or act.get("title") or n["title"],
                  "url": act.get("url") or n["url"]})
    return norms


def _channel_open(channels: dict, norms: dict) -> dict:
    out = {}
    for cid, ch in channels.items():
        primary = (ch.get("norm_ids") or [None])[0]
        n = norms.get(primary)
        out[cid] = not (n and n["in_vendor"] and n["status"] != "in_force")
    return out


def _rules(ctx, norms: dict) -> dict:
    out = {}
    for r in ctx.vendor.get("pal-norms", {}).get("deadline-rules", {}).get("items", []):
        ok = r.get("verified") is True and all(norms.get(n, {}).get("safe") for n in r.get("norm_ids", []))
        out[r["id"]] = {**r, "usable": ok}
    return out


def _groups(devices: list[dict]) -> list[dict]:
    groups: dict[int, dict] = {}
    for d in devices:
        g = groups.setdefault(d["group_no"], {"no": d["group_no"], "title": d["group_title"], "items": [],
                                              "subgroups": []})
        g["items"].append(d)
        if not g["subgroups"] or g["subgroups"][-1]["title"] != d["subgroup_title"]:
            g["subgroups"].append({"title": d["subgroup_title"], "items": [],
                                   "anchor": f"sg-{len(g['subgroups']) + 1}"})
        g["subgroups"][-1]["items"].append(d)
    return [groups[k] for k in sorted(groups)]


def _shown(alias: dict) -> bool:
    return alias.get("kind") != "misspelling" and alias.get("search_only") is not True


def _az(aliases: list[dict], by_code: dict, removed: dict, groups: list[dict]) -> list[dict]:
    anchors = {(g["no"], sg["title"]): sg["anchor"] for g in groups for sg in g["subgroups"]}
    letters: dict[str, list] = {}
    for a in sorted(filter(_shown, aliases), key=lambda a: normalize(a["alias"])):
        first = normalize(a["alias"])[:1].upper() or "#"
        targets = []
        for code in a.get("codes", []):
            if code in by_code:
                targets.append({"code": code, "name": by_code[code]["nkmi_name"], "kind": "device"})
            elif code in removed:
                targets.append({"code": code, "name": removed[code]["name_348n"], "kind": "removed"})
        bundles: dict[tuple, dict] = {}
        for t in targets:
            if t["kind"] == "device":
                d = by_code[t["code"]]
                key = (d["group_no"], d["subgroup_title"])
                bundles.setdefault(key, {"group_no": d["group_no"], "title": d["subgroup_title"],
                                         "anchor": anchors.get(key, ""), "count": 0})["count"] += 1
        letters.setdefault(first, []).append({"alias": a, "targets": targets, "bundles": list(bundles.values()),
                                              "old": len([t for t in targets if t["kind"] == "removed"])})
    return [{"letter": k, "items": v} for k, v in letters.items()]


def _quick(content: dict, aliases: list[dict]) -> list[dict]:
    out = []
    for q in (content.get("home") or {}).get("quick", []):
        word = normalize(q["word"])
        shown = [a for a in aliases if _shown(a)]
        hit = next((a for a in shown if normalize(a["alias"]) == word), None) or \
            next((a for a in shown if normalize(a["alias"]).startswith(word)), None)
        out.append({"label": q["label"], "word": q["word"], "alias_id": hit["id"] if hit else ""})
    return out


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _device_views(devices, aliases_by_id, alias_by_code) -> None:
    for d in devices:
        names = [aliases_by_id[a]["alias"] for a in d.get("aliases", []) if a in aliases_by_id and _shown(aliases_by_id[a])]
        names += [a["alias"] for a in alias_by_code.get(d["code"], []) if a["alias"] not in names and _shown(a)]
        primary = aliases_by_id.get(d.get("primary_alias") or "")
        d["_title"] = _cap(primary["alias"]) if primary else d["nkmi_name"]
        d["_other_names"] = [n for n in names if not primary or n != primary["alias"]]
        d["_primary_verified"] = bool(primary and primary.get("verified"))
        known = {a["alias"]: a for a in aliases_by_id.values()}
        d["_unverified_names"] = [n for n in d["_other_names"] if n in known and known[n].get("verified") is not True]
        now = d.get("nkmi_name_now") or ""
        d["_renamed"] = bool(now) and normalize(now) != normalize(d["nkmi_name"])


def _diff_view(diff: list[dict], devices: list[dict]) -> dict:
    old_rows = [x for x in diff if x["status"] in ("kept", "removed")]
    checked = [x for x in diff if x.get("verified")]
    kept = [x for x in checked if x["status"] == "kept"]
    removed = [x for x in checked if x["status"] == "removed"]
    added_codes = {x["code"] for x in checked if x["status"] == "added"}
    added = [d for d in devices if d.get("in_348n") == "no" or d["code"] in added_codes]
    amended = [x for x in diff if x.get("amended_by")]
    return {
        "old_total": len(kept) + len(removed),
        "new_total": len(devices),
        "kept": len(kept),
        "removed": removed,
        "added": added,
        "old_rows": len(old_rows),
        "unchecked": len([x for x in old_rows if not x.get("verified")]),
        "amend_added": len([x for x in amended if x["amended_by"] == "added_1195n"]),
        "amend_removed": len([x for x in amended if x["amended_by"] == "removed_1195n"]),
    }


KIND_WORDS = {"ministry_order": "Приказ", "joint_order": "Приказ", "government_order": "Распоряжение",
              "government_decree": "Постановление", "federal_law": "Федеральный закон"}


GENITIVE = {"Минздрав ": "Минздрава ", "Минтруд ": "Минтруда ", "Правительство ": "Правительства "}


def _acts(ctx) -> dict:
    return {a["id"]: a for a in ctx.vendor.get("pal-norms", {}).get("acts", {}).get("items", [])}


def _requisites(acts: dict, sources: dict) -> dict:
    out = {}
    for nid, a in acts.items():
        if not (a.get("number") and a.get("doc_date")):
            continue
        date = dt.date.fromisoformat(a["doc_date"]).strftime("%d.%m.%Y")
        who = "" if a.get("kind") == "federal_law" else a.get("authority") or ""
        for nom, gen in GENITIVE.items():
            who = who.replace(nom, gen)
        head = " ".join(x for x in (KIND_WORDS.get(a.get("kind", ""), ""), who) if x)
        out[nid] = {"line": f"{head} от {date} № {a['number']}".strip(), "eoNumber": a.get("eoNumber") or "",
                    "url": a.get("url") or "", "title": a.get("title") or "", "verified": a.get("verified") is True}
    for s in sources.values():
        nid = s.get("norm_id")
        if nid and nid not in out and s.get("eoNumber"):
            out[nid] = {"line": re.sub(r"\s*\([^()]*\)$", "", s.get("title", "")), "eoNumber": s["eoNumber"], "url": s.get("url", ""), "title": "",
                        "verified": True}
    return out


def _sources_norm(q: dict) -> str:
    ref = q.get("source_ref") or ""
    return ref[5:] if ref.startswith("norm-") else ""


def _vendor_quotes(ctx, acts: dict, own: dict) -> dict:
    out = dict(own)
    for q in ctx.vendor.get("pal-norms", {}).get("quotes", {}).get("items", []):
        mine = own.get(q["id"])
        if mine and mine.get("text_verbatim") and mine.get("verified") and not q.get("verified"):
            continue
        act = acts.get(q.get("act_id") or "", {})
        out[q["id"]] = {"id": q["id"], "text_verbatim": q.get("text") or "", "point": q.get("point") or "",
                        "scan_page": q.get("page") or "", "eoNumber": act.get("eoNumber") or "",
                        "url": act.get("url") or "", "verified": q.get("verified") is True,
                        "verified_at": q.get("verified_at"), "source_ref": q.get("source_ref") or "",
                        "act_id": q.get("act_id") or "", "from_norms": True,
                        "point_short": (mine or {}).get("point") or "",
                        "law_id": (_sources_norm(mine) if mine else "")}
    return out


def _pending(norms: dict, acts: dict, wanted: set) -> list[dict]:
    out = []
    for nid in sorted(wanted):
        act = acts.get(nid)
        if act and act.get("verified") is True:
            continue
        n = norms.get(nid, {})
        out.append({"id": nid, "title": (act or {}).get("short_title") or n.get("title") or nid,
                    "url": (act or {}).get("url") or n.get("url") or "",
                    "why": "есть в разделе «Нормы и сроки», но ещё не сверен" if act else "ещё не разобран в разделе «Нормы и сроки»"})
    return out


def _until(env: dict) -> str:
    if not env:
        return ""
    return (dt.date.fromisoformat(env["data_date"]) + dt.timedelta(days=int(env["stale_after_days"]))).isoformat()


def context(ctx) -> dict:
    texts = ctx.content.get("texts") or {}
    devices = sorted((dict(d) for d in _items(ctx, "devices-398n")), key=lambda d: d["order"])
    aliases = _items(ctx, "aliases")
    aliases_by_id = {a["id"]: a for a in aliases}
    by_code = {d["code"]: d for d in devices}
    diff = _items(ctx, "devices-348n-diff")
    removed = {x["code"]: x for x in diff if x["status"] == "removed" and x.get("verified")}
    alias_by_code: dict[str, list] = {}
    for a in aliases:
        for c in a.get("codes", []):
            alias_by_code.setdefault(c, []).append(a)
    _device_views(devices, aliases_by_id, alias_by_code)
    sources = _sources(ctx)
    norms = _norms(ctx, sources, texts.get("norm_titles") or {})
    channels = {c["id"]: c for c in _items(ctx, "channels")}
    acts = _acts(ctx)
    quotes = _vendor_quotes(ctx, acts, {q["id"]: q for q in _items(ctx, "quotes")})
    wanted = {s["norm_id"] for s in sources.values() if s.get("norm_id")}
    for ch in channels.values():
        wanted.update(ch.get("norm_ids") or [])
    for w in _items(ctx, "warnings"):
        wanted.update(TOKEN.findall(w.get("text") or ""))
    env = ctx.data.get("devices-398n") or {}
    nutrition = sorted(_items(ctx, "nutrition-3551r"), key=lambda n: n["date"])
    base_nut = next((n for n in nutrition if n["kind"] == "base"), nutrition[0] if nutrition else None)
    return {"dv": {
        "devices": devices,
        "by_code": by_code,
        "groups": _groups(devices),
        "aliases": aliases_by_id,
        "alias_by_code": alias_by_code,
        "az": _az(aliases, by_code, removed, _groups(devices)),
        "quick": _quick(ctx.content, aliases),
        "channels": channels,
        "channel_open": _channel_open(channels, norms),
        "channel_warnings": CHANNEL_WARNINGS,
        "warnings": {w["id"]: w for w in _items(ctx, "warnings")},
        "quotes": quotes,
        "req": _requisites(acts, sources),
        "pending": _pending(norms, acts, wanted),
        "renamed": [d for d in devices if d["_renamed"]],
        "sources": sources,
        "norms": norms,
        "rules": _rules(ctx, norms),
        "vendor_norms": [k for k, v in norms.items() if v["in_vendor"]],
        "diff": _diff_view(diff, devices),
        "removed": removed,
        "nutrition": nutrition,
        "nutrition_by_id": {n["id"]: n for n in nutrition},
        "nutrition_base": base_nut,
        "env": env,
        "check_until": _until(env),
        "nkmi": env.get("nkmi_check") or {},
        "fn2_count": len([d for d in devices if d["fn2"]]),
        "new_count": len([d for d in devices if d.get("in_348n") == "no"]),
        "unverified_count": len([d for d in devices if not d["verified"]]),
        "dataset_titles": DATASET_TITLES,
        "situations": {s["id"]: s for s in ctx.situations},
        "seg": segments,
    }}


def _write_csv(ctx, devices: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_FIELDS)
    for d in devices:
        w.writerow(["true" if d.get(k) is True else "false" if d.get(k) is False else
                    ("" if d.get(k) is None else d.get(k)) for k in CSV_FIELDS])
    dest = Path(ctx.out) / "data" / "v1" / "devices-398n.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(buf.getvalue(), encoding="utf-8")


def pages(ctx):
    dv = ctx.site["dv"]
    if dv["devices"]:
        _write_csv(ctx, dv["devices"])
        from pipeline.export import write_csvs
        write_csvs(Path(ctx.out) / "data" / "v1", ctx.data)
    for d in dv["devices"]:
        yield f"devices/{d['code']}/", "dv/device.html.j2", {"device": d}
    groups = dv["groups"]
    for i, g in enumerate(groups):
        yield f"list/{g['no']}/", "dv/list-group.html.j2", {
            "group": g, "prev_group": groups[i - 1] if i else None,
            "next_group": groups[i + 1] if i + 1 < len(groups) else None}
    for n in dv["nutrition"]:
        yield f"nutrition/{n['id']}/", "dv/nutrition-edition.html.j2", {"edition": n}
