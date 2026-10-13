import datetime as dt
import json
import os
from pathlib import Path

from pipeline.common import EO_348N, nkmi_status, norm_text, read_csv, read_yaml, scan_pages
from pipeline.nkmi import first_change, read_descriptions

NAMES = ["devices-398n", "devices-348n-diff", "aliases", "channels", "warnings", "quotes", "nutrition-3551r", "entrypoints"]
REPO = "pal-devices-data"
LICENSE = "CC0-1.0"
STALE = 90
ALIAS_SOURCE = {"id": "openpalliative-aliases", "title": "Бытовые названия изделий: разметка openpalliative по справочнику видов Росздравнадзора и исследованиям проекта"}
REASSIGN_CHECKED = "2026-10-12"
NKMI_ATTRIBUTION = "Открытые данные Росздравнадзора, набор 7710537160-mi_types"


def fixtures(root: Path) -> list[dict]:
    return [json.loads((root / "tests" / "fixtures" / f"{n}.json").read_text(encoding="utf-8")) for n in NAMES]


def datasets(root) -> list[dict]:
    root = Path(root)
    if os.environ.get("OP_FIXTURES") == "1" or not (root / "data" / "398n.csv").is_file():
        return fixtures(root)
    return build_all(root)


def b(v) -> bool:
    return str(v).strip().lower() == "true"


def opt(v):
    return v if v not in ("", None) else None


def as_int(v):
    return int(v) if str(v).strip() else None


def schema_version(name: str) -> str:
    p = Path(__file__).resolve().parent.parent / "data" / "schema" / f"{name}.schema.json"
    return json.loads(p.read_text(encoding="utf-8")).get("x-schema-version", "1.0.0") if p.is_file() else "1.0.0"


def _envelope(name, items, source, meta, **extra):
    from opsite.data import make_envelope
    env = make_envelope(dataset=name, repo=REPO, items=items, source=source, meta=meta,
                        schema_version=schema_version(name), stale_after_days=STALE, license=LICENSE)
    items_out = env.pop("items")
    env.update(extra)
    env["items"] = items_out
    return env


def _source_entry(s: dict) -> dict:
    out = {"id": s["id"], "title": s["title"]}
    for k in ("url", "eoNumber", "retrieved_at", "sha256", "license"):
        if s.get(k):
            out[k] = s[k]
    return out


def load(root: Path) -> dict:
    d = root / "data"
    snap_p, check_p = d / "snapshots" / "nkmi.json", d / "snapshots" / "last_check.json"
    return {
        "meta": read_yaml(d / "meta.yaml"),
        "sources": {s["id"]: s for s in read_yaml(d / "sources.yaml")},
        "rows398": read_csv(d / "398n.csv"),
        "rows348": read_csv(d / "348n.csv") if (d / "348n.csv").is_file() else [],
        "aliases": read_csv(d / "aliases.csv"),
        "channels": read_yaml(d / "channels.yaml"),
        "warnings": read_yaml(d / "warnings.yaml"),
        "quotes": read_yaml(d / "quotes.yaml"),
        "nutrition": read_csv(d / "nutrition_3551r.csv"),
        "snap": json.loads(snap_p.read_text(encoding="utf-8")) if snap_p.is_file() else None,
        "check": json.loads(check_p.read_text(encoding="utf-8")) if check_p.is_file() else None,
    }


def match_when(when: dict, ctx: dict) -> bool:
    if not when:
        return False
    for k, v in when.items():
        if k == "always":
            continue
        want = v if k in ("in_348n", "group_no") else b(v)
        if str(ctx.get(k)) != str(want):
            return False
    return True


