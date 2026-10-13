import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from opsite import check, lint, links, render
from opsite.build import check_situations, minify_css, sitemap_xml
from opsite.data import BuildError

PHONE = re.compile(r"^(\d{2,6}|8 \d{3,5} (\d{1,3}-)?\d{2}-\d{2})(, .+)?$")


@pytest.mark.parametrize("raw, shown", [
    ("8 (495) 777-77-77", "8 495 777-77-77"),
    ("+7 (495) 777-77-77", "8 495 777-77-77"),
    ("8-800-700-84-36", "8 800 700-84-36"),
    ("+7 800 550 99 03", "8 800 550-99-03"),
    ("8 (804) 333-01-03", "8 804 333-01-03"),
    ("8 (8772) 53-49-97", "8 8772 53-49-97"),
    ("8 (81370) 2-12-34", "8 81370 2-12-34"),
    ("112", "112"),
    ("103", "103"),
    ("8 (495) 123-45-67, доб. 3", "8 495 123-45-67, доб. 3"),
])
def test_tel_display(raw, shown):
    assert render.tel_display(raw) == shown
    assert PHONE.match(shown)
    assert render.tel(raw).startswith("tel:")


def test_norm_three_states():
    assert render.norm_state({"status": "in_force", "verified": True}) == "in_force"
    assert render.norm_state({"status": "repealed", "verified": True}) == "repealed"
    assert render.norm_state({"status": "repealed", "verified": False}) == "unverified"
    assert render.norm_state({"status": "in_force", "verified": False}) == "unverified"
    assert render.norm_state(None) == "unverified"


def _rules(found):
    return {f.rule for f in found if f.level == "error"}


def test_ai_words_are_general(monkeypatch):
    monkeypatch.delenv("OP_PRIVATE_STOPLIST", raising=False)
    monkeypatch.setattr(lint, "RULES", None)
    assert "ai-words" in _rules(lint.check_text("собрано нейросетью", "x", 1))
    assert "ai-words" in _rules(lint.check_text("ответ LLM", "x", 1))
    assert "ai-words" in _rules(lint.check_text("искусственный интеллект", "x", 1))
    assert not _rules(lint.check_text("Компания Пример", "x", 1))


def test_words_system_medical_context(monkeypatch):
    monkeypatch.setattr(lint, "RULES", None)

    def warns(text):
        return {f.rule for f in lint.check_text(text, "x", 1) if f.level == "warning"}
    assert "words" not in warns("Болезни нервной системы, в том числе БАС")
    assert "words" not in warns("болезни органов дыхательной системы")
    assert "words" in warns("так устроена система")
    assert "words" in warns("Болезни нервной системы. Такая система не работает")


def test_private_stoplist_both_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(lint, "RULES", None)
    monkeypatch.setenv("OP_PRIVATE_STOPLIST", str(tmp_path / "missing.txt"))
    assert not _rules(lint.check_text("Компания Пример", "x", 1))
    stop = tmp_path / "stop.txt"
    stop.write_text("# частные слова\nкомпания пример\n", encoding="utf-8")
    monkeypatch.setenv("OP_PRIVATE_STOPLIST", str(stop))
    monkeypatch.setattr(lint, "RULES", None)
    assert "private-stoplist" in _rules(lint.check_text("Компания Пример", "x", 1))
    monkeypatch.setattr(lint, "RULES", None)


def test_stoplist_reasons_are_public():
    text = (Path(lint.OPSITE) / "lint" / "stoplist.yaml").read_text(encoding="utf-8")
    assert not re.search(r"\.md\b|/Users/|~/|\bnyu", text)


GOOD_HEAD = f'<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{render.CSP}"><script src="a.js"></script></head></html>'


def test_csp_checks():
    assert not lint.check_csp(GOOD_HEAD, "p.html")
    assert _rules(lint.check_csp("<html><head></head></html>", "p.html")) == {"csp"}
    late = f'<head><script src="a.js"></script><meta http-equiv="Content-Security-Policy" content="{render.CSP}"></head>'
    assert any("после script" in f.text for f in lint.check_csp(late, "p.html"))
    other = GOOD_HEAD.replace("form-action 'none'", "form-action 'self'")
    assert any("отличается" in f.text for f in lint.check_csp(other, "p.html"))


