import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .build import load_site
from .data import OPSITE, days_old, read_yaml
from .lint import Finding, lint_output, lint_sources
from .links import check_budgets, check_links, check_runtime_network, parse_refs
from .messages_ru import msg

MANIFEST_SKIP = {"MANIFEST.sha256"}


def manifest_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file() and p.name not in MANIFEST_SKIP
                  and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".DS_Store")


def write_manifest(base: Path = OPSITE) -> int:
    lines = manifest_lines(base)
    (base / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def manifest_lines(base: Path) -> list[str]:
    return [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(base).as_posix()}"
            for p in manifest_files(base)]


def manifest_changed(base: Path) -> bool:
    mf = base / "MANIFEST.sha256"
    if not mf.is_file():
        return True
    old = [ln for ln in mf.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.endswith("  VERSION")]
    new = [ln for ln in manifest_lines(base) if not ln.endswith("  VERSION")]
    return old != new


def bump_version(base: Path) -> str:
    major, minor, patch = (int(x) for x in (base / "VERSION").read_text().strip().split("."))
    version = f"{major}.{minor}.{patch + 1}"
    (base / "VERSION").write_text(version + "\n", encoding="utf-8")
    return version


def verify_manifest(base: Path) -> list[str]:
    mf = base / "MANIFEST.sha256"
    if not mf.is_file():
        return ["MANIFEST.sha256 отсутствует"]
    expected = {}
    for ln in mf.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            digest, name = ln.split("  ", 1)
            expected[name] = digest
    actual = {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in manifest_files(base)}
    bad = [n for n in sorted(set(expected) | set(actual)) if expected.get(n) != actual.get(n)]
    return bad