def device_items(src: dict) -> tuple[list[dict], dict]:
    snap = src["snap"]
    kinds = snap["codes"] if snap else {}
    rows348 = {r["code"]: r for r in src["rows348"]}
    old_complete = bool(rows348) and all(b(r["verified"]) for r in rows348.values())
    alias_by_code: dict[str, list[str]] = {}
    primary: dict[str, str] = {}
    for a in src["aliases"]:
        for c in a["codes"].split(";"):
            alias_by_code.setdefault(c, []).append(a["id"])
        if a["primary_for"]:
            primary[a["primary_for"]] = a["id"]
    items, missing = [], []
    for r in src["rows398"]:
        code = r["code"]
        now = kinds.get(code) if snap else None
        status = nkmi_status(r["name_in_act"], now) if snap else "unknown"
        history = (snap or {}).get("history", {}).get(code) or []
        changed_in = first_change(history, r["name_in_act"]) if status == "mismatch" else None
        if changed_in:
            status = "renamed"
        if status == "missing":
            missing.append(code)
        fn2 = b(r["fn2"])
        if code in rows348:
            in348 = "yes" if b(rows348[code]["verified"]) else "unknown"
        else:
            in348 = "no" if old_complete else "unknown"
        wctx = {"fn2": fn2, "in_348n": in348, "nkmi_missing": status == "missing", "nkmi_mismatch": status == "mismatch",
                "nkmi_renamed": status == "renamed" and not changed_in,
                "nkmi_reassigned": bool(changed_in), "tsr_unknown": r["tsr_2347r"] == "unknown", "group_no": r["group_no"]}
        warning_ids = [w["id"] for w in src["warnings"] if match_when(w.get("when") or {}, wctx) or b((w.get("when") or {}).get("always", "false"))]
        ok = b(r["verified"]) and status in ("present", "renamed")
        items.append({
            "id": code, "code": code, "nkmi_name": r["nkmi_name"], "name_in_act": r["name_in_act"], "nkmi_name_now": now,
            "group_no": int(r["group_no"]), "group_title": r["group_title"], "subgroup_title": r["subgroup_title"],
            "order": int(r["order"]), "scan_page": int(r["scan_page"]), "fn2": fn2, "tsr_2347r": r["tsr_2347r"],
            "in_348n": in348, "channel_ids": ["mo-398n", "sfr-pp240"] if fn2 else ["mo-398n"],
            "warning_ids": warning_ids, "aliases": alias_by_code.get(code, []), "primary_alias": primary.get(code),
            "nkmi_status": status, "nkmi_changed_in": changed_in, "nkmi_history": history,
            "tsr_source_ref": opt(r["tsr_source_ref"]),
            "legal_reviewed": b(r["legal_reviewed"]), "note": r["note"],
            "verified": ok, "verified_at": opt(r["verified_at"]) if ok else None, "source_ref": r["source_ref"],
        })
    check = src["check"] or {}
    nkmi_check = {"checked_at": check.get("checked_at") or None,
                  "version": (snap or {}).get("version"),
                  "history_versions": (snap or {}).get("history_versions", []),
                  "present": len(items) - len(missing) if snap else 0,
                  "missing": len(missing), "missing_codes": missing,
                  "ok": check.get("ok") if check else None}
    return items, nkmi_check


