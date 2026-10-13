import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from xml.sax.saxutils import escape as xml_escape
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import sw
from .data import (OPSITE, BuildError, coerce, load_schema, now_utc, read_yaml, validate)
from .messages_ru import msg
from .render import (HUB, ICON_FILE, ICON_FILE_ALL, icon_names, make_env, md, out_path_for, page_dir_url, render,
                     ru_date, sprite, tel_display)

SITE_URL = "https://openpalliative.github.io"
NOINDEX = '<meta name="robots" content="noindex">'

MAX_DATASET = 1024 * 1024


@dataclass
class Ctx:
    root: Path
    site: dict
    out: Path
    opsite_version: str
    built_at: str
    data: dict = field(default_factory=dict)
    vendor: dict = field(default_factory=dict)
    content: dict = field(default_factory=dict)
    now: dict = field(default_factory=dict)
    tools: list = field(default_factory=list)
    situations: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    noindex: set = field(default_factory=set)
    icons_used: set = field(default_factory=set)
    commit: str = ""


def load_site(root: Path) -> dict:
    path = root / "site.yaml"
    if not path.is_file():
        raise BuildError(msg("no_site_yaml", root=root))
    schema = load_schema("site")
    site = coerce(read_yaml(path), schema)
    validate(site, schema, "site.yaml")
    site.setdefault("nav", [])
    site["site_url"] = (os.environ.get("OP_SITE_URL") or site.get("site_url") or SITE_URL).rstrip("/")
    site.setdefault("lang", "ru")
    return site


STEP_KEYS = ("today", "later", "if_failed")


def check_situations(raw: dict, where: str = "situations.yaml") -> None:
    problems = []
    for s in (raw or {}).get("situations") or []:
        if not isinstance(s, dict):
            continue
        allowed = set(load_schema("situations")["$defs"]["steps"]["items"]["properties"])
        for key in STEP_KEYS:
            for i, step in enumerate(s.get(key) or []):
                extra = sorted(set(step) - allowed) if isinstance(step, dict) else []
                if extra:
                    problems.append(f"{where}: у шага {s.get('id')}/{key}[{i}] лишний ключ {', '.join(extra)}. "
                                    "Возможно, в подписи запятая без кавычек: возьмите label в кавычки")
    if problems:
        raise BuildError("\n".join(problems))
    validate(raw, load_schema("situations"), where)


def load_situations_schema(raw: dict, where: str) -> None:
    check_situations(raw, where)


def _import(root: Path, modname: str, relpath: str):
    path = root / relpath
    if not path.is_file():
        return None
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def check_envelope(env: dict, schema_path: Path | None, where: str) -> None:
    validate(env, load_schema("envelope"), where)
    if schema_path is None or not schema_path.is_file():
        raise BuildError(msg("dataset_schema_missing", name=env.get("dataset")))
    validate(env, json.loads(schema_path.read_text(encoding="utf-8")), where)


def load_data(ctx: Ctx) -> None:
    export = _import(ctx.root, "pipeline.export", "pipeline/export.py")
    if export is None:
        return
    for env in export.datasets(ctx.root):
        name = env["dataset"]
        check_envelope(env, ctx.root / "data" / "schema" / f"{name}.schema.json", f"датасет {name}")
        ctx.data[name] = env


def load_vendor(ctx: Ctx) -> None:
    vroot = ctx.root / "vendor"
    if not vroot.is_dir():
        return
    for repo_dir in sorted(p for p in vroot.iterdir() if p.is_dir()):
        for f in sorted((repo_dir / "v1").glob("*.json")) if (repo_dir / "v1").is_dir() else []:
            if f.name.endswith(".schema.json") or f.name == "index.json":
                continue
            env = json.loads(f.read_text(encoding="utf-8"))
            check_envelope(env, f.with_name(f.stem + ".schema.json"), f"vendor/{repo_dir.name}/v1/{f.name}")
            ctx.vendor.setdefault(repo_dir.name, {})[env["dataset"]] = env


