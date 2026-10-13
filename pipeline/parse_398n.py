import argparse
import re
import sys
from pathlib import Path

from pipeline.common import EO_398N, nkmi_status, read_csv, read_yaml, scan_pages, words, write_csv
from pipeline.nkmi import first_change, load_snapshot

HEADER = ["code", "nkmi_name", "name_in_act", "group_no", "group_title", "subgroup_title", "order", "scan_page",
          "fn2", "tsr_2347r", "tsr_source_ref", "verified", "verified_at", "legal_reviewed", "source_ref", "note"]
KEEP = ("tsr_2347r", "tsr_source_ref", "legal_reviewed", "nkmi_name")
PASSES = (("300dpi", EO_398N), ("400dpi", EO_398N + "-400dpi"))
CONFLICT_HEAD = ["page", "pass", "kind", "value", "candidates", "resolution"]
CODE = re.compile(r"(?<!\d)\d{6}(?!\d)")
FRAGMENT = re.compile(r"(?<!\d)\d{3,5}(?!\d)")


class LayoutError(Exception):
    pass


def recover(fragment: str, window: str, kinds: dict[str, str], min_common: int = 2) -> list[str]:
    seen = words(window)
    out = []
    for code, name in kinds.items():
        if code.endswith(fragment) and len(code) == 6:
            common = [w for w in words(name) if len(w) >= 5 and w in seen]
            if len(common) >= min_common:
                out.append(code)
    return sorted(out)


def ocr_conflicts(text: str, page: int, signed: list[str], kinds: dict[str, str]) -> list[dict]:
    found = CODE.findall(text)
    out = []
    for c in found:
        if c not in signed:
            out.append({"page": page, "kind": "ocr_extra", "value": c, "candidates": ""})
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        for frag in FRAGMENT.findall(ln):
            window = " ".join(lines[max(0, i - 4): i + 5])
            cands = recover(frag, window, kinds)
            if cands:
                out.append({"page": page, "kind": "ocr_fragment", "value": frag, "candidates": ";".join(cands)})
    for c in signed:
        if c not in found:
            out.append({"page": page, "kind": "ocr_missing", "value": c, "candidates": ""})
    return out