@pytest.mark.parametrize("code", [
    "fetch(`https://x`)",
    "navigator.sendBeacon('https://x', data)",
    "xhr.open('POST', 'https://x')",
    "new WebSocket('wss://x')",
    "new EventSource('//x/stream')",
    "import('https://x/mod.js')",
    'fetch("//x/a")',
])
def test_js_network_rules(tmp_path, code):
    (tmp_path / "a.js").write_text(f"export function f() {{ {code}; }}\n", encoding="utf-8")
    assert _rules(links.check_runtime_network(tmp_path)) == {"network"}


def test_js_local_requests_allowed(tmp_path):
    (tmp_path / "a.js").write_text('fetch(new URL("../data/x.json", import.meta.url)); import("./b.js");\n',
                                   encoding="utf-8")
    assert not links.check_runtime_network(tmp_path)


def test_sitemap_and_seo_checks(tmp_path):
    site = {"site_url": "https://openpalliative.github.io", "base": "/pal-norms/"}
    xml = sitemap_xml(site, ["index.html", "acts/index.html"], "2026-10-11")
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.fromstring(xml).findall("s:url/s:loc", ns)]
    assert locs == ["https://openpalliative.github.io/pal-norms/acts/", "https://openpalliative.github.io/pal-norms/"]
    (tmp_path / "a").mkdir()
    (tmp_path / "index.html").write_text('<link rel="canonical" href="https://x.org/">', encoding="utf-8")
    (tmp_path / "a" / "index.html").write_text("<p>без canonical</p>", encoding="utf-8")
    (tmp_path / "case").mkdir()
    (tmp_path / "case" / "index.html").write_text('<meta name="robots" content="noindex"><link rel="canonical" '
                                                 'href="https://x.org/case/">', encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<urlset><url><loc>./a/</loc></url><url><loc>https://x.org/case/</loc>"
                                          "</url></urlset>", encoding="utf-8")
    texts = " ".join(f.text for f in check.check_seo(tmp_path))
    assert "ровно одно" in texts and "относительный" in texts and "noindex" in texts


def test_situations_extra_key_fails():
    bad = {"situations": [{"id": "discharge", "title": "т", "hint": "х", "icon": "x",
                           "today": [{"repo": "hub", "label": "Что делать", "если выписывают": ""}]}]}
    with pytest.raises(BuildError, match=r"discharge/today\[0\] лишний ключ"):
        check_situations(bad)
    good = {"situations": [{"id": "discharge", "title": "т", "hint": "х", "icon": "x", "urgent": "true",
                            "today": [{"repo": "hub", "label": "Что делать, если выписывают"}]}]}
    check_situations(good)


def test_budget_gzip_and_allowance(tmp_path):
    (tmp_path / "ui").mkdir()
    big = "a" * 120 * 1024
    (tmp_path / "ui" / "x.css").write_text(big, encoding="utf-8")
    (tmp_path / "index.html").write_text('<link rel="stylesheet" href="ui/x.css">', encoding="utf-8")
    sizes: dict = {}
    assert not [f for f in links.check_budgets(tmp_path, sizes, {"first_load_kb": 100, "gzip": "true"}) if f.level == "error"]
    assert [f for f in links.check_budgets(tmp_path, {}, {"first_load_kb": 100}) if f.level == "error"]
    allow = {"first_load_kb": 100, "allow": [{"page": "index.html", "kb": 125, "reason": "проверка исключения"}]}
    found = links.check_budgets(tmp_path, {}, allow)
    assert not [f for f in found if f.level == "error"] and [f for f in found if f.level == "warning"]


def test_minify_css_keeps_strings_and_descendants():
    css = '.a :not(.b) > .c , .d { content: " ( , ) " ; width: calc(1px + 2em) }\n/* x */'
    assert minify_css(css) == '.a :not(.b)>.c,.d{content:" ( , ) ";width:calc(1px + 2em)}\n'


def test_sprite_contains_only_symbols():
    svg = render.sprite({"phone", "check"})
    assert svg.count("<symbol") == 2 and 'id="phone"' in svg and "<!--" not in svg
