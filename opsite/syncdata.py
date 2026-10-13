import hashlib
import json
import os
import urllib.request
from pathlib import Path

import jsonschema
import yaml

from .data import content_sha256, now_utc, read_yaml
from .messages_ru import msg

PAGES = "https://openpalliative.github.io/"
UA = "openpalliative-sync (+https://github.com/openpalliative)"


class Unavailable(Exception):
    pass


def _reader(mode: str, root: Path, repo: str):
    org_dir = Path(os.environ.get("OP_ORG_DIR", root.parent))

    def read(rel: str) -> bytes:
        if mode == "local":
            p = org_dir / repo / "_site" / rel
            if not p.is_file():
                raise Unavailable(f"нет файла {p}")
            return p.read_bytes()
        req = urllib.request.Request(f"{PAGES}{repo}/{rel}", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except OSError as e:
            raise Unavailable(str(e)) from e
    return read


def sync_repo(root: Path, repo: str, spec: dict, mode: str) -> dict:
    read = _reader(mode, root, repo)
    index = json.loads(read("data/v1/index.json"))
    by_name = {d["name"]: d for d in index["datasets"]}
    want_major = int(spec.get("major", "1"))
    files: dict[str, bytes] = {}
    envelopes: set[str] = set()
    shas = {}
    for name in spec.get("datasets", []):
        entry = by_name.get(name)
        if entry is None:
            raise Unavailable(f"в index.json нет датасета {name}")
        got_major = int(entry["schema_version"].split(".")[0])
        if got_major != want_major:
            raise SystemExit(msg("sync_major", repo=repo, got=got_major, want=want_major))
        raw = read(f"data/v1/{entry['path']}")
        if entry.get("sha256") and hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise SystemExit(msg("sync_sha", repo=repo, file=entry["path"]))
        env = json.loads(raw)
        if content_sha256(env["source"], env["items"]) != env["content_sha256"]:
            raise SystemExit(msg("sync_sha", repo=repo, file=entry["path"]))
        schema_raw = read(f"data/v1/{entry['schema']}")
        jsonschema.Draft202012Validator(json.loads(schema_raw)).validate(env)
        files[f"v1/{entry['path']}"] = raw
        envelopes.add(f"v1/{entry['path']}")
        files[f"v1/{entry['schema']}"] = schema_raw
        shas[name] = env["content_sha256"]
        spec_version, spec_date = env["version"], env["data_date"]
    for kind in ("lib", "tools"):
        for fname in spec.get(kind, []):
            files[f"{kind}/{fname}"] = read(f"{kind}/{fname}")
    files["v1/index.json"] = json.dumps(index, ensure_ascii=False, indent=1).encode("utf-8")
    vdir = root / "vendor" / repo
    unchanged = spec.get("content_sha256") == shas and all(
        (vdir / rel).is_file() and (rel in envelopes or (vdir / rel).read_bytes() == data)
        for rel, data in files.items() if not rel.startswith("v1/index"))
    if unchanged:
        print(msg("sync_same", repo=repo))
        return spec
    for rel, data in files.items():
        dest = vdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    if shas:
        spec.update(version=spec_version, data_date=spec_date)
    spec.update(content_sha256=shas, synced_at=now_utc())
    print(msg("sync_updated", repo=repo, version=spec.get("version", "-"), data_date=spec.get("data_date", "-")))
    return spec


def run(root: Path, mode: str = "local", strict: bool = False, only: str | None = None) -> int:
    root = root.resolve()
    deps_path = root / "deps.yaml"
    if not deps_path.is_file():
        return 0
    deps = read_yaml(deps_path) or {}
    failed = changed = False
    for repo, spec in deps.items():
        if only and repo != only:
            continue
        try:
            new = sync_repo(root, repo, dict(spec or {}), mode)
        except Unavailable as e:
            print(msg("sync_unavailable", repo=repo, error=e))
            failed = True
            continue
        changed |= new != spec
        deps[repo] = new
    if changed:
        for spec in deps.values():
            if isinstance(spec, dict) and str(spec.get("major", "")).isdigit():
                spec["major"] = int(spec["major"])
        deps_path.write_text(yaml.safe_dump(deps, allow_unicode=True, sort_keys=False, default_flow_style=None),
                             encoding="utf-8")
    return 1 if failed and strict else 0
