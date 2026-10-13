import hashlib
from pathlib import Path

from .render import render

SKIP_SUFFIXES = (".schema.json", ".map")
SKIP_NAMES = {"sw.js", "build.json", "sitemap.txt", "sitemap.xml", "404.html", ".nojekyll", "VERSION", "OFL.txt", "LICENSE"}


def precache_list(out: Path) -> list[str]:
    files = []
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.name in SKIP_NAMES or p.name.endswith(SKIP_SUFFIXES):
            continue
        rel = p.relative_to(out).as_posix()
        if rel.startswith("ui/brand/") and not rel.endswith(("favicon.svg", "icon-192.png")):
            continue
        if rel.startswith("region-lines/") or rel in ("sitemap.xml", "robots.txt", "situations.json"):
            continue
        if rel.endswith("index.html"):
            rel = rel[: -len("index.html")] or "./"
        files.append(rel)
    return files


def write(ctx, env) -> None:
    manifest = render(env, "op/manifest.webmanifest.j2", "manifest.webmanifest",
                      {"site": ctx.site, "page_absolute": False})
    (ctx.out / "manifest.webmanifest").write_text(manifest, encoding="utf-8")
    files = precache_list(ctx.out)
    digest = hashlib.sha256()
    for rel in files:
        target = ctx.out / ("index.html" if rel == "./" else rel + "index.html" if rel.endswith("/") else rel)
        digest.update(rel.encode())
        digest.update(target.read_bytes() if target.is_file() else b"")
    version = f"{ctx.site['repo']}-{digest.hexdigest()[:12]}"
    js = render(env, "op/sw.js.j2", "sw.js", {"site": ctx.site, "files": files, "version": version,
                                              "page_absolute": False})
    (ctx.out / "sw.js").write_text(js, encoding="utf-8")