def normalize_html(html: str) -> str:
    html = re.sub(r'<p class="op-footer-build">.*?</p>', "", html, flags=re.S)
    html = re.sub(r'<details class="op-footer-data">.*?</details>', "", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def check_golden(root: Path, site_dir: Path, update: bool) -> list[Finding]:
    gdir = root / "tests" / "golden" / "html"
    out = []
    if not gdir.is_dir():
        return out
    for g in sorted(gdir.glob("*.html")):
        page = site_dir / g.stem.replace("__", "/") / "index.html"
        if g.stem == "home":
            page = site_dir / "index.html"
        if not page.is_file():
            out.append(Finding("error", "golden", g.name, 0, "страница из эталона не собрана"))
            continue
        got = normalize_html(page.read_text(encoding="utf-8"))
        if update:
            g.write_text(got + "\n", encoding="utf-8")
        elif got != g.read_text(encoding="utf-8").strip():
            out.append(Finding("error", "golden", g.name, 0, "HTML отличается от эталона (--update-golden)"))
    return out


LOC = re.compile(r"<loc>([^<]*)</loc>")
CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"')
NOINDEX = '<meta name="robots" content="noindex">'


def check_seo(site_dir: Path) -> list[Finding]:
    out = []
    smap = site_dir / "sitemap.xml"
    pages = {p.relative_to(site_dir).as_posix(): p.read_text(encoding="utf-8") for p in sorted(site_dir.rglob("*.html"))}
    noindex_urls = set()
    for rel, html in pages.items():
        canon = CANONICAL.findall(html)
        if NOINDEX in html or rel == "404.html":
            noindex_urls.update(canon)
            continue
        if len(canon) != 1:
            out.append(Finding("error", "seo", rel, 0, f"rel=canonical должно быть ровно одно, сейчас {len(canon)}"))
        elif not re.match(r"^https?://", canon[0]) or not canon[0].endswith("/"):
            out.append(Finding("error", "seo", rel, 0, f"canonical не абсолютный адрес со слешем: {canon[0]}"))
    if not smap.is_file():
        out.append(Finding("error", "seo", "sitemap.xml", 0, "нет sitemap.xml"))
        return out
    for loc in LOC.findall(smap.read_text(encoding="utf-8")):
        if not re.match(r"^https?://", loc):
            out.append(Finding("error", "seo", "sitemap.xml", 0, f"относительный адрес в карте: {loc}"))
        elif loc in noindex_urls:
            out.append(Finding("error", "seo", "sitemap.xml", 0, f"страница с noindex в карте: {loc}"))
    return out


def check_hub_drift(root: Path) -> list[Finding]:
    hub = Path(os.environ.get("OP_HUB") or root.parent / "openpalliative.github.io") / "opsite"
    mine = root / "opsite"
    if not hub.is_dir() or hub.resolve() == mine.resolve() or not (mine / "VERSION").is_file():
        return []
    same_version = (hub / "VERSION").read_text().strip() == (mine / "VERSION").read_text().strip()
    hub_mf, mine_mf = hub / "MANIFEST.sha256", mine / "MANIFEST.sha256"
    if same_version and hub_mf.is_file() and mine_mf.is_file() and hub_mf.read_bytes() != mine_mf.read_bytes():
        return [Finding("warning", "opsite", "opsite/VERSION", 0,
                        "версия opsite та же, что в хабе, а файлы другие: в хабе нужно поднять VERSION")]
    return []


def check_freshness(root: Path) -> list[Finding]:
    out = []
    vroot = root / "vendor"
    for f in sorted(vroot.glob("*/v1/*.json")) if vroot.is_dir() else []:
        if f.name.endswith(".schema.json") or f.name == "index.json":
            continue
        env = json.loads(f.read_text(encoding="utf-8"))
        days = int(env.get("stale_after_days", 90))
        if days_old(env["data_date"]) > days:
            out.append(Finding("warning", "stale", f.relative_to(root).as_posix(), 0,
                               msg("stale", repo=f.parts[-3], name=env["dataset"], data_date=env["data_date"],
                                   days=days)))
    return out


def run(root: Path, ci: bool = False, update_golden: bool = False) -> int:
    root = root.resolve()
    site = load_site(root)
    site_dir = root / "_site"
    if not site_dir.is_dir():
        print(msg("no_site"))
        return 1
    tools = {t["repo"] for t in read_yaml(OPSITE / "tools.yaml")["tools"]}
    findings: list[Finding] = []
    findings += lint_sources(root)
    findings += lint_output(site_dir)
    link_findings, external, cross = check_links(site_dir, site["base"], tools)
    findings += link_findings
    findings += check_runtime_network(site_dir)
    sizes: dict = {}
    findings += check_budgets(site_dir, sizes, site.get("budget"))
    findings += check_seo(site_dir)
    findings += check_hub_drift(root)
    findings += check_freshness(root)
    findings += check_golden(root, site_dir, update_golden)
    bad = verify_manifest(root / "opsite")
    if bad:
        is_hub = (root / "opsite").resolve() == OPSITE and site["repo"] == "openpalliative.github.io"
        text = msg("manifest_stale") + ": " + ", ".join(bad[:10]) if is_hub else \
            msg("manifest_mismatch", files=", ".join(bad[:10]))
        findings.append(Finding("error", "opsite", "opsite/MANIFEST.sha256", 0, text))
    reports = root / "_reports"
    reports.mkdir(exist_ok=True)
    (reports / "external-links.txt").write_text("\n".join(external) + "\n", encoding="utf-8")
    (reports / "cross-links.txt").write_text("\n".join(cross) + "\n", encoding="utf-8")
    (reports / "budgets.txt").write_text("\n".join(f"{v // 1024:4d} КБ  {k}" for k, v in sorted(sizes.items())) + "\n",
                                         encoding="utf-8")
    (reports / "check.json").write_text(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    for f in errors + warnings:
        print(("::error::" if ci and f.level == "error" else "::warning::" if ci else "") + str(f))
    if errors:
        print(msg("check_failed", errors=len(errors), warnings=len(warnings)))
        return 1
    print(msg("check_ok", warnings=len(warnings)))
    return 0


def check_org(org_site: Path) -> int:
    tools = {t["repo"] for t in read_yaml(OPSITE / "tools.yaml")["tools"]}
    missing: dict[str, set] = {}
    for page in sorted(org_site.rglob("*.html")):
        rel = page.relative_to(org_site)
        if rel.name == "404.html":
            continue
        for _tag, _attr, ref, _ in parse_refs(page.read_text(encoding="utf-8")):
            parts = urlsplit(ref)
            if parts.scheme or parts.netloc or not parts.path.startswith("/"):
                continue
            target = org_site / parts.path.lstrip("/")
            if parts.path.endswith("/") or target.is_dir():
                target = target / "index.html"
            if not target.exists():
                missing.setdefault(parts.path, set()).add(rel.as_posix())
    errors = warnings = 0
    for path, pages in sorted(missing.items()):
        first = path.strip("/").split("/", 1)[0]
        absent_tool = first in tools and not (org_site / first).is_dir()
        level = "warning" if absent_tool else "error"
        errors += level == "error"
        warnings += level == "warning"
        where = ", ".join(sorted(pages)[:3]) + (f" и ещё {len(pages) - 3}" if len(pages) > 3 else "")
        text = "сайта инструмента пока нет" if absent_tool else "страницы нет"
        print(Finding(level, "cross-link", where, 0, f"{path}: {text}"))
    print(msg("check_failed" if errors else "check_ok", errors=errors, warnings=warnings))
    return 1 if errors else 0