def diff_items(root: Path, src: dict, devices: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    snap = src["snap"] or {"codes": {}}
    kinds = snap["codes"]
    rows348 = {r["code"]: r for r in src["rows348"]}
    new = {d["code"]: d for d in devices}
    old_complete = bool(rows348) and all(b(r["verified"]) for r in rows348.values())
    items = []
    for code in list(rows348) + [c for c in new if c not in rows348]:
        r = rows348.get(code)
        status = "kept" if r and code in new else "removed" if r else "added"
        if status == "added":
            ok = old_complete and new[code]["verified"]
            vat = new[code]["verified_at"] if ok else None
        else:
            ok = b(r["verified"]) and (status == "removed" or new[code]["verified"])
            vat = opt(r["verified_at"]) if ok else None
        items.append({
            "id": code, "code": code, "status": status,
            "name_348n": opt(r["name_in_act"]) if r else None,
            "nkmi_name_now": kinds.get(code), "retired": code not in kinds,
            "retired_note": retired_note(snap, code) if code not in kinds else None,
            "amended_by": (r or {}).get("amended_by", ""),
            "verified": bool(ok), "verified_at": vat,
            "source_ref": r["source_ref"] if r else "pravo-398n",
        })
    verified = [i for i in items if i["verified"]]
    counts = {"old_total": len(rows348), "new_total": len(devices),
              "kept": sum(i["status"] == "kept" for i in verified),
              "removed": sum(i["status"] == "removed" for i in verified),
              "added": sum(i["status"] == "added" for i in verified),
              "unverified": len(items) - len(verified)}
    notes = []
    for p in scan_pages(root, EO_348N):
        for v in p.get("invalid_codes", []):
            notes.append({"id": f"invalid-{v}", "text": f"На странице {p['page']} скана прежнего перечня код записан как «{v}», это не шесть цифр. Такую строку мы не сопоставляли с кодами"})
    dups = [r for r in src["rows348"] if r.get("note")]
    if dups:
        notes.append({"id": "duplicates", "text": "Некоторые строки в прежнем перечне повторяются: " + ", ".join(r["code"] for r in dups)})
    return items, counts, notes


def month(version: str) -> str:
    return f"{version[6:8]}.{version[4:6]}.{version[:4]}" if len(version) == 8 else f"{version[4:6]}.{version[:4]}"


def ru_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def retired_note(snap: dict, code: str) -> str:
    versions = snap.get("history_versions") or [snap.get("version")] if snap.get("version") else []
    points = (snap.get("history") or {}).get(code) or []
    if versions and points and all(p["name"] is None for p in points):
        return f"нет в версиях справочника от {month(versions[0])} до {month(versions[-1])}"
    if versions:
        return f"нет в версии справочника от {month(versions[-1])}"
    return "нет в справочнике"


def alias_items(src: dict) -> list[dict]:
    out = []
    for a in src["aliases"]:
        codes = [c for c in a["codes"].split(";") if c]
        item = {"id": a["id"], "alias": a["alias"], "kind": a["kind"], "codes": codes,
                "primary_for": opt(a["primary_for"]), "ambiguous": b(a["ambiguous"]),
                "search_only": b(a.get("search_only", "false")), "seen_in": a["seen_in"], "basis": a.get("basis", ""),
                "norm_text": norm_text(a["alias"]), "verified": b(a["verified"]),
                "verified_at": opt(a["verified_at"]) if b(a["verified"]) else None,
                "source_ref": ALIAS_SOURCE["id"]}
        if a.get("reason"):
            item["reason"] = a["reason"]
        out.append(item)
    return out


def channel_items(src: dict) -> list[dict]:
    return [{"id": c["id"], "title": c["title"], "sentence": c["sentence"], "body": c.get("body", ""),
             "norm_ids": c.get("norm_ids", []), "quote_ids": c.get("quote_ids", []),
             "deadline_rule_ids": c.get("deadline_rule_ids", []), "warning_ids": c.get("warning_ids", []),
             "verified": b(c["verified"]),
             "verified_at": opt(c.get("verified_at")), "source_ref": c["source_ref"]} for c in src["channels"]]


def warning_items(src: dict) -> list[dict]:
    out = []
    for w in src["warnings"]:
        when = {}
        for k, v in (w.get("when") or {}).items():
            when[k] = v if k == "in_348n" else int(v) if k == "group_no" else b(v)
        item = {"id": w["id"], "when": when, "kind": w["kind"], "text": w["text"],
                "quote_ids": w.get("quote_ids", []), "verified": b(w["verified"]),
                "verified_at": opt(w.get("verified_at")), "source_ref": w["source_ref"]}
        if w.get("reason"):
            item["reason"] = w["reason"]
        out.append(item)
    return out


def quote_items(src: dict) -> list[dict]:
    out = []
    for q in src["quotes"]:
        ok = b(q["verified"]) and bool(q["text_verbatim"])
        item = {"id": q["id"], "text_verbatim": q["text_verbatim"], "eoNumber": opt(q.get("eoNumber")),
                "point": q["point"], "scan_page": as_int(q.get("scan_page", "")), "lint_allow": q.get("lint_allow", []),
                "url": q.get("url", ""), "verified": ok, "verified_at": opt(q.get("verified_at")) if ok else None,
                "source_ref": q["source_ref"]}
        for k in ("moved_to", "reason"):
            if q.get(k):
                item[k] = q[k]
        out.append(item)
    return out


def nutrition_items(src: dict) -> list[dict]:
    quotes = {q["id"]: q for q in src["quotes"]}
    out = []
    for r in src["nutrition"]:
        s = src["sources"][r["source_ref"]]
        q = quotes.get(r["quote_id"], {})
        fq = quotes.get(r["in_force_quote_id"]) if r.get("in_force_quote_id") else None
        in_force = opt(r["in_force_from"]) if (fq and b(fq["verified"])) else None
        ok = b(r["verified"]) and b(q.get("verified", "false"))
        out.append({"id": r["id"], "number": r["number"], "date": r["date"], "kind": r["kind"], "amends": opt(r["amends"]),
                    "in_force_from": in_force, "pages": int(r["pages"]), "first_sentence": q.get("text_verbatim", ""),
                    "items_from": as_int(r.get("items_from", "")), "items_to": as_int(r.get("items_to", "")),
                    "items_scan_pages": r.get("items_scan_pages", ""),
                    "url": s["url"], "sha256": s.get("sha256", ""), "verified": ok,
                    "verified_at": opt(r["verified_at"]) if ok else None, "source_ref": r["source_ref"]})
    return out


def entrypoint_items(meta: dict) -> list[dict]:
    d = meta["data_date"]
    rows = [
        ("search", "Кто выдаёт изделия", "Найдите аппарат или расходник по тому, как вы его называете, и узнайте, кто его выдаёт", "", ["device", "discharge", "turning-18"], False),
        ("nutrition", "Лечебное питание", "Перечень специализированных продуктов лечебного питания для детей с инвалидностью и его редакции", "nutrition/", ["device"], False),
        ("channels", "Через кого получают изделия", "Медицинская организация или Соцфонд: простыми словами и с основаниями", "channels/", ["device"], False),
        ("changes", "Что изменилось в перечне", "Чем новый перечень изделий для дома отличается от прежнего", "changes/", ["device"], False),
        ("list", "Весь перечень", "Все позиции перечня таблицей и лист «что просить» для печати", "list/", [], True),
    ]
    return [{"id": i, "title": t, "summary": s, "path": p, "audience": ["family"], "situations": sit, "offline": False,
             "printable": pr, "maturity": "beta", "verified": True, "verified_at": d} for i, t, s, p, sit, pr in rows]


def open_questions(src: dict, devices: list[dict]) -> list[dict]:
    qs = [
        {"id": "count-173", "text": (
            f"В новостях называют 173 позиции нового перечня. В официальной публикации на страницах 3-16 мы нашли {len(devices)} строк с кодами, "
            "коды не повторяются. Это подтвердили два независимых прохода сверки 11.10.2026. Официального источника с числом 173 мы не нашли, вопрос открыт")},
        {"id": "tsr-not-checked", "text": (
            "Входит ли позиция в федеральный перечень реабилитационных средств, по тексту этого перечня не сверено. "
            f"У {sum(d['fn2'] for d in devices)} позиций в перечне стоит сноска 2 об обеспечении людей с инвалидностью, это всё, что мы отмечаем. "
            "Текстов правил обеспечения техническими средствами реабилитации и федерального перечня реабилитационных средств "
            f"на портале официального опубликования нет, поиск {ru_date(REASSIGN_CHECKED)}")},
        {"id": "transfer-order", "text": "Действует ли порядок передачи изделий на дом после выхода нового перечня, проверяется в разделе «Нормы и сроки»"},
    ]
    for d in devices:
        if d["nkmi_changed_in"]:
            now = d["nkmi_name_now"]
            qs.append({"id": f"nkmi-reassigned-{d['code']}", "text": (
                f"Код {d['code']}: в перечне и в справочнике Росздравнадзора до версии от {month(d['nkmi_changed_in'])} это «{d['name_in_act']}». "
                f"С версии от {month(d['nkmi_changed_in'])} под этим кодом в справочнике «{now}». "
                + (f"При этом описание вида в справочнике сейчас такое: «{d['_desc'][:170].rsplit(' ', 1)[0].rstrip(',')}...». " if d.get("_desc") else "")
                + f"Поправок к перечню на портале официального опубликования не найдено, проверено {ru_date(REASSIGN_CHECKED)}")})
    mism = [d["code"] for d in devices if d["nkmi_status"] == "mismatch"]
    if mism:
        qs.append({"id": "nkmi-mismatch", "text": "Под кодами " + ", ".join(mism) + " в справочнике Росздравнадзора сейчас записан другой вид изделия, чем в перечне"})
    retired = [r["code"] for r in src["rows348"] if r["in_nkmi"] == "false"]
    if retired:
        qs.append({"id": "old-codes-missing", "text": f"{len(retired)} кодов прежнего перечня нет в текущем справочнике Росздравнадзора: " + ", ".join(retired)})
    return qs


def publish_items(meta: dict) -> bool:
    return str(meta.get("publish_items", "false")).lower() == "true"


def nutrition_position_items(root: Path, src: dict) -> list[dict]:
    p = root / "data" / "nutrition_items.csv"
    if not p.is_file():
        return []
    by_eo = {r["id"]: r for r in src["nutrition"]}
    out = []
    for r in read_csv(p):
        ok = b(r["number_verified"]) and b(r["text_verified"])
        out.append({"id": r["item_no"], "item_no": int(r["item_no"]), "name": r["name"], "form": r["form"],
                    "edition_added": r["edition_added"], "edition_removed": opt(r["edition_removed"]),
                    "scan_page": int(r["scan_page"]), "number_verified": b(r["number_verified"]),
                    "text_verified": b(r["text_verified"]), "verified": ok,
                    "verified_at": opt(r["verified_at"]) if ok else None,
                    "source_ref": by_eo[r["edition_added"]]["source_ref"], "note": r["note"]})
    return out


def build_all(root: Path) -> list[dict]:
    src = load(root)
    meta = {"data_date": src["meta"]["data_date"], "version": src["meta"]["version"]}
    S = src["sources"]
    snap = src["snap"]
    nkmi_src = _source_entry(S["rzn-nkmi"])
    if snap:
        nkmi_src["title"] = f"{NKMI_ATTRIBUTION}, версия {snap['version']}"
        nkmi_src["sha256"] = snap["zip_sha256"]
    devices, nkmi_check = device_items(src)
    descs = read_descriptions(root)
    for d in devices:
        if d["nkmi_changed_in"] and descs.get(d["code"]):
            d["_desc"] = descs[d["code"]]
    diff, counts_diff, notes = diff_items(root, src, devices)
    aliases = alias_items(src)
    src_398 = [_source_entry(S["pravo-398n"]), nkmi_src]
    envs = [
        _envelope("devices-398n", devices, src_398, meta, nkmi_check=nkmi_check,
                  open_questions=open_questions(src, devices)),
        _envelope("devices-348n-diff", diff, [_source_entry(S["pravo-348n"]), _source_entry(S["pravo-1195n"]),
                                              _source_entry(S["pravo-398n"]), nkmi_src], meta,
                  counts_diff=counts_diff, scan_notes=notes),
        _envelope("aliases", aliases, [ALIAS_SOURCE, nkmi_src], meta),
        _envelope("channels", channel_items(src), [_source_entry(S["pravo-208n-243n"]), _source_entry(S["pravo-398n"])], meta),
        _envelope("warnings", warning_items(src), [_source_entry(S[i]) for i in ("pravo-398n", "pravo-208n-243n", "pravo-348n", "rzn-nkmi", "norm-2347-r")], meta),
        _envelope("quotes", quote_items(src), [_source_entry(S[q["source_ref"]]) for q in {q["source_ref"]: q for q in src["quotes"]}.values()], meta),
        _envelope("nutrition-3551r", nutrition_items(src), [_source_entry(S[r["source_ref"]]) for r in src["nutrition"]], meta),
        _envelope("entrypoints", entrypoint_items(meta), [{"id": "openpalliative", "title": "Разделы инструмента «Кто выдаёт изделия»"}], meta),
    ]
    if publish_items(src["meta"]):
        envs.append(_envelope("nutrition-items", nutrition_position_items(root, src),
                              [_source_entry(S[r["source_ref"]]) for r in src["nutrition"]], meta))
    return envs


CSV_TABLES = {
    "devices-398n": ["code", "name_in_act", "nkmi_name", "nkmi_name_now", "group_no", "group_title", "subgroup_title", "order",
                     "scan_page", "fn2", "tsr_2347r", "in_348n", "nkmi_status", "nkmi_changed_in", "verified", "verified_at",
                     "legal_reviewed", "source_ref"],
    "devices-348n-diff": ["code", "status", "name_348n", "nkmi_name_now", "retired", "retired_note", "amended_by",
                          "verified", "verified_at", "source_ref"],
    "aliases": ["id", "alias", "kind", "codes", "primary_for", "ambiguous", "search_only", "seen_in", "basis",
                "verified", "verified_at", "reason"],
    "nutrition-3551r": ["id", "number", "date", "kind", "amends", "in_force_from", "pages", "items_from", "items_to",
                        "first_sentence", "url", "sha256", "verified", "verified_at", "source_ref"],
}
CSV_BOM = "﻿"


def csv_cell(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return ""
    if isinstance(v, list):
        return ";".join(str(x) for x in v)
    return str(v)


def csv_text(env: dict, fields: list[str]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(fields)
    for it in env["items"]:
        w.writerow([csv_cell(it.get(f)) for f in fields])
    return CSV_BOM + buf.getvalue()


def write_csvs(out_dir: Path, envs: dict) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fields in CSV_TABLES.items():
        env = envs.get(name)
        if not env:
            continue
        p = out_dir / f"{name}.csv"
        p.write_text(csv_text(env, fields), encoding="utf-8")
        written.append(p)
    return written
