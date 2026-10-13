import io
import zipfile

from pipeline import net, nkmi, watch
from pipeline.common import write_csv
from pipeline.tests.test_watch import HEADER, row

GOOD = "Средство гемостатическое неорганического происхождения"
OTHER = "Система управления/получения видеоизображений для эндоскопа"
VERSIONS = {
    "20260601": {"259910": GOOD, "303260": "Инсуффлятор-аспиратор"},
    "20260701": {"259910": OTHER, "303260": "Инсуффлятор-аспиратор"},
    "20260801": {"259910": OTHER, "303260": "Инсуффлятор-аспиратор"},
}


def xml(kinds: dict) -> bytes:
    body = "".join(f"<classificator><code>{c}</code><name>{n}</name><description>d</description></classificator>"
                   for c, n in kinds.items())
    return f'<?xml version="1.0" encoding="utf-8"?><classificator_list>{body}</classificator_list>'.encode()


def zipped(kinds: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data.xml", xml(kinds))
    return buf.getvalue()


def meta(versions) -> bytes:
    base = "https://roszdravnadzor.gov.ru/opendata/7710537160-mi_types/"
    lines = ["property,value", "modified,20260801", f"structure-20180615,{base}structure-20180615.xsd"]
    lines += [f"data-{v}-structure-20180615,{base}data-{v}-structure-20180615.zip" for v in versions]
    return "\n".join(lines).encode()


def getter(versions):
    def get(url: str, **_):
        net.check_host(url)
        if url.endswith("meta.csv"):
            return meta(versions)
        if url.endswith(".xsd"):
            return b"<xsd/>"
        for v in versions:
            if f"data-{v}-" in url:
                return zipped(VERSIONS[v])
        raise net.SourceDown(url)
    return get


def test_history_finds_first_change():
    hist = nkmi.build_history({v: k for v, k in VERSIONS.items()}, ["259910", "303260"])
    assert hist == {"259910": [{"version": "20260601", "name": GOOD}, {"version": "20260701", "name": OTHER}]}
    assert nkmi.first_change(hist["259910"], GOOD) == "20260701"
    assert nkmi.first_change(hist["259910"], OTHER) is None


def test_refresh_with_history_writes_snapshot(tmp_path):
    (tmp_path / "data").mkdir()
    write_csv(tmp_path / "data" / "398n.csv", HEADER, [row("259910", GOOD), row("303260", "Инсуффлятор-аспиратор")])
    snap = nkmi.refresh(tmp_path, get=getter(list(VERSIONS)), with_history=True)
    assert snap["version"] == "20260801"
    assert snap["history_versions"] == sorted(VERSIONS)
    assert [p["version"] for p in snap["history"]["259910"]] == ["20260601", "20260701"]
    assert "303260" not in snap["history"]


def test_watch_reports_code_changed_across_three_versions(tmp_path):
    (tmp_path / "data").mkdir()
    write_csv(tmp_path / "data" / "398n.csv", HEADER, [row("259910", GOOD), row("303260", "Инсуффлятор-аспиратор")])
    kinds = []
    for i in range(1, 4):
        rep = watch.run(tmp_path, get=getter(list(VERSIONS)[:i]), reports=tmp_path / "_reports")
        kinds.append(sorted((r["kind"], r.get("code", "")) for r in rep["review"]))
    assert kinds[0] == []
    assert kinds[1] == [("code_changed", "259910")]
    assert kinds[2] == []
    snap = nkmi.load_snapshot(tmp_path)
    assert snap["history_versions"] == sorted(VERSIONS)
    assert snap["history"]["259910"][-1] == {"version": "20260701", "name": OTHER}