def build(root: Path) -> tuple[list[dict], list[dict]]:
    layout = read_yaml(root / "data" / "review" / "398n_layout.yaml")
    pages = sorted(scan_pages(root, EO_398N), key=lambda p: int(p["page"]))
    snap = load_snapshot(root) or {"codes": {}}
    kinds = snap["codes"]
    old = {r["code"]: r for r in read_csv(root / "data" / "398n.csv")} if (root / "data" / "398n.csv").is_file() else {}
    page_of, fn2, checked = {}, set(), {}
    for p in pages:
        for c in p["codes"]:
            if c in page_of:
                raise LayoutError(f"код {c} подписан на двух страницах: {page_of[c]} и {p['page']}")
            page_of[c] = int(p["page"])
            checked[c] = p.get("checked_at", "")
        fn2 |= set(p.get("fn2_codes", []))
    seq = [c for p in pages for c in p["codes"]]
    rows, order = [], 0
    layout_seq = []
    for g in layout["groups"]:
        for sg in g["subgroups"]:
            for c in sg["codes"]:
                layout_seq.append(c)
                order += 1
                name_act = layout.get("name_overrides", {}).get(c) or kinds.get(c, "")
                if not name_act:
                    raise LayoutError(f"код {c}: нет имени ни в справочнике, ни в name_overrides")
                status = nkmi_status(name_act, kinds.get(c))
                changed_in = first_change((snap.get("history") or {}).get(c) or [], name_act) if status == "mismatch" else None
                prev = old.get(c, {})
                notes = []
                if changed_in:
                    status = "renamed"
                    notes.append(f"в скане и в справочнике до версии {changed_in} это то же имя; с версии {changed_in} под кодом другой вид")
                if status == "renamed" and not changed_in:
                    notes.append(f"в справочнике {snap.get('version', '')}: {kinds[c]}")
                if status == "mismatch":
                    notes.append(f"под этим кодом в справочнике {snap.get('version', '')} другой вид: {kinds[c]}")
                if status == "missing":
                    notes.append("кода нет в справочнике")
                ok = c in page_of and bool(checked.get(c)) and status in ("present", "renamed")
                rows.append({
                    "code": c,
                    "nkmi_name": prev.get("nkmi_name") or (kinds[c] if status in ("present", "renamed") and not changed_in else name_act),
                    "name_in_act": name_act,
                    "group_no": g["no"], "group_title": g["title"], "subgroup_title": sg["title"],
                    "order": order, "scan_page": page_of.get(c, ""),
                    "fn2": "true" if c in fn2 else "false",
                    "tsr_2347r": prev.get("tsr_2347r") or ("by_fn2" if c in fn2 else "unknown"),
                    "tsr_source_ref": prev.get("tsr_source_ref", ""),
                    "verified": "true" if ok else "false",
                    "verified_at": checked.get(c, "") if ok else "",
                    "legal_reviewed": prev.get("legal_reviewed") or "false",
                    "source_ref": "pravo-398n",
                    "note": "; ".join(notes),
                })
    if layout_seq != seq:
        missing = sorted(set(layout_seq) ^ set(seq))
        raise LayoutError("порядок кодов в 398n_layout.yaml не совпадает со scan_pages.yaml" +
                          (f": разница {missing}" if missing else ": тот же набор, другой порядок"))
    conflicts = []
    ocr_dir = root / "raw" / "ocr" / EO_398N
    for p in pages:
        f = ocr_dir / f"p-{int(p['page']):02d}.txt"
        if f.is_file():
            conflicts += ocr_conflicts(f.read_text(encoding="utf-8"), int(p["page"]), p["codes"], kinds)
    by_code = {r["code"]: r for r in rows}
    for cf in conflicts:
        extra = ""
        if cf["kind"] == "ocr_fragment" and cf["candidates"] in by_code:
            target, extra = by_code[cf["candidates"]], f"OCR прочёл как {cf['value']}, код сверен по изображению страницы"
        elif cf["kind"] == "ocr_missing":
            target, extra = by_code[cf["value"]], "OCR код не прочёл, код сверен по изображению страницы"
        if extra and extra not in target["note"]:
            target["note"] = "; ".join(x for x in (target["note"], extra) if x)
    for r in rows:
        if r["note"].count("OCR") > 1:
            r["note"] = r["note"].replace("; OCR код не прочёл, код сверен по изображению страницы", "")
    return rows, conflicts


def resolutions(root: Path) -> dict:
    p = root / "data" / "review" / "398n_resolutions.yaml"
    return {f"{r['page']}:{r['kind']}:{r['value']}": r["resolution"] for r in read_yaml(p)} if p.is_file() else {}


def all_conflicts(root: Path) -> list[dict]:
    pages = sorted(scan_pages(root, EO_398N), key=lambda p: int(p["page"]))
    kinds = (load_snapshot(root) or {"codes": {}})["codes"]
    res = resolutions(root)
    out = []
    for name, folder in PASSES:
        for p in pages:
            f = root / "raw" / "ocr" / folder / f"p-{int(p['page']):02d}.txt"
            if not f.is_file():
                continue
            for c in ocr_conflicts(f.read_text(encoding="utf-8"), int(p["page"]), p["codes"], kinds):
                c["pass"] = name
                c["resolution"] = res.get(f"{c['page']}:{c['kind']}:{c['value']}", "")
                out.append(c)
    return out


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    argparse.ArgumentParser(prog="python -m pipeline.parse_398n").parse_args(argv)
    root = root_dir()
    rows, conflicts = build(root)
    write_csv(root / "data" / "398n.csv", HEADER, rows)
    both = all_conflicts(root)
    write_csv(root / "_reports" / "398n_conflicts.csv", CONFLICT_HEAD, both)
    write_csv(root / "data" / "review" / "398n_conflicts.csv", CONFLICT_HEAD, both)
    open_ = [c for c in both if not c["resolution"]]
    if open_:
        print(f"неразобранных расхождений: {len(open_)}", file=sys.stderr)
    fn2 = sum(r["fn2"] == "true" for r in rows)
    unv = [r["code"] for r in rows if r["verified"] != "true"]
    print(f"398n.csv: {len(rows)} кодов, со сноской 2: {fn2}, не сверено: {len(unv)} {unv}; расхождений OCR: {len(conflicts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
