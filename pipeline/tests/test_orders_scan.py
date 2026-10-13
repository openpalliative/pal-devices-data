import datetime as dt
import json
import urllib.parse

from pipeline import net, orders_scan

TEXTS = {
    "a": "РАСПОРЯЖЕНИЕ от 1 ноября 2025 г. № 3122-р Утвердить прилагаемые изменения, которые вносятся в перечень "
         "специализированных продуктов лечебного\nпитания для детей-инвалидов",
    "b": "РАСПОРЯЖЕНИЕ Утвердить схему территориального планирования",
}


def fake_get(url: str, **_):
    net.check_host(url)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    if url.startswith(orders_scan.API):
        if q["DocumentDateFrom"].endswith(".11.2025") and q["Index"] == "1":
            items = [{"eoNumber": "0001202511100019", "number": "3122-р", "documentDate": "2025-11-01T00:00:00",
                      "pagesCount": 2, "id": "a"},
                     {"eoNumber": "0001202511100020", "number": "3123-р", "documentDate": "2025-11-01T00:00:00",
                      "pagesCount": 1, "id": "b"}]
            return json.dumps({"items": items, "pagesTotalCount": 1}).encode()
        return json.dumps({"items": [], "pagesTotalCount": 0}).encode()
    raise net.SourceDown(url)


def test_scan_finds_amendment_and_writes_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(orders_scan, "first_page_text", lambda doc_id, get=None: TEXTS[doc_id])
    out = tmp_path / "scan.tsv"
    rows = orders_scan.scan(dt.date(2025, 10, 30), dt.date(2025, 11, 2), out, workers=1, get=fake_get, log=lambda s: None)
    assert {e: r["hit"] for e, r in rows.items()} == {"0001202511100019": "1", "0001202511100020": "0"}
    summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
    assert summary["listed"] == summary["checked"] == 2 and summary["hits"] == ["0001202511100019"]
    again = orders_scan.scan(dt.date(2025, 10, 30), dt.date(2025, 11, 2), out, workers=1, get=fake_get, log=lambda s: None)
    assert again == rows


def test_month_ranges_cover_period():
    ranges = list(orders_scan.month_ranges(dt.date(2024, 9, 17), dt.date(2024, 11, 3)))
    assert ranges[0] == (dt.date(2024, 9, 17), dt.date(2024, 9, 30))
    assert ranges[-1] == (dt.date(2024, 11, 1), dt.date(2024, 11, 3))
    assert len(ranges) == 3