def load_content(ctx: Ctx) -> None:
    cdir = ctx.root / "content"
    for f in sorted(cdir.glob("*.yaml")) if cdir.is_dir() else []:
        obj = read_yaml(f)
        sp = cdir / "schema" / f"{f.stem}.schema.json"
        if sp.is_file():
            schema = json.loads(sp.read_text(encoding="utf-8"))
            obj = coerce(obj, schema)
            validate(obj, schema, f"content/{f.name}")
        ctx.content[f.stem] = obj
    ctx.now = coerce(read_yaml(OPSITE / "now.yaml"), load_schema("now"))
    validate(ctx.now, load_schema("now"), "opsite/now.yaml")
    for line in ctx.now["lines"]:
        line.setdefault("note", "")
        line.setdefault("short", "")
        line.setdefault("third_party", False)
        for key in ("point", "eoNumber", "url", "quote_verbatim"):
            line["source"].setdefault(key, "")
    ctx.tools = read_yaml(OPSITE / "tools.yaml")["tools"]
    sit = OPSITE / "situations.json"
    ctx.situations = json.loads(sit.read_text(encoding="utf-8")) if sit.is_file() else []
    if "situations" in ctx.content:
        load_situations_schema(ctx.content["situations"], "content/situations.yaml")


def data_dates(ctx: Ctx) -> list[dict]:
    names = read_yaml(OPSITE / "datasets.yaml")
    internal = set(names.get("internal") or [])
    titles = names.get("titles") or {}
    envs = [(env["repo"], env) for env in ctx.data.values()]
    envs += [(repo, env) for repo, group in ctx.vendor.items() for env in group.values()]
    out = []
    for repo, env in envs:
        name = env["dataset"]
        if name in internal:
            continue
        out.append({"repo": repo, "name": name, "title": (titles.get(repo) or {}).get(name, name),
                    "date": env["data_date"], "stale_after": env["stale_after_days"]})
    return out


def parse_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise BuildError(msg("frontmatter_error", path=path))
    head, body = text[4:].split("\n---\n", 1)
    fm = yaml.load(head, Loader=yaml.BaseLoader) or {}
    schema = load_schema("page-frontmatter")
    fm = coerce(fm, schema)
    validate(fm, schema, path.name)
    return fm, body


def data_summary(dates: list[dict], tools: list[dict]) -> dict:
    if not dates:
        return {"main": "", "other": []}
    main = Counter(d["date"] for d in dates).most_common(1)[0][0]
    titles = {t["repo"]: t["title"] for t in tools}
    oldest: dict[str, str] = {}
    for d in dates:
        oldest[d["repo"]] = min(oldest.get(d["repo"], d["date"]), d["date"])
    other = [{"repo": repo, "tool": titles.get(repo, repo), "date": date}
             for repo, date in sorted(oldest.items(), key=lambda kv: titles.get(kv[0], kv[0]))
             if date != main]
    return {"main": main, "other": other}


def base_vars(ctx: Ctx) -> dict:
    dates = data_dates(ctx)
    return {
        "site": ctx.site,
        "opdata": {"now": ctx.now, "tools": ctx.tools, "situations": ctx.situations,
                   "version": ctx.opsite_version, "built_at": ctx.built_at,
                   "data_dates": dates, "data_summary": data_summary(dates, ctx.tools),
                   "commit": ctx.commit, "hub_repo": HUB},
        "content": ctx.content,
        "data": ctx.data,
        "vendor": ctx.vendor,
        "draft": ctx.site.get("draft_default", "none"),
        "noindex": False,
        "print_only": False,
        "doc": False,
        "page_absolute": False,
        "nav_current": "",
        "lang": ctx.site.get("lang", "ru"),
        "alternates": [],
        "print_url": False,
        "og_image": "",
        "page_flags": {},
        "icons_used": ctx.icons_used,
        "icon_sprite": "",
    }


