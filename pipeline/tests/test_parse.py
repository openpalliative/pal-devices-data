import io

from pipeline import nkmi
from pipeline.common import nkmi_status, norm_text
from pipeline.parse_398n import ocr_conflicts, recover


def kinds(fix):
    return nkmi.parse_xml(io.BytesIO((fix / "nkmi_sample.xml").read_bytes()))


def test_fragment_7610_recovers_327610_only_with_matching_name(fix):
    text = (fix / "ocr_398n_p03.txt").read_text(encoding="utf-8")
    k = kinds(fix)
    lines = text.splitlines()
    i = next(n for n, ln in enumerate(lines) if "7610" in ln)
    window = " ".join(lines[max(0, i - 4): i + 5])
    assert recover("7610", window, k) == ["327610"]
    assert recover("7610", "Подгузники для взрослых", k) == []


def test_ocr_conflicts_report_fragment_and_missing(fix):
    text = (fix / "ocr_398n_p03.txt").read_text(encoding="utf-8")
    signed = ["232490", "283460", "322330", "327610", "327640", "113890", "114040", "232890"]
    out = ocr_conflicts(text, 3, signed, kinds(fix))
    kinds_found = {(c["kind"], c["value"]) for c in out}
    assert ("ocr_fragment", "7610") in kinds_found
    assert ("ocr_missing", "327610") in kinds_found
    assert not [c for c in out if c["kind"] == "ocr_extra"]


def test_status_rules():
    assert nkmi_status("Инсуффлятор-аспиратор", "Инсуффлятор-аспиратор") == "present"
    assert nkmi_status("Концентратор кислорода мобильный/портативный", "Концентратор кислорода переносной/портативный") == "renamed"
    assert nkmi_status("Средство гемостатическое неорганического происхождения",
                       "Система управления/получения видеоизображений для эндоскопа") == "mismatch"
    assert nkmi_status("Пульсоксиметр", None) == "missing"


def test_norm_text():
    assert norm_text(" Ёлочный - КОЛЯСКА,  ") == "елочный коляска"
