import json
import shutil

import pytest

from pipeline import net, nkmi, watch
from pipeline.common import read_csv, write_csv

HEADER = ["code", "nkmi_name", "name_in_act", "group_no", "group_title", "subgroup_title", "order", "scan_page",
          "fn2", "tsr_2347r", "verified", "verified_at", "legal_reviewed", "source_ref", "note"]


def make_root(tmp_path, rows):
    (tmp_path / "data").mkdir()
    write_csv(tmp_path / "data" / "398n.csv", HEADER, rows)
    return tmp_path


def row(code, name):
    return {"code": code, "nkmi_name": name, "name_in_act": name, "group_no": "1", "order": "1", "scan_page": "3",
            "fn2": "false", "tsr_2347r": "unknown", "verified": "true", "legal_reviewed": "false", "source_ref": "pravo-398n"}


def down(url, **_):
    raise net.SourceDown(url)


def test_fixture_run_reports_removed_code(root):
    report = watch.run_fixtures(root)
    assert any(f["path"] == "data/snapshots/nkmi.json" for f in report["facts"])
    removed = [r for r in report["review"] if r["kind"] == "code_removed"]
    assert [r["code"] for r in removed] == ["999990"]
    saved = json.loads((root / "_reports" / "watch.json").read_text(encoding="utf-8"))
    assert saved["review"] == report["review"]
    assert not (root / "_reports" / "watch-fixtures" / "data" / "snapshots" / "nkmi.json").read_text() == \
        (root / "data" / "snapshots" / "nkmi.json").read_text()


def test_new_structure_is_format_change(tmp_path):
    r = make_root(tmp_path, [row("303260", "Инсуффлятор-аспиратор")])
    rep = watch.run(r, get=watch.fixture_get("meta_newstructure.csv"), reports=tmp_path / "_reports")
    assert [x["kind"] for x in rep["review"]] == ["format_changed"]
    assert not (tmp_path / "data" / "snapshots" / "nkmi.json").exists()


def test_three_failures_open_review(tmp_path):
    r = make_root(tmp_path, [row("303260", "Инсуффлятор-аспиратор")])
    kinds = []
    for _ in range(3):
        rep = watch.run(r, get=down, reports=tmp_path / "_reports")
        kinds.append([x["kind"] for x in rep["review"]])
    assert kinds == [[], [], ["source_down"]]
    check = json.loads((tmp_path / "data" / "snapshots" / "last_check.json").read_text(encoding="utf-8"))
    assert check["consecutive_failures"] == 3 and check["ok"] is False


def test_same_version_only_updates_check_and_rename_is_proposal(tmp_path):
    r = make_root(tmp_path, [row("303260", "Инсуффлятор-аспиратор"), row("113810", "Концентратор кислорода мобильный/портативный")])
    first = watch.run(r, get=watch.fixture_get(), reports=tmp_path / "_reports")
    assert {f["path"] for f in first["facts"]} == {"data/snapshots/nkmi.json", "data/snapshots/last_check.json"}
    assert [p["code"] for p in first["proposals"]] == ["113810"]
    second = watch.run(r, get=watch.fixture_get(), reports=tmp_path / "_reports")
    assert [f["path"] for f in second["facts"]] == ["data/snapshots/last_check.json"]
    n = watch.apply_proposals(r, tmp_path / "_reports" / "watch.json")
    assert n == 1
    assert {x["code"]: x["nkmi_name"] for x in read_csv(r / "data" / "398n.csv")}["113810"] == "Концентратор кислорода переносной/портативный"


def test_changed_xsd_is_format_change(tmp_path):
    r = make_root(tmp_path, [row("303260", "Инсуффлятор-аспиратор")])
    watch.run(r, get=watch.fixture_get(), reports=tmp_path / "_reports")
    snap = nkmi.load_snapshot(r)
    snap["version"], snap["xsd_sha256"] = "20260901", "0" * 64
    nkmi.write_json(nkmi.snapshot_path(r), snap)
    rep = watch.run(r, get=watch.fixture_get(), reports=tmp_path / "_reports")
    assert [x["kind"] for x in rep["review"]] == ["format_changed"]
    assert nkmi.load_snapshot(r)["version"] == "20260901"


def test_open_issues_skips_duplicates(tmp_path):
    report = {"review": [watch.review("code_removed", "Кода 1 нет", "b", "s", code="100000"),
                         watch.review("code_removed", "Кода 2 нет", "b", "s", code="100010")]}
    p = tmp_path / "w.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    calls = []

    class R:
        def __init__(self, out):
            self.stdout = out

    def runner(cmd, **_):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return R('[{"number": 5}]' if report["review"][0]["title"].rsplit(" ", 1)[-1] in cmd[6] else "[]")
        return R("")
    assert report["review"][0]["title"] != report["review"][1]["title"]
    assert watch.open_issues(p, runner=runner) == 1
    assert sum(c[:3] == ["gh", "issue", "create"] for c in calls) == 1


def test_stale_check(tmp_path):
    (tmp_path / "data" / "snapshots").mkdir(parents=True)
    (tmp_path / "data" / "snapshots" / "last_check.json").write_text('{"checked_at": "2026-09-01"}', encoding="utf-8")
    out = tmp_path / "s.json"
    assert watch.stale_check(tmp_path, 21, out, today="2026-10-11") is True
    assert json.loads(out.read_text(encoding="utf-8"))["review"][0]["kind"] == "watch_stale"
    assert watch.stale_check(tmp_path, 60, out, today="2026-10-11") is False


def test_host_guard():
    with pytest.raises(net.HostNotAllowed):
        net.check_host("https://sfr.gov.ru/x")
    with pytest.raises(net.HostNotAllowed):
        watch.fixture_get()("https://example.org/meta.csv")


def test_retries_then_gives_up(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise net.urllib.error.URLError("нет сети")
    monkeypatch.setattr(net.urllib.request, "urlopen", boom)
    with pytest.raises(net.SourceDown):
        net.get("https://roszdravnadzor.gov.ru/x", pauses=(0, 0, 0, 0), sleep=lambda s: None)
    assert len(calls) == 5
