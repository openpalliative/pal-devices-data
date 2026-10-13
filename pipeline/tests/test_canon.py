import json
import re

import yaml

from pipeline.common import EO_348N, EO_398N, read_csv, read_yaml, scan_pages

MANDATORY_ALIASES = {
    "otkashlivatel": {"303260"},
    "kislorodnik": {"113810", "191160"},
    "kislorod": {"113810", "191160"},
    "pampersy": {"280360", "233160"},
    "podguzniki": {"280360", "233160"},
}


def rows398(root):
    return read_csv(root / "data" / "398n.csv")


def test_counts_follow_signed_pages(root):
    pages = scan_pages(root, EO_398N)
    codes = [c for p in pages for c in p["codes"]]
    fn2 = [c for p in pages for c in p.get("fn2_codes", [])]
    rows = rows398(root)
    assert len(rows) == len(codes)
    assert sum(r["fn2"] == "true" for r in rows) == len(fn2)
    assert {r["code"] for r in rows if r["fn2"] == "true"} == set(fn2)
    assert all(p.get("checked_at") for p in pages)


def test_golden_edition(root):
    golden = yaml.safe_load((root / "tests" / "golden" / "398n.yaml").read_text(encoding="utf-8"))
    rows = rows398(root)
    by = {r["code"]: r for r in rows}
    assert len(rows) == golden["codes_total"] == 170
    assert sum(r["fn2"] == "true" for r in rows) == golden["fn2_total"] == 29
    assert {r["code"] for r in rows if r["fn2"] == "true"} == set(golden["fn2_codes"])
    assert set(golden["required_codes"]) <= set(by)
    assert all(by[c]["fn2"] == "false" for c in golden["not_fn2_codes"])
    assert len({r["group_no"] for r in rows}) == golden["groups_total"]
    counts = {}
    for r in rows:
        counts[r["group_no"]] = counts.get(r["group_no"], 0) + 1
    assert counts == {k: v for k, v in golden["group_counts"].items()}


def test_codes_unique_and_complete(root):
    rows = rows398(root)
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"\d{6}", c) for c in codes)
    assert all(r["scan_page"].isdigit() and 3 <= int(r["scan_page"]) <= 16 for r in rows)
    assert [int(r["order"]) for r in rows] == list(range(1, len(rows) + 1))


def test_every_code_in_nkmi_snapshot(root):
    snap = json.loads((root / "data" / "snapshots" / "nkmi.json").read_text(encoding="utf-8"))
    assert all(r["code"] in snap["codes"] for r in rows398(root))


def test_verified_only_from_signed_pages(root):
    signed = {c: p["page"] for p in scan_pages(root, EO_398N) for c in p["codes"]}
    for r in rows398(root):
        if r["verified"] == "true":
            assert r["code"] in signed and r["verified_at"]
            assert str(signed[r["code"]]) == r["scan_page"]
        assert r["legal_reviewed"] == "false"


def test_tsr_flag_follows_footnote(root):
    quotes = {q["id"] for q in read_yaml(root / "data" / "quotes.yaml")}
    sources = {s["id"] for s in read_yaml(root / "data" / "sources.yaml")}
    for r in rows398(root):
        assert r["tsr_2347r"] in ("yes", "no", "unknown", "by_fn2"), r["code"]
        if r["tsr_2347r"] in ("yes", "no"):
            assert r["tsr_source_ref"] in quotes | sources, f"{r['code']}: {r['tsr_2347r']} без источника"
        if r["fn2"] == "true":
            assert r["tsr_2347r"] in ("by_fn2", "yes", "no") and r["tsr_source_ref"]
        else:
            assert r["tsr_2347r"] != "by_fn2"


def test_tsr_yes_without_source_is_rejected_by_schema(root):
    import jsonschema
    schema = json.loads((root / "data" / "schema" / "devices-398n.schema.json").read_text(encoding="utf-8"))
    item_schema = schema["properties"]["items"]["items"]
    fixture = json.loads((root / "tests" / "fixtures" / "devices-398n.json").read_text(encoding="utf-8"))
    item = dict(fixture["items"][0], tsr_2347r="yes", tsr_source_ref=None)
    try:
        jsonschema.validate(item, item_schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("tsr_2347r=yes без tsr_source_ref прошёл схему")


def test_348n_signed_and_amended(root):
    rows = read_csv(root / "data" / "348n.csv")
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"\d{6}", c) for c in codes)
    assert {r["code"] for r in rows if r["amended_by"] == "added_1195n"} == {"134620"}
    pages = scan_pages(root, EO_348N)
    assert sorted(int(p["page"]) for p in pages) == list(range(2, 19))
    names = read_yaml(root / "data" / "review" / "348n_names.yaml")["names"]
    new = {r["code"] for r in rows398(root)}
    removed = [c for c in codes if c not in new]
    assert all(c in names for c in removed)


