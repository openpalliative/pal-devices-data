import argparse
import sys
from pathlib import Path

from pipeline.common import EO_348N, read_yaml, scan_pages, write_csv
from pipeline.nkmi import load_snapshot

HEADER = ["code", "name_in_act", "scan_page", "amended_by", "in_nkmi", "verified", "verified_at", "source_ref", "note"]


def build(root: Path) -> list[dict]:
    pages = sorted(scan_pages(root, EO_348N), key=lambda p: int(p["page"]))
    names = read_yaml(root / "data" / "review" / "348n_names.yaml")
    snap = load_snapshot(root) or {"codes": {}}
    rows, seen = [], {}
    for p in pages:
        for c in p["codes"]:
            if c in seen:
                seen[c]["note"] = f"строка повторяется в акте, также стр. {p['page']}" if not seen[c]["note"] else seen[c]["note"] + f", {p['page']}"
                continue
            row = {"code": c, "name_in_act": names["names"].get(c, ""), "scan_page": p["page"], "amended_by": "",
                   "in_nkmi": "true" if c in snap["codes"] else "false",
                   "verified": "true" if p.get("checked_at") else "false",
                   "verified_at": p.get("checked_at", ""), "source_ref": "pravo-348n", "note": ""}
            seen[c] = row
            rows.append(row)
    for am in names.get("amendments", []):
        for c in am["codes"]:
            row = seen.get(c)
            if row:
                row["amended_by"] = am["kind"]
                continue
            rows.append({"code": c, "name_in_act": am.get("names", {}).get(c, ""), "scan_page": am["page"],
                         "amended_by": am["kind"], "in_nkmi": "true" if c in snap["codes"] else "false",
                         "verified": "true" if am.get("checked_at") else "false",
                         "verified_at": am.get("checked_at", ""), "source_ref": "pravo-1195n", "note": ""})
    return rows


def invalid_codes(root: Path) -> list[dict]:
    return [{"page": p["page"], "value": v} for p in scan_pages(root, EO_348N) for v in p.get("invalid_codes", [])]


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    argparse.ArgumentParser(prog="python -m pipeline.parse_348n").parse_args(argv)
    root = root_dir()
    rows = build(root)
    write_csv(root / "data" / "348n.csv", HEADER, rows)
    print(f"348n.csv: {len(rows)} кодов, из них по поправке: {sum(bool(r['amended_by']) for r in rows)}, "
          f"нет в справочнике: {sum(r['in_nkmi'] == 'false' for r in rows)}, кодов не из шести цифр в акте: {len(invalid_codes(root))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
