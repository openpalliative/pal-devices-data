import hashlib

import pytest

from pipeline import fetch_pravo, net

SRC = """- id: pravo-x
  title: "x"
  short_title: "x"
  url: "http://publication.pravo.gov.ru/document/0001202508130021"
  eoNumber: "0001202508130021"
  pages: "1"
  sha256: "{sha}"
  retrieved_at: ""
  norm_id: "x"
  license: ""
"""


def setup(tmp_path, body: bytes, sha: str | None = None):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sources.yaml").write_text(SRC.format(sha=sha if sha is not None else hashlib.sha256(body).hexdigest()), encoding="utf-8")
    return tmp_path


def test_fetch_writes_cache_and_tsv(tmp_path, monkeypatch):
    body = b"%PDF-1.4 test"
    root = setup(tmp_path, body)
    monkeypatch.delenv("OP_SCRATCH", raising=False)
    seen = []
    p = fetch_pravo.fetch("0001202508130021", root, get=lambda u: seen.append(u) or body, today="2026-10-11")
    assert p.read_bytes() == body
    assert seen == ["http://publication.pravo.gov.ru/file/pdf?eoNumber=0001202508130021"]
    row = fetch_pravo.read_sources_tsv(root)["0001202508130021"]
    assert row["sha256"] == hashlib.sha256(body).hexdigest() and row["bytes"] == str(len(body))
    fetch_pravo.fetch("0001202508130021", root, get=lambda u: pytest.fail("второй раз качать не нужно"))


def test_fetch_rejects_non_pdf(tmp_path, monkeypatch):
    root = setup(tmp_path, b"", sha="")
    monkeypatch.delenv("OP_SCRATCH", raising=False)
    with pytest.raises(net.SourceDown):
        fetch_pravo.fetch("0001202508130021", root, get=lambda u: b"<html>")


def test_api_fixture_names_act(fix):
    import json
    item = json.loads((fix / "api398.json").read_text(encoding="utf-8"))["items"][0]
    assert item["eoNumber"] == "0001202508130021" and item["number"] == "398н" and item["pagesCount"] == 16