def write_page(ctx: Ctx, env, template: str, out_rel: str, variables: dict) -> None:
    html = link_page_css(render(env, template, out_rel,
                                {**base_vars(ctx), "page_url": page_dir_url(out_rel), **variables}))
    dest = ctx.out / out_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    ctx.pages.append(out_rel)
    if NOINDEX in html:
        ctx.noindex.add(out_rel)


def render_pages(ctx: Ctx, env, hooks) -> None:
    tdir = ctx.root / "templates" / "pages"
    for t in sorted(tdir.rglob("*.html.j2")) if tdir.is_dir() else []:
        rel = t.relative_to(tdir)
        out_rel = out_path_for(rel)
        write_page(ctx, env, f"pages/{rel.as_posix()}", out_rel, {"nav_current": page_dir_url(out_rel)})
    cdir = ctx.root / "content" / "pages"
    for f in sorted(cdir.rglob("*.md")) if cdir.is_dir() else []:
        fm, body = parse_md(f)
        out_rel = out_path_for(f.relative_to(cdir))
        variables = {"page": fm, "body": md(body), "nav_current": page_dir_url(out_rel)}
        for key in ("draft", "noindex", "lang"):
            if key in fm:
                variables[key] = fm[key]
        write_page(ctx, env, fm.get("layout") or "op/page.html.j2", out_rel, variables)
    if hooks is not None and hasattr(hooks, "pages"):
        for out_dir, template, page_vars in hooks.pages(ctx):
            out_rel = out_dir.strip("/") + "/index.html" if out_dir.strip("/") else "index.html"
            write_page(ctx, env, template, out_rel, {"nav_current": page_dir_url(out_rel), **page_vars})
    html = link_page_css(render(env, "op/404.html.j2", "404.html",
                                {**base_vars(ctx), "page_absolute": True, "noindex": True, "draft": "none",
                                 "page_url": "404.html"}))
    (ctx.out / "404.html").write_text(html, encoding="utf-8")


def copy_tree(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))


def copy_static(ctx: Ctx) -> None:
    shutil.copytree(OPSITE / "ui", ctx.out / "ui", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "og"))
    og = OPSITE / "ui" / "brand" / "og" / f"{ctx.site['repo']}.png"
    if og.is_file():
        (ctx.out / "ui" / "brand" / "og").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(og, ctx.out / "ui" / "brand" / "og" / og.name)
    copy_tree(ctx.root / "assets", ctx.out / "assets")
    copy_tree(ctx.root / "lib", ctx.out / "lib")
    copy_tree(ctx.root / "tools", ctx.out / "tools")
    vroot = ctx.root / "vendor"
    deps = read_yaml(ctx.root / "deps.yaml") if (ctx.root / "deps.yaml").is_file() else {}
    for repo_dir in sorted(vroot.iterdir()) if vroot.is_dir() else []:
        for kind in ("lib", "tools"):
            copy_tree(repo_dir / kind, ctx.out / "vendor" / repo_dir.name / kind)
        for name in ((deps or {}).get(repo_dir.name) or {}).get("datasets") or []:
            src = repo_dir / "v1" / f"{name}.json"
            if src.is_file():
                dest = ctx.out / "vendor" / repo_dir.name / "v1" / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)


def _dataset(ctx: Ctx, repo: str, name: str) -> dict | None:
    if ctx.site["repo"] == repo:
        return ctx.data.get(name)
    return ctx.vendor.get(repo, {}).get(name)


def region_line(item: dict, sources: dict) -> dict:
    number = tel_display(item.get("number_display") or item.get("number_raw") or "")
    if item.get("ext_text"):
        number += f", {item['ext_text']}"
    what = item.get("agency_name") or ""
    if item.get("topic_text"):
        what = f"{what}. {item['topic_text']}" if what else item["topic_text"]
    src = sources.get(item.get("source_ref"), {})
    source = src.get("title", "")
    if item.get("assured_date"):
        source = f"{source}, сведения от {ru_date(item['assured_date'])}" if source else ""
    return {"tel": item.get("tel", ""), "number": number, "what": what, "hours": item.get("hours_text") or "",
            "is_24x7": item.get("is_24x7") is True, "verified": item.get("verified") is True,
            "verified_at": item.get("verified_at"), "roles": item.get("roles") or [], "source": source}


