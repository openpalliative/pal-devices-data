import argparse
import json
import shutil
import sys
from pathlib import Path

from . import check, syncdata
from .build import build, check_situations
from .data import OPSITE, BuildError, read_yaml
from .lint import lint_sources
from .messages_ru import msg
from .serve import serve, serve_dir


def write_tools_js() -> None:
    tools = read_yaml(OPSITE / "tools.yaml")["tools"]
    prefixes = ["op"] + [t["prefix"] for t in tools if t.get("prefix")]
    dbs = [f"op-{t['repo']}" for t in tools]
    text = (f"export const PREFIXES = {json.dumps(prefixes)};\n"
            f"export const DATABASES = {json.dumps(dbs)};\n")
    target = OPSITE / "ui" / "js" / "tools.js"
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")


def cmd_manifest(root: Path) -> int:
    if (root / "opsite").resolve() == OPSITE:
        src = root / "content" / "now.yaml"
        if src.is_file():
            shutil.copyfile(src, OPSITE / "now.yaml")
        sit = root / "content" / "situations.yaml"
        if sit.is_file():
            raw = read_yaml(sit)
            check_situations(raw)
            items = [{k: s.get(k, "") for k in ("id", "title", "hint", "icon")} | {"urgent": s.get("urgent") == "true"}
                     for s in raw.get("situations", [])]
            (OPSITE / "situations.json").write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
    write_tools_js()
    if check.manifest_changed(OPSITE):
        check.bump_version(OPSITE)
    count = check.write_manifest(OPSITE)
    print(msg("manifest_ok", version=(OPSITE / "VERSION").read_text().strip(), count=count))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="opsite", description="Сборка и проверка сайтов openpalliative")
    p.add_argument("--root", default=".", help="корень репо")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="собрать _site/")
    b.add_argument("--org-root", default="/", help="префикс для ссылок в соседние репо")
    c = sub.add_parser("check", help="линт текста, ссылки, сеть, бюджеты, манифест")
    c.add_argument("--ci", action="store_true")
    c.add_argument("--update-golden", action="store_true")
    c.add_argument("--org", help="проверить межрепные ссылки в общей сборке, например ../_site")
    s = sub.add_parser("serve", help="отдать _site/ по пути как на Pages")
    s.add_argument("--port", type=int)
    s.add_argument("--no-open", action="store_true")
    s.add_argument("--dir", help="отдать готовую папку как есть, например общий _site")
    d = sub.add_parser("sync-data", help="забрать снимки соседей в vendor/")
    d.add_argument("--from", dest="mode", choices=["local", "pages"], default="local")
    d.add_argument("--strict", action="store_true")
    d.add_argument("--only")
    sub.add_parser("lint", help="только линт исходников")
    sub.add_parser("manifest", help="в хабе: обновить opsite/now.yaml и MANIFEST.sha256")
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    try:
        if a.cmd == "build":
            build(root, a.org_root)
            return 0
        if a.cmd == "check":
            if a.org:
                return check.check_org(Path(a.org).resolve())
            return check.run(root, ci=a.ci, update_golden=a.update_golden)
        if a.cmd == "serve":
            if a.dir:
                print(msg("serve", repo="все сайты", url=f"http://localhost:{a.port or 8080}/"), flush=True)
                serve_dir(Path(a.dir).resolve(), a.port or 8080)
                return 0
            serve(root, a.port)
            return 0
        if a.cmd == "sync-data":
            return syncdata.run(root, a.mode, a.strict, a.only)
        if a.cmd == "lint":
            found = lint_sources(root)
            for f in found:
                print(f)
            return 1 if any(f.level == "error" for f in found) else 0
        if a.cmd == "manifest":
            return cmd_manifest(root)
    except BuildError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
