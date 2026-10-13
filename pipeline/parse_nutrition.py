import argparse
import re
import sys
from pathlib import Path

from pipeline.common import read_csv, read_yaml, write_csv

HEADER = ["item_no", "name", "form", "edition_added", "edition_removed", "scan_page", "number_verified",
          "text_verified", "verified_at", "note"]
FORMS = sorted(["сухой порошок", "сухая смесь", "сухая инстантная смесь", "жидкий продукт", "жидкая смесь",
                "жидкая стерилизованная смесь", "жидкая форма", "жидкая жировая эмульсия", "мелкий сухой порошок",
                "масло"], key=len, reverse=True)
ITEM = re.compile(r'^\s*"?(\d{1,3})\.\s+(.*)$')
HEAD_WORDS = ("Наименование специализированного", "лечебного питания продукта", "питания", "Форма")


def pages(root: Path) -> list[dict]:
    return read_yaml(root / "data" / "review" / "nutrition_pages.yaml")


def split_items(text: str) -> dict[int, list[str]]:
    out, cur = {}, None
    for line in text.splitlines():
        m = ITEM.match(line)
        if m:
            cur = int(m.group(1))
            out[cur] = [m.group(2)]
        elif cur is not None and line.strip():
            out[cur].append(line.strip())
    return out


def name_and_form(lines: list[str]) -> tuple[str, str]:
    lines = [re.sub(r"\s+", " ", l.replace("\u2014", "-").replace("\u2013", "-")).strip() for l in lines]
    for form in FORMS:
        words = form.split()
        for j in range(len(words), 0, -1):
            head, tail = " ".join(words[:j]), " ".join(words[j:])
            if not lines[0].endswith(" " + head):
                continue
            if tail and not (len(lines) > 1 and (lines[1] == tail or lines[1].endswith(" " + tail))):
                continue
            out = [lines[0][: -len(head)].rstrip()] + lines[1:]
            if tail:
                out[1] = out[1][: -len(tail)].rstrip()
            return " ".join(x for x in out if x).strip(), form
    return " ".join(lines).strip(), ""


def build(root: Path) -> list[dict]:
    editions = read_csv(root / "data" / "nutrition_3551r.csv")
    manual = {int(r["item_no"]): r for r in read_yaml(root / "data" / "review" / "nutrition_items_manual.yaml")}
    rows = []
    for p in pages(root):
        lo, hi = int(p["items_from"]), int(p["items_to"])
        ocr_file = root / "raw" / "ocr" / p["eo"] / f"p-{int(p['page']):02d}.txt"
        blocks = split_items(ocr_file.read_text(encoding="utf-8")) if ocr_file.is_file() else {}
        for n in range(lo, hi + 1):
            if n in manual:
                m = manual[n]
                name, form, text_ok, note = m["name"], m["form"], m["text_verified"] == "true", m.get("note", "")
            elif n in blocks:
                name, form = name_and_form(blocks[n])
                text_ok, note = False, "текст из OCR, с изображением страницы дословно не сверен"
            else:
                name, form, text_ok, note = "", "", False, "OCR не нашёл пункт, текст не перенесён"
            rows.append({"item_no": n, "name": name, "form": form, "edition_added": p["eo"], "edition_removed": "",
                         "scan_page": p["page"], "number_verified": "true", "text_verified": "true" if text_ok else "false",
                         "verified_at": p["checked_at"], "note": note})
    known = {e["id"] for e in editions}
    assert all(r["edition_added"] in known for r in rows)
    return rows


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    argparse.ArgumentParser(prog="python -m pipeline.parse_nutrition").parse_args(argv)
    root = root_dir()
    rows = build(root)
    write_csv(root / "data" / "nutrition_items.csv", HEADER, rows)
    print(f"позиций: {len(rows)}, текст сверен дословно: {sum(r['text_verified'] == 'true' for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