def write_region_lines(ctx: Ctx) -> int:
    lines = _dataset(ctx, "pal-directory", "region-lines")
    regions = _dataset(ctx, "pal-directory", "regions")
    if not lines or not regions:
        return 0
    sources = {s.get("id"): s for s in lines.get("source") or []}
    by_region: dict[str, list] = {}
    for item in lines["items"]:
        if item.get("hidden") is True or item.get("origin") == "synthetic":
            continue
        by_region.setdefault(item.get("region_id"), []).append(region_line(item, sources))
    out = ctx.out / "region-lines"
    out.mkdir(parents=True, exist_ok=True)
    for r in regions["items"]:
        doc = {"region": r["id"], "name": r.get("name", r["id"]), "data_date": lines["data_date"],
               "stale_after_days": lines.get("stale_after_days", 90), "lines": by_region.get(r["id"], [])}
        (out / f"{r['id'].lower()}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                                                     encoding="utf-8")
    return len(regions["items"])


CSS_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _minify_css_part(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([{};,>])\s*", r"\1", text)
    text = re.sub(r":\s+", ":", text)
    return text.replace(";}", "}")


def minify_css(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, pos = [], 0
    for m in CSS_STRING.finditer(css):
        out.append(_minify_css_part(css[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_minify_css_part(css[pos:]))
    return "".join(out).strip() + "\n"


def minify_site_css(ctx: Ctx) -> None:
    for path in sorted((ctx.out / "ui" / "css").glob("*.css")):
        path.write_text(minify_css(path.read_text(encoding="utf-8")), encoding="utf-8")


def write_sprite(ctx: Ctx) -> None:
    dest = ctx.out / ICON_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(sprite(ctx.icons_used | {"monitor", "sun", "moon"}), encoding="utf-8")
    if any(ICON_FILE_ALL in (ctx.out / p).read_text(encoding="utf-8") for p in ctx.pages):
        (ctx.out / ICON_FILE_ALL).write_text(sprite(icon_names()), encoding="utf-8")


def write_region_index(ctx: Ctx) -> None:
    regions = _dataset(ctx, "pal-directory", "regions")
    if not regions:
        return
    rows = [{"id": r["id"], "name": r.get("name", r["id"]), "capital": r.get("capital") or "",
             "aliases": r.get("aliases") or []} for r in regions["items"]]
    (ctx.out / "region-index.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
                                               encoding="utf-8")


CORE_CSS = re.compile(r'<link rel="stylesheet" href="([^"]*)ui/css/components\.css">')
PAGE_CSS = [
    ("forms.css", re.compile(r'class="[^"]*\bop-(?:field|input|choice|date|search|steps)\b|<(?:form|input|select|textarea)\b')),
    ("now.css", re.compile(r'class="[^"]*\bop-(?:now|row|rows)\b')),
    ("extra.css", re.compile(r'class="[^"]*\bop-(?:dialog|toc|dl|card|quote|cite)\b')),
    ("region.css", re.compile(r'class="[^"]*\bop-region\b')),
]


def link_page_css(html: str) -> str:
    m = CORE_CSS.search(html)
    if not m:
        return html
    extra = "".join(f'\n<link rel="stylesheet" href="{m.group(1)}ui/css/{name}">'
                    for name, rx in PAGE_CSS if rx.search(html))
    return html[:m.end()] + extra + html[m.end():] if extra else html


def write_data(ctx: Ctx) -> list[dict]:
    if not ctx.data:
        return []
    ddir = ctx.out / "data" / "v1"
    ddir.mkdir(parents=True, exist_ok=True)
    index = []
    for name, env in sorted(ctx.data.items()):
        raw = json.dumps(env, ensure_ascii=False, indent=1).encode("utf-8")
        if len(raw) > MAX_DATASET:
            raise BuildError(msg("dataset_too_big", name=name, size=len(raw)))
        (ddir / f"{name}.json").write_bytes(raw)
        shutil.copyfile(ctx.root / "data" / "schema" / f"{name}.schema.json", ddir / f"{name}.schema.json")
        index.append({"name": name, "path": f"{name}.json", "schema": f"{name}.schema.json",
                      "schema_version": env["schema_version"], "version": env["version"],
                      "data_date": env["data_date"], "content_sha256": env["content_sha256"],
                      "bytes": len(raw), "items": len(env["items"]),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    idx = {"repo": ctx.site["repo"], "generated_at": ctx.built_at, "opsite_version": ctx.opsite_version,
           "datasets": index}
    (ddir / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def page_abs_url(site: dict, out_rel: str) -> str:
    return site["site_url"] + site["base"] + page_dir_url(out_rel)


def sitemap_xml(site: dict, pages: list[str], lastmod: str) -> str:
    rows = [f"<url><loc>{xml_escape(page_abs_url(site, p))}</loc><lastmod>{lastmod}</lastmod></url>"
            for p in sorted(pages)]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n")


def robots_txt(site: dict, tools: list[dict]) -> str:
    lines = ["User-agent: *", "Allow: /", ""]
    lines.append(f"Sitemap: {site['site_url']}/sitemap.xml")
    for t in tools:
        lines.append(f"Sitemap: {site['site_url']}/{t['repo']}/sitemap.xml")
    return "\n".join(lines) + "\n"


def write_meta(ctx: Ctx, index: list[dict]) -> None:
    indexed = [p for p in ctx.pages if p not in ctx.noindex]
    (ctx.out / "sitemap.xml").write_text(sitemap_xml(ctx.site, indexed, ctx.built_at[:10]), encoding="utf-8")
    build = {"repo": ctx.site["repo"], "opsite_version": ctx.opsite_version, "built_at": ctx.built_at,
             "datasets": [{"name": d["name"], "version": d["version"], "data_date": d["data_date"]} for d in index]}
    if ctx.commit:
        build["commit"] = ctx.commit
    (ctx.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    if ctx.site["repo"] == HUB:
        (ctx.out / "ui" / "VERSION").write_text(ctx.opsite_version + "\n", encoding="utf-8")
        (ctx.out / "robots.txt").write_text(robots_txt(ctx.site, ctx.tools), encoding="utf-8")
        shutil.copyfile(OPSITE / "situations.json", ctx.out / "situations.json")
    (ctx.out / ".nojekyll").write_text("", encoding="utf-8")


def build(root: Path, org_root: str = "/") -> Ctx:
    t0 = time.monotonic()
    root = root.resolve()
    site = load_site(root)
    site["is_hub"] = site["repo"] == HUB
    site["has_css"] = (root / "assets" / "css" / f"{site['prefix']}.css").is_file()
    ctx = Ctx(root=root, site=site, out=root / "_site",
              opsite_version=(OPSITE / "VERSION").read_text().strip(), built_at=now_utc())
    sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    ctx.commit = sha[:7] if re.fullmatch(r"[0-9a-f]{7,40}", sha) else ""
    load_data(ctx)
    load_vendor(ctx)
    load_content(ctx)
    hooks = _import(root, "site_hooks", "site_hooks.py")
    if hooks is not None and hasattr(hooks, "context"):
        site.update(hooks.context(ctx) or {})
    if ctx.out.exists():
        shutil.rmtree(ctx.out)
    ctx.out.mkdir(parents=True)
    env = make_env(ctx, org_root)
    render_pages(ctx, env, hooks)
    copy_static(ctx)
    minify_site_css(ctx)
    write_sprite(ctx)
    write_region_lines(ctx)
    write_region_index(ctx)
    index = write_data(ctx)
    if site.get("pwa"):
        sw.write(ctx, env)
    write_meta(ctx, index)
    print(msg("build_ok", pages=len(ctx.pages), datasets=len(index), seconds=time.monotonic() - t0, out=ctx.out))
    return ctx
