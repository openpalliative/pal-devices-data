import fnmatch
import gzip
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .lint import Finding

RUNTIME_ATTRS = {("script", "src"), ("link", "href"), ("img", "src"), ("source", "srcset"), ("source", "src"),
                 ("iframe", "src"), ("video", "src"), ("audio", "src"), ("object", "data"), ("embed", "src")}
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)")
CSS_IMPORT = re.compile(r"@import\s+['\"]([^'\"]+)")
JS_IMPORT = re.compile(r"""(?:import\s[^"']*?from\s*|import\s*\(\s*|import\s+)["']([^"']+)["']""")
STATIC_IMPORT = re.compile(r"""(?:^|[;\n])\s*(?:import\s[^"'(]*?from\s*|import\s+|export\s[^"'(]*?from\s*)["']([^"']+)["']""")
LAZY_ROW = re.compile(r"""\[\s*"([a-z0-9-]+)"\s*,\s*"(\./[a-z0-9-]+\.js)"\s*\]""")
_Q = r"""["'`]"""
_ABS = r"(?:[a-z][a-z0-9+.-]*:)?//"
JS_NET = [
    re.compile(rf"(?:\bfetch|\bimportScripts|\bimport|new\s+URL|new\s+(?:Shared)?Worker|new\s+EventSource)\s*\(\s*{_Q}{_ABS}",
               re.IGNORECASE),
    re.compile(rf"\.open\s*\(\s*{_Q}[A-Za-z]+{_Q}\s*,\s*{_Q}{_ABS}", re.IGNORECASE),
    re.compile(r"\bsendBeacon\s*\("),
    re.compile(r"\bnew\s+WebSocket\s*\("),
]
FIRST_LOAD_LIMIT = 150 * 1024
JS_LIMIT = 60 * 1024
MARGIN = 5 * 1024


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str, str, dict]] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        for k in ("href", "src", "srcset", "data", "action"):
            if k in a:
                self.refs.append((tag, k, a[k], a))


def parse_refs(html: str) -> list[tuple[str, str, str, dict]]:
    p = _Refs()
    p.feed(html)
    return p.refs


def resolve(site_dir: Path, page: Path, ref: str, base: str, tools: set[str]) -> tuple[str, Path | None]:
    parts = urlsplit(ref)
    path = unquote(parts.path)
    if not path:
        return "self", None
    if path.startswith("/"):
        first = path.strip("/").split("/", 1)[0]
        if base == "/" and first in tools:
            return "cross", None
        if base != "/" and not path.startswith(base):
            return "cross", None
        target = site_dir / path[len(base):] if path.startswith(base) else site_dir / path.lstrip("/")
    else:
        target = (page.parent / path)
    target = Path(str(target))
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return "local", target


def check_links(site_dir: Path, base: str, tools: set[str]) -> tuple[list[Finding], list[str], list[str]]:
    findings, external, cross = [], set(), set()
    for page in sorted(site_dir.rglob("*.html")):
        rel = page.relative_to(site_dir).as_posix()
        if rel == "404.html":
            continue
        for tag, attr, ref, attrs in parse_refs(page.read_text(encoding="utf-8")):
            values = [v.strip().split(" ")[0] for v in ref.split(",")] if attr == "srcset" else [ref]
            for v in values:
                if not v or v.startswith(("#", "mailto:", "tel:", "sms:", "data:", "blob:", "javascript:")):
                    if v.startswith("javascript:"):
                        findings.append(Finding("error", "link", rel, 0, f"javascript: в {tag}[{attr}]"))
                    continue
                if EXTERNAL.match(v):
                    if (tag, attr) in RUNTIME_ATTRS and not (tag == "link" and attrs.get("rel") in
                                                            ("canonical", "alternate", "license")):
                        findings.append(Finding("error", "network", rel, 0, f"внешний ресурс в рантайме: {v}"))
                    else:
                        external.add(v)
                    continue
                kind, target = resolve(site_dir, page, v, base, tools)
                if kind == "cross":
                    cross.add(urlsplit(v).path)
                elif kind == "local" and not target.exists():
                    findings.append(Finding("error", "link", rel, 0, f"битая ссылка {v}"))
    return findings, sorted(external), sorted(cross)


