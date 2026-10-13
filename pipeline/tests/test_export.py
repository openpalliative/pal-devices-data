import json
import os

import jsonschema

from pipeline import export


def schemas(root, name):
    env = json.loads((root / "opsite" / "schema" / "envelope.schema.json").read_text(encoding="utf-8"))
    ds = json.loads((root / "data" / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return env, ds


def test_real_export_is_not_fixture(root, monkeypatch):
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    envs = export.datasets(root)
    assert [e["dataset"] for e in envs] == export.NAMES
    for e in envs:
        assert e["data_date"] != "2000-01-01"
        assert all(s["id"] != "fixture" for s in e["source"])


def test_fixture_mode(root, monkeypatch):
    monkeypatch.setenv("OP_FIXTURES", "1")
    envs = export.datasets(root)
    assert all(e["data_date"] == "2000-01-01" for e in envs)


def test_envelopes_match_schemas_and_size(root, monkeypatch):
    for mode in ("0", "1"):
        monkeypatch.setenv("OP_FIXTURES", mode)
        for e in export.datasets(root):
            env, ds = schemas(root, e["dataset"])
            jsonschema.validate(e, env)
            jsonschema.validate(e, ds)
            assert len(json.dumps(e, ensure_ascii=False).encode()) < 1_000_000


def test_device_logic(root, monkeypatch):
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    envs = {e["dataset"]: e for e in export.datasets(root)}
    dev = {i["code"]: i for i in envs["devices-398n"]["items"]}
    assert len(dev) == 170 and sum(i["fn2"] for i in dev.values()) == 29
    assert dev["303260"]["channel_ids"] == ["mo-398n"] and "no-fn2-ipra" in dev["303260"]["warning_ids"]
    assert dev["280360"]["channel_ids"] == ["mo-398n", "sfr-pp240"]
    assert {"fn2-sfr", "ref-repealed-345n"} <= set(dev["280360"]["warning_ids"])
    assert dev["303260"]["primary_alias"] == "otkashlivatel"
    assert dev["207920"]["fn2"] is False
    assert all("ref-repealed-348n" in i["warning_ids"] for i in dev.values())
    for i in dev.values():
        if i["nkmi_status"] in ("mismatch", "missing"):
            assert i["verified"] is False
    check = envs["devices-398n"]["nkmi_check"]
    assert check["present"] + check["missing"] == 170
    diff = envs["devices-348n-diff"]
    c = diff["counts_diff"]
    assert c["new_total"] == 170
    statuses = {i["code"]: i["status"] for i in diff["items"]}
    assert statuses["303260"] == "kept" and statuses["134620"] == "kept"
    assert statuses["104200"] == "removed"
    assert c["kept"] + c["removed"] + c["added"] + c["unverified"] == len(diff["items"])
    eps = [i["id"] for i in envs["entrypoints"]["items"]]
    assert eps == ["search", "nutrition", "channels", "changes", "list"]
    nut = envs["nutrition-3551r"]["items"]
    assert nut[0]["in_force_from"] == "2024-01-01" and nut[1]["in_force_from"] is None


def test_aliases_norm_text(root, monkeypatch):
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    envs = {e["dataset"]: e for e in export.datasets(root)}
    al = {a["id"]: a for a in envs["aliases"]["items"]}
    assert al["pelenki"]["norm_text"] == "пеленки"
    assert al["kreslo-tualet"]["norm_text"] == "кресло туалет"


def test_human_csv_matches_json(root, monkeypatch, tmp_path):
    import csv
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    envs = {e["dataset"]: e for e in export.datasets(root)}
    written = export.write_csvs(tmp_path, envs)
    assert sorted(p.name for p in written) == sorted(f"{n}.csv" for n in export.CSV_TABLES)
    for name, fields in export.CSV_TABLES.items():
        raw = (tmp_path / f"{name}.csv").read_bytes()
        assert raw.startswith("﻿".encode())
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        items = envs[name]["items"]
        assert len(rows) == len(items), name
        for row, it in zip(rows, items):
            assert list(row) == fields
            for f in fields:
                assert row[f] == export.csv_cell(it.get(f)), (name, it["id"], f)
    site = root / "_site" / "data" / "v1"
    if (site / "devices-398n.json").is_file() and (site / "aliases.csv").is_file():
        for name in export.CSV_TABLES:
            built = json.loads((site / f"{name}.json").read_text(encoding="utf-8"))
            rows = list(csv.DictReader((site / f"{name}.csv").read_bytes().decode("utf-8-sig").splitlines()))
            assert [r.get("id") or r.get("code") for r in rows] == [i["id"] for i in built["items"]], name
