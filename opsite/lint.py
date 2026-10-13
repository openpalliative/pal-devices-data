import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import yaml

from .data import OPSITE

DASH = re.compile("[–—]")
EMOJI = re.compile("[←-⇿⌀-⏿①-⓿■-➿⤀-⥿⬀-⯿"
                   "︎️‍\U0001f000-\U0001faff]")
AI_WORDS = re.compile(r"(?<![А-Яа-яЁё])ИИ(?![А-Яа-яЁё])|нейросет|\bGPT|\bLLM\b|искусственн\w*\s+интеллект",
                      re.IGNORECASE)
AI_CASE = re.compile(r"(?<![А-Яа-яЁё])ИИ(?![А-Яа-яЁё])")
ACT_NUMBER = re.compile(r"№\s*\d+|\b\d+-ФЗ\b|(?<![\d-])\d{2,4}\s?н(?![А-Яа-яЁё])|\b\d{2,5}-р(?![А-Яа-яЁё])")
DOSE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:мг|мкг|мл|ЕД|таб\.)(?![А-Яа-яЁё])")
CAPS = re.compile(r"(?<![А-Яа-яЁёA-Za-z])[А-ЯЁ]{4,}(?![А-Яа-яЁёA-Za-z])")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
CITE_KEYS = {"source", "sources", "cite", "quote_verbatim", "eoNumber", "url", "lint_allow"}
VERBATIM_KEYS = {"quote_verbatim"}


@dataclass
class Finding:
    level: str
    rule: str
    file: str
    line: int
    text: str

    def __str__(self) -> str:
        kind = "Ошибка" if self.level == "error" else "Предупреждение"
        return f"{kind} [{self.rule}] {self.file}:{self.line}: {self.text}"


def private_words(env: dict | None = None) -> re.Pattern | None:
    env = os.environ if env is None else env
    path = env.get("OP_PRIVATE_STOPLIST", "").strip()
    if not path or not Path(path).is_file():
        return None
    words = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE) if words else None