def check_runtime_network(site_dir: Path) -> list[Finding]:
    out = []
    for p in sorted(site_dir.rglob("*")):
        if p.suffix not in (".css", ".js") or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(site_dir).as_posix()
        refs = CSS_URL.findall(text) + CSS_IMPORT.findall(text) if p.suffix == ".css" else JS_IMPORT.findall(text)
        for ref in refs:
            if EXTERNAL.match(ref.strip()):
                out.append(Finding("error", "network", rel, 0, f"внешний адрес в рантайме: {ref}"))
        if p.suffix == ".js":
            for rx in JS_NET:
                m = rx.search(text)
                if m:
                    out.append(Finding("error", "network", rel, text[:m.start()].count("\n") + 1,
                                       f"запрос к внешнему адресу в JS: {m.group(0)[:60]}"))
                    break
    return out


def _weigher(use_gzip: bool):
    cache: dict = {}

    def weigh(path: Path) -> int:
        if path not in cache:
            data = path.read_bytes() if path.is_file() else b""
            packed = use_gzip and path.suffix not in (".woff2", ".png", ".jpg", ".webp")
            cache[path] = len(gzip.compress(data, 9, mtime=0)) if packed and data else len(data)
        return cache[path]
    return weigh


def _js_size(site_dir: Path, entry: Path, seen: set, weigh) -> int:
    if entry in seen or not entry.is_file():
        return 0
    seen.add(entry)
    total = weigh(entry)
    text = entry.read_text(encoding="utf-8", errors="replace")
    for ref in STATIC_IMPORT.findall(text):
        if ref.startswith("."):
            total += _js_size(site_dir, (entry.parent / ref).resolve(), seen, weigh)
    return total


def _lazy_size(site_dir: Path, entry: Path, html: str, seen: set, weigh) -> int:
    if not entry.is_file() or entry.name != "op.js":
        return 0
    total = 0
    for name, ref in LAZY_ROW.findall(entry.read_text(encoding="utf-8", errors="replace")):
        used = ('class="op-date"' in html if name == "op-date" else 'rel="manifest"' in html if name == "manifest"
                else f"<{name}" in html)
        if used:
            total += _js_size(site_dir, (entry.parent / ref).resolve(), seen, weigh)
    return total


def _allowance(budget: dict, rel: str) -> tuple[int, str]:
    for row in budget.get("allow") or []:
        if fnmatch.fnmatch(rel, row.get("page", "")):
            return int(row["kb"]) * 1024, row.get("reason", "")
    return int(budget.get("first_load_kb") or 150) * 1024, ""


def check_budgets(site_dir: Path, sizes: dict | None = None, budget: dict | None = None) -> list[Finding]:
    out = []
    sizes = {} if sizes is None else sizes
    budget = budget or {}
    use_gzip = str(budget.get("gzip", "false")).lower() == "true"
    weigh = _weigher(use_gzip)
    unit = "КБ в gzip" if use_gzip else "КБ"
    for page in sorted(site_dir.rglob("*.html")):
        rel = page.relative_to(site_dir).as_posix()
        html = page.read_text(encoding="utf-8")
        if '<meta name="robots" content="noindex">' in html:
            continue
        total = weigh(page)
        js_total, seen, counted = 0, set(), set()
        for tag, attr, ref, attrs in parse_refs(html):
            if EXTERNAL.match(ref) or ref.startswith(("#", "data:", "mailto:", "tel:")) or ref.startswith("/"):
                continue
            target = (page.parent / urlsplit(ref).path).resolve()
            if tag == "script":
                size = _js_size(site_dir, target, seen, weigh) + _lazy_size(site_dir, target, html, seen, weigh)
                js_total += size
                total += size
                continue
            fetched = (tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("media", "all") != "print") or \
                (tag == "link" and attrs.get("rel") == "preload") or tag == "use"
            if fetched and target not in counted and target.is_file():
                counted.add(target)
                total += weigh(target)
        sizes[rel] = total
        limit, reason = _allowance(budget, rel)
        if total > limit:
            out.append(Finding("error", "budget", rel, 0, f"первая загрузка {total // 1024} {unit}, лимит {limit // 1024}"))
        elif limit - total < MARGIN:
            out.append(Finding("warning", "budget", rel, 0,
                               f"первая загрузка {total // 1024} {unit}, до лимита {limit // 1024} меньше 5 КБ"
                               + (f" (исключение: {reason})" if reason else "")))
        if js_total > JS_LIMIT:
            out.append(Finding("error", "budget", rel, 0, f"JS страницы {js_total // 1024} {unit}, лимит 60"))
    for p in sorted(site_dir.rglob("*.json")):
        if p.stat().st_size > 1024 * 1024:
            out.append(Finding("error", "budget", p.relative_to(site_dir).as_posix(), 0, "JSON больше 1 МБ"))
    return out