def test_aliases(root):
    rows = read_csv(root / "data" / "aliases.csv")
    assert len(rows) >= 30
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    known = {r["code"] for r in rows398(root)} | {r["code"] for r in read_csv(root / "data" / "348n.csv")}
    by = {r["id"]: r for r in rows}
    for r in rows:
        codes = r["codes"].split(";")
        assert codes and all(c in known for c in codes), r["id"]
        if r["primary_for"]:
            assert r["primary_for"] in codes
        assert r["kind"] in ("household", "abbr", "misspelling")
        assert "http" not in r["seen_in"]
    for alias_id, codes in MANDATORY_ALIASES.items():
        assert set(by[alias_id]["codes"].split(";")) == codes
    assert by["trubka"]["ambiguous"] == "true"
    assert len({r["subgroup_title"] for r in rows398(root) if r["code"] in by["trubka"]["codes"].split(";")}) > 1
    assert by["matras"]["codes"] and all("ротивопролежнев" in r["nkmi_name"] for r in rows398(root) if r["code"] in by["matras"]["codes"].split(";"))
    assert all("оляск" in r["nkmi_name"] for r in rows398(root) if r["code"] in by["kolyaska"]["codes"].split(";"))


SAME_NUMBER_ACTS = {"0001202112140014", "0001202211220014", "0001202412050026"}


def test_nutrition_editions(root):
    from pipeline.fetch_pravo import read_sources_tsv
    rows = read_csv(root / "data" / "nutrition_3551r.csv")
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) and len(ids) >= 4
    assert "0001202501270007" in ids
    assert not set(ids) & SAME_NUMBER_ACTS
    assert rows[0]["kind"] == "base" and all(r["kind"] == "amendment" for r in rows[1:])
    assert all(r["amends"] == rows[0]["id"] for r in rows[1:])
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    tsv = read_sources_tsv(root)
    sources = {s["id"]: s for s in read_yaml(root / "data" / "sources.yaml")}
    quotes = {q["id"]: q for q in read_yaml(root / "data" / "quotes.yaml")}
    for r in rows:
        src = sources[r["source_ref"]]
        assert src["eoNumber"] == r["id"] and tsv[r["id"]]["sha256"] == src["sha256"], r["id"]
        q = quotes[r["quote_id"]]
        assert q["verified"] == "true" and q["eoNumber"] == r["id"] and q["scan_page"] == "1", r["id"]


def test_nutrition_items_numbered_without_gaps(root):
    rows = read_csv(root / "data" / "nutrition_3551r.csv")
    expect = 1
    for r in rows:
        assert int(r["items_from"]) == expect, f"{r['id']}: ждали пункт {expect}, в данных {r['items_from']}"
        assert int(r["items_to"]) >= int(r["items_from"])
        expect = int(r["items_to"]) + 1


def test_orders_scan_covers_period(root):
    import glob
    files = sorted(glob.glob(str(root / "raw" / "orders_scan" / "government-orders-*.tsv")))
    assert files
    hits = {}
    for f in files:
        for line in open(f, encoding="utf-8").read().splitlines()[1:]:
            parts = line.split("\t")
            if parts[4] == "1":
                hits[parts[0]] = parts[1]
    review = {r["eoNumber"]: r for r in read_yaml(root / "data" / "review" / "nutrition_orders_review.yaml")}
    assert set(hits) <= set(review), sorted(set(hits) - set(review))
    editions = {r["id"] for r in read_csv(root / "data" / "nutrition_3551r.csv")}
    for eo, r in review.items():
        assert r["decision"] in ("edition", "not_amendment", "same_number"), eo
        assert (r["decision"] == "edition") == (eo in editions), eo


def test_quotes_reference_known_sources(root):
    sources = {s["id"] for s in read_yaml(root / "data" / "sources.yaml")}
    for q in read_yaml(root / "data" / "quotes.yaml"):
        assert q["source_ref"] in sources
        if q["verified"] == "true":
            assert q["text_verbatim"] and q["eoNumber"] and q["scan_page"] and q["verified_at"]


def test_verified_quotes_match_ocr_of_their_page(root):
    from pipeline.common import words
    for q in read_yaml(root / "data" / "quotes.yaml"):
        if q["verified"] != "true":
            continue
        d = root / "raw" / "ocr" / q["eoNumber"]
        page = int(q["scan_page"])
        texts = [d / f"p-{p:02d}.txt" for p in (page, page + 1)]
        ocr = " ".join(t.read_text(encoding="utf-8") for t in texts if t.is_file())
        assert ocr, f"{q['id']}: нет OCR страницы {page}"
        ocr = ocr.replace("-\n", "")
        want = {w for w in words(q["text_verbatim"]) if len(w) > 3}
        have = words(ocr)
        share = len(want & have) / len(want)
        assert share >= 0.85, f"{q['id']}: в OCR страницы нашлось {share:.0%} слов цитаты"