def _load_rules() -> dict:
    lint_dir = OPSITE / "lint"
    words = yaml.load((lint_dir / "words.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    stop = yaml.load((lint_dir / "stoplist.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    terr = yaml.load((lint_dir / "territories.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    drugs = [ln.strip() for ln in (lint_dir / "drugs.txt").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    return {
        "words": [(re.compile(w["pattern"], re.IGNORECASE),
                   re.compile(w["except"], re.IGNORECASE) if w.get("except") else None, w["instead"])
                  for w in words["words"]],
        "stop": [(d["domain"], d["reason"]) for d in stop["domains"]],
        "terr": re.compile("|".join(terr["patterns"])),
        "drugs": re.compile(r"(?<![А-Яа-яЁё])(" + "|".join(map(re.escape, drugs)) + ")", re.IGNORECASE),
        "private": private_words(),
    }


RULES = None


def rules() -> dict:
    global RULES
    if RULES is None:
        RULES = _load_rules()
    return RULES


def check_text(text: str, file: str, line: int, *, allow: frozenset = frozenset(), source: bool = True,
               cite: bool = False, verbatim: bool = False, prose: bool = True) -> list[Finding]:
    r = rules()
    out = []

    def add(level, rule, detail):
        if rule not in allow:
            out.append(Finding(level, rule, file, line, detail))

    if not verbatim and DASH.search(text):
        add("error", "dash", "длинное или среднее тире, пишите короткое -")
    if EMOJI.search(text):
        add("error", "emoji", "эмодзи или пиктограмма в тексте")
    m = AI_WORDS.search(text)
    if m and (m.group(0).upper() != "ИИ" or AI_CASE.search(text)):
        add("error", "ai-words", f"запрещённое слово «{m.group(0)}»")
    if r["private"] is not None:
        m = r["private"].search(text)
        if m:
            add("error", "private-stoplist", f"слово из частного стоп-листа «{m.group(0)}»")
    for domain, reason in r["stop"]:
        if domain in text:
            add("error", "stoplist", f"домен {domain}: {reason}")
    if r["terr"].search(text):
        add("error", "territory", "строка про исключённую территорию, решение за мейнтейнером в РФ")
    if source and not cite:
        m = ACT_NUMBER.search(text)
        if m:
            add("error", "act-number", f"номер акта «{m.group(0)}» литералом, используйте norm('id')")
        m = DOSE.search(text)
        if m:
            add("error", "dose", f"доза «{m.group(0)}» в тексте")
        m = r["drugs"].search(text)
        if m:
            add("error", "drug", f"название препарата «{m.group(0)}»")
    if prose and not cite:
        for pat, exc, instead in r["words"]:
            ok = [e.span() for e in exc.finditer(text)] if exc else []
            m = next((m for m in pat.finditer(text)
                      if not any(a <= m.start() and m.end() <= b for a, b in ok)), None)
            if m:
                add("warning", "words", f"«{m.group(0)}»: {instead}")
        m = CAPS.search(text)
        if m:
            add("warning", "caps", f"капс «{m.group(0)}»")
        if "!" in text:
            add("warning", "exclaim", "восклицательный знак")
    return out


def _allow_from(node) -> set:
    allowed = set()
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if k.value == "lint_allow" and isinstance(v, yaml.SequenceNode):
                for item in v.value:
                    if isinstance(item, yaml.MappingNode):
                        allowed |= {iv.value for ik, iv in item.value if ik.value == "rule"}
    return allowed


def _walk_yaml(node, file: str, allow: frozenset, cite: bool, verbatim: bool, out: list) -> None:
    if isinstance(node, yaml.ScalarNode):
        out.extend(check_text(node.value, file, node.start_mark.line + 1, allow=allow, cite=cite,
                              verbatim=verbatim))
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            _walk_yaml(v, file, allow, cite, verbatim, out)
    elif isinstance(node, yaml.MappingNode):
        allow = allow | _allow_from(node)
        for k, v in node.value:
            if k.value == "lint_allow":
                continue
            _walk_yaml(v, file, allow, cite or k.value in CITE_KEYS, verbatim or k.value in VERBATIM_KEYS, out)


def lint_yaml_text(text: str, file: str, line_offset: int = 0) -> list[Finding]:
    out: list[Finding] = []
    node = yaml.compose(text, Loader=yaml.BaseLoader)
    if node is not None:
        _walk_yaml(node, file, frozenset(), False, False, out)
    for f in out:
        f.line += line_offset
    return out


def lint_md(path: Path, rel: str) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    out: list[Finding] = []
    allow: frozenset = frozenset()
    body, offset = text, 0
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        head, body = text[4:].split("\n---\n", 1)
        node = yaml.compose(head, Loader=yaml.BaseLoader)
        allow = frozenset(_allow_from(node))
        out += [f for f in lint_yaml_text(head, rel, 1) if f.rule not in allow]
        offset = head.count("\n") + 2
    for i, ln in enumerate(body.splitlines(), start=offset + 1):
        out += check_text(ln, rel, i, allow=allow)
    return out


TAG = re.compile(r"<[^>]*>|\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}")


def lint_template(path: Path, rel: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        out += check_text(ln, rel, i, prose=False)
        prose_text = TAG.sub(" ", ln)
        out += [f for f in check_text(prose_text, rel, i) if f.level == "warning"]
        if re.search(r'\sstyle="', ln):
            out.append(Finding("error", "inline-style", rel, i, "атрибут style в шаблоне, используйте класс"))
        if re.search(r"\son[a-z]+=", ln):
            out.append(Finding("error", "inline-handler", rel, i, "обработчик on*= в разметке"))
    return out


def lint_code(path: Path, rel: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        out += check_text(ln, rel, i, source=False, prose=False)
    return out


def lint_css(path: Path, rel: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if path.name != "tokens.css" and HEX.search(ln):
            out.append(Finding("error", "hex", rel, i, "цвет hex вне tokens.css, используйте var(--op-*)"))
        if EMOJI.search(ln) or DASH.search(ln):
            out.append(Finding("error", "dash", rel, i, "тире или пиктограмма в CSS"))
    return out


def lint_sources(root: Path) -> list[Finding]:
    out: list[Finding] = []
    targets = [root / "content", root / "templates", root / "assets", root / "lib"]
    if (root / "opsite" / "VERSION").is_file() and (root / "opsite").resolve() == OPSITE:
        targets += [OPSITE / "templates", OPSITE / "ui" / "js", OPSITE / "ui" / "css", OPSITE / "now.yaml",
                    OPSITE / "tools.yaml"]
    for t in targets:
        files = [t] if t.is_file() else sorted(p for p in t.rglob("*") if p.is_file()) if t.is_dir() else []
        for p in files:
            rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else p.as_posix()
            if "vendor" in p.relative_to(t.parent).parts:
                continue
            if p.suffix == ".md":
                out += lint_md(p, rel)
            elif p.suffix in (".yaml", ".yml"):
                out += lint_yaml_text(p.read_text(encoding="utf-8"), rel)
            elif p.name.endswith((".js.j2", ".webmanifest.j2")):
                out += lint_code(p, rel)
            elif p.name.endswith(".j2"):
                out += lint_template(p, rel)
            elif p.suffix == ".js":
                out += lint_code(p, rel)
            elif p.suffix == ".css":
                out += lint_css(p, rel)
    return out


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.verbatim = 0
        self.stack: list[tuple[str, bool]] = []
        self.chunks: list[tuple[str, bool, int]] = []
        self.inline_scripts = 0
        self.handlers: list[str] = []
        self.styles = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "template"):
            if tag == "script" and "src" not in a and a.get("type") != "application/json":
                self.inline_scripts += 1
            self.skip += tag != "template"
        for k, _ in attrs:
            if k.startswith("on"):
                self.handlers.append(f"{tag}[{k}]")
        if "style" in a:
            self.styles += 1
        is_verbatim = "data-verbatim" in a
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
            self.stack.append((tag, is_verbatim))
            self.verbatim += is_verbatim
        for k in ("title", "aria-label", "alt", "placeholder", "content"):
            if a.get(k) and tag != "meta":
                self.chunks.append((a[k], self.verbatim > 0, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        while self.stack:
            t, v = self.stack.pop()
            self.verbatim -= v
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.chunks.append((data, self.verbatim > 0, self.getpos()[0]))


def lint_html(path: Path, rel: str) -> list[Finding]:
    p = _TextExtractor()
    p.feed(path.read_text(encoding="utf-8"))
    out = []
    for text, verbatim, line in p.chunks:
        out += [f for f in check_text(text, rel, line, source=False, prose=False, verbatim=verbatim)]
    if p.inline_scripts:
        out.append(Finding("error", "inline-script", rel, 0, "инлайн-скрипт в HTML"))
    for h in p.handlers:
        out.append(Finding("error", "inline-handler", rel, 0, f"обработчик {h}"))
    if p.styles:
        out.append(Finding("error", "inline-style", rel, 0, f"атрибутов style: {p.styles}"))
    return out


CSP_META = re.compile(r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"\s*/?>', re.IGNORECASE)
FIRST_RES = re.compile(r"<(?:script|link)\b", re.IGNORECASE)


def check_csp(html: str, rel: str) -> list[Finding]:
    from .render import CSP
    found = CSP_META.findall(html)
    if not found:
        return [Finding("error", "csp", rel, 0, "нет meta Content-Security-Policy")]
    out = []
    if len(found) > 1:
        out.append(Finding("error", "csp", rel, 0, "meta Content-Security-Policy больше одной"))
    if found[0].replace("&#39;", "'") != CSP:
        out.append(Finding("error", "csp", rel, 0, "CSP отличается от строки из base.html.j2"))
    first = FIRST_RES.search(html)
    if first and first.start() < CSP_META.search(html).start():
        out.append(Finding("error", "csp", rel, 0, "meta CSP стоит после script или link"))
    return out


def lint_output(out_dir: Path) -> list[Finding]:
    found = []
    for p in sorted(out_dir.rglob("*.html")):
        rel = "_site/" + p.relative_to(out_dir).as_posix()
        found += lint_html(p, rel)
        found += check_csp(p.read_text(encoding="utf-8"), rel)
    terr = rules()["terr"]
    for p in sorted((out_dir / "data").rglob("*.json")) if (out_dir / "data").is_dir() else []:
        m = terr.search(p.read_text(encoding="utf-8"))
        if m:
            found.append(Finding("error", "territory", "_site/" + p.relative_to(out_dir).as_posix(), 0,
                                 f"строка про исключённую территорию «{m.group(0)}»"))
    return found
