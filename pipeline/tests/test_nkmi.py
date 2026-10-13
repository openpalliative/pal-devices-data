import io

import pytest

from pipeline import nkmi


def test_meta_parses(fix):
    meta = nkmi.parse_meta((fix / "meta.csv").read_text(encoding="utf-8"))
    assert nkmi.latest(meta)["version"] == "20261001"
    assert nkmi.latest(meta)["structure"] == nkmi.STRUCTURE
    assert len(meta["data"]) == 10
    assert nkmi.STRUCTURE in meta["structures"]


def test_meta_without_header_is_format_change():
    with pytest.raises(nkmi.FormatChanged):
        nkmi.parse_meta("a,b\n1,2\n")


def test_xml_sample_parses(fix):
    kinds = nkmi.parse_xml(io.BytesIO((fix / "nkmi_sample.xml").read_bytes()))
    assert len(kinds) == 50
    assert kinds["303260"] == "Инсуффлятор-аспиратор"
    assert "  " not in "".join(kinds.values())


def test_xml_wrong_root_is_format_change():
    with pytest.raises(nkmi.FormatChanged):
        nkmi.parse_xml(io.BytesIO('<?xml version="1.0"?><other><classificator/></other>'.encode()))


def test_snapshot_lists_absent_codes():
    snap = nkmi.build_snapshot(version="20261001", zip_url="u", zip_sha="z", xsd_sha="x", structure="20180615",
                               kinds={"303260": "Инсуффлятор-аспиратор"}, codes=["303260", "999990"])
    assert snap["codes"] == {"303260": "Инсуффлятор-аспиратор"}
    assert snap["absent"] == ["999990"]
    assert snap["total_kinds"] == 1


def test_zip_bomb_is_format_change(monkeypatch):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.xml", b"<classificator_list>" + b" " * 2048 + b"</classificator_list>")
    monkeypatch.setattr(nkmi, "MAX_XML_BYTES", 1024)
    with pytest.raises(nkmi.FormatChanged):
        nkmi.parse_zip(buf.getvalue())


def test_net_get_limits_size(monkeypatch):
    from pipeline import net

    class R:
        def __init__(self):
            self.data = b"x" * 2048

        def read(self, n=-1):
            return self.data[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(net.urllib.request, "urlopen", lambda *a, **k: R())
    with pytest.raises(net.TooLarge):
        net.get("https://roszdravnadzor.gov.ru/x", max_bytes=1024, pauses=())
    assert net.get("https://roszdravnadzor.gov.ru/x", max_bytes=4096, pauses=()) == b"x" * 2048