def test_golden_full_list(root):
    golden = yaml.safe_load((root / "tests" / "golden" / "398n.yaml").read_text(encoding="utf-8"))
    rows = rows398(root)
    want = [(g["code"], int(g["page"]), int(g["group"]), bool(g["fn2"]), g["name"]) for g in golden["rows"]]
    have = [(r["code"], int(r["scan_page"]), int(r["group_no"]), r["fn2"] == "true", r["name_in_act"]) for r in rows]
    assert len(want) == 170
    assert have == want


def test_every_page_checked_twice(root):
    pages = scan_pages(root, EO_398N)
    assert sorted(int(p["page"]) for p in pages) == list(range(3, 17))
    for p in pages:
        assert p["checked_at"] and p["method"], p["page"]
        second = p["second_check"]
        assert second["checked_at"] and second["method"] and second["result"], p["page"]
        assert second["method"] != p["method"], p["page"]


def test_ocr_conflicts_resolved(root):
    from pipeline.parse_398n import PASSES, all_conflicts
    conflicts = all_conflicts(root)
    assert {c["pass"] for c in conflicts} <= {name for name, _ in PASSES}
    assert all((root / "raw" / "ocr" / folder).is_dir() for _, folder in PASSES)
    assert [c for c in conflicts if not c["resolution"]] == []
    saved = read_csv(root / "data" / "review" / "398n_conflicts.csv")
    assert len(saved) == len(conflicts)


ALIASES_NOT_REQUIRED: dict[str, str] = {}


def test_aliases_v2(root):
    from pipeline.common import norm_text
    from pipeline.nkmi import read_descriptions
    rows = read_csv(root / "data" / "aliases.csv")
    assert len(rows) >= 80
    descs = read_descriptions(root)
    acts = {r["code"]: r for r in rows398(root)}
    unverified = [r for r in rows if r["verified"] != "true"]
    assert len(unverified) <= 10
    for r in rows:
        seen = r["seen_in"].lower()
        assert seen and "вконтакт" not in seen and "телеграм" not in seen and "vk" not in seen and "t.me" not in seen, r["id"]
        if r["verified"] == "true":
            basis = norm_text(r["basis"])
            assert basis, r["id"]
            assert any(basis in norm_text(acts[c]["name_in_act"] + " " + acts[c]["nkmi_name"] + " " + descs.get(c, ""))
                       for c in r["codes"].split(";") if c in acts), r["id"]
        else:
            assert r["reason"], r["id"]
        if r["kind"] == "misspelling":
            assert r["primary_for"] == "" and r["search_only"] in ("true", "false")
    by = {r["id"]: r for r in rows}
    assert by["pampersy"]["search_only"] == "true"
    assert any(r["kind"] == "misspelling" for r in rows)
    covered = {c for r in rows for c in r["codes"].split(";")}
    missing = set(acts) - covered - set(ALIASES_NOT_REQUIRED)
    assert not missing, sorted(missing)


def test_quotes_empty_or_unverified_have_reason(root):
    for q in read_yaml(root / "data" / "quotes.yaml"):
        if not q["text_verbatim"] or q["verified"] != "true":
            assert q.get("reason"), q["id"]
        if not q["text_verbatim"]:
            assert q["verified"] == "false" and q.get("moved_to"), q["id"]


def test_nutrition_items_follow_page_signatures(root):
    import jsonschema
    from pipeline import export
    pages = read_yaml(root / "data" / "review" / "nutrition_pages.yaml")
    items = read_csv(root / "data" / "nutrition_items.csv")
    editions = read_csv(root / "data" / "nutrition_3551r.csv")
    for e in editions:
        signed = [p for p in pages if p["eo"] == e["id"]]
        assert signed and all(p["checked_at"] and p["method"] for p in signed), e["id"]
        want = sum(int(p["items_to"]) - int(p["items_from"]) + 1 for p in signed)
        have = [r for r in items if r["edition_added"] == e["id"]]
        assert len(have) == want == int(e["items_to"]) - int(e["items_from"]) + 1, e["id"]
    assert [int(r["item_no"]) for r in items] == list(range(1, len(items) + 1))
    schema = json.loads((root / "data" / "schema" / "nutrition-items.schema.json").read_text(encoding="utf-8"))
    src = export.load(root)
    for it in export.nutrition_position_items(root, src):
        jsonschema.validate(it, schema["properties"]["items"]["items"])
        if it["text_verified"]:
            assert it["name"] and it["form"]


def test_nutrition_items_not_published_while_flag_off(root, monkeypatch):
    from pipeline import export
    monkeypatch.delenv("OP_FIXTURES", raising=False)
    meta = read_yaml(root / "data" / "meta.yaml")
    assert meta["publish_items"] == "false"
    envs = export.datasets(root)
    assert "nutrition-items" not in [e["dataset"] for e in envs]
    blob = json.dumps(envs, ensure_ascii=False)
    assert "Ресурс Юниор" not in blob and "ПедиаШур" not in blob
    site = root / "_site"
    if site.is_dir():
        for p in site.rglob("*"):
            if p.is_file() and p.suffix in (".html", ".json", ".csv"):
                assert "ПедиаШур" not in p.read_text(encoding="utf-8", errors="ignore"), p
