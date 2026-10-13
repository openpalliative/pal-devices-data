import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from pipeline import net

API = "http://publication.pravo.gov.ru/api/Documents"
PAGE_IMAGE = "http://publication.pravo.gov.ru/GetImage"
ORDER_TYPE = "7ff5b3b5-3757-44f1-bb76-3766cabe3593"
HEAD = ["eoNumber", "number", "document_date", "pages", "hit", "snippet"]
HIT = re.compile(r"лечебн\w*\s+питан|3551\s*-?\s*р")


def month_ranges(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        yield cur, min(end, nxt - dt.timedelta(days=1))
        cur = nxt


def list_orders(start: dt.date, end: dt.date, *, get=net.get) -> list[dict]:
    out = []
    for a, b in month_ranges(start, end):
        index = 1
        while True:
            q = {"Block": "government", "DocumentTypes": ORDER_TYPE, "PeriodType": "range",
                 "DocumentDateFrom": a.strftime("%d.%m.%Y"), "DocumentDateTo": b.strftime("%d.%m.%Y"),
                 "PageSize": 200, "Index": index}
            page = json.loads(get(API + "?" + urllib.parse.urlencode(q)).decode("utf-8"))
            out += page["items"]
            if index >= int(page.get("pagesTotalCount") or 0) or not page["items"]:
                break
            index += 1
    seen, uniq = set(), []
    for it in out:
        if it["eoNumber"] not in seen:
            seen.add(it["eoNumber"])
            uniq.append(it)
    return uniq


def first_page_text(doc_id: str, *, get=net.get) -> str:
    png = get(PAGE_IMAGE + "?" + urllib.parse.urlencode({"documentId": doc_id, "pageNumber": 1}))
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "rus", "--psm", "6"], input=png,
                       capture_output=True, check=True)
    return r.stdout.decode("utf-8", "replace")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е"))


def check(item: dict, *, get=net.get) -> dict:
    text = clean(first_page_text(item["id"], get=get))
    m = HIT.search(text)
    return {"eoNumber": item["eoNumber"], "number": item["number"], "document_date": item["documentDate"][:10],
            "pages": str(item.get("pagesCount") or ""), "hit": "1" if m else "0",
            "snippet": text[max(0, m.start() - 160):m.end() + 160].replace("\t", " ") if m else ""}


def read_tsv(path: Path) -> dict:
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    return {r["eoNumber"]: r for r in (dict(zip(HEAD, l.split("\t"))) for l in lines[1:] if l.strip())}


def write_tsv(path: Path, rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["\t".join(HEAD)] + ["\t".join(rows[k].get(h, "") for h in HEAD)
                                for k in sorted(rows, key=lambda e: (rows[e]["document_date"], e))]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def write_summary(path: Path, *, start, end, listed: list[str], rows: dict, failed: list[str]) -> dict:
    checked = [e for e in listed if e in rows]
    summary = {"period": f"{start}..{end}", "checked_at": dt.date.today().isoformat(), "listed": len(listed),
               "checked": len(checked), "failed": sorted(failed), "hits": sorted(e for e in checked if rows[e]["hit"] == "1"),
               "query": "api/Documents Block=government DocumentTypes=распоряжение PeriodType=range по месяцам, "
                        "первая страница каждого акта (GetImage) через tesseract rus psm 6, поиск «лечебн… питан» и «3551-р»"}
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


def scan(start: dt.date, end: dt.date, out: Path, *, workers: int = 3, get=net.get, log=print) -> dict:
    rows = read_tsv(out)
    listed = list_orders(start, end, get=get)
    failed = []
    items = [i for i in listed if i["eoNumber"] not in rows]
    log(f"распоряжений к проверке: {len(items)}, уже проверено: {len(rows)}")
    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check, i, get=get): i for i in items}
        for f in cf.as_completed(futs):
            try:
                r = f.result()
            except (net.SourceDown, subprocess.CalledProcessError) as e:
                log(f"{futs[f]['eoNumber']}: не удалось, {e}")
                failed.append(futs[f]["eoNumber"])
                continue
            rows[r["eoNumber"]] = r
            done += 1
            if r["hit"] == "1":
                log(f"НАЙДЕНО {r['eoNumber']} {r['number']} {r['document_date']}: {r['snippet'][:200]}")
            if done % 100 == 0:
                write_tsv(out, rows)
                log(f"проверено {done} из {len(items)}")
    write_tsv(out, rows)
    write_summary(out.with_suffix(".summary.json"), start=start, end=end, listed=[i["eoNumber"] for i in listed],
                  rows=rows, failed=failed)
    return rows


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    ap = argparse.ArgumentParser(prog="python -m pipeline.orders_scan")
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args(argv)
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    out = a.out or root_dir() / "raw" / "orders_scan" / f"government-orders-{a.start}-{a.end}.tsv"
    rows = scan(start, end, out, workers=a.workers, log=lambda s: print(s, flush=True))
    hits = [r for r in rows.values() if r["hit"] == "1"]
    print(f"проверено {len(rows)}, совпадений {len(hits)}")
    for r in hits:
        print(f"  {r['eoNumber']} {r['number']} {r['document_date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
