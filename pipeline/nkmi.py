import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from pipeline import net
from pipeline.common import words

DATASET = "7710537160-mi_types"
BASE = f"https://roszdravnadzor.gov.ru/opendata/{DATASET}/"
META_URL = BASE + "meta.csv"
STRUCTURE = "20180615"
MAX_XML_BYTES = 100 * 1024 * 1024
DATA_KEY = re.compile(r"^data-(\d{8})-structure-(\d{8})$")


class FormatChanged(Exception):
    pass


def parse_meta(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][:2] != ["property", "value"]:
        raise FormatChanged("meta.csv: нет заголовка property,value")
    meta = {"modified": "", "valid": "", "data": [], "structures": {}}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key, value = row[0].strip(), row[1].strip()
        if key in ("modified", "valid"):
            meta[key] = value
        m = DATA_KEY.match(key)
        if m:
            meta["data"].append({"version": m.group(1), "structure": m.group(2), "url": value})
        elif key.startswith("structure-"):
            meta["structures"][key.removeprefix("structure-")] = value
    if not meta["data"]:
        raise FormatChanged("meta.csv: нет строк data-*")
    meta["data"].sort(key=lambda d: d["version"], reverse=True)
    return meta


def latest(meta: dict) -> dict:
    return meta["data"][0]


def parse_xml(stream) -> dict[str, str]:
    out = {}
    seen_root = False
    for event, el in ET.iterparse(stream, events=("start", "end")):
        if event == "start":
            if not seen_root:
                if el.tag != "classificator_list":
                    raise FormatChanged(f"XML: корневой элемент {el.tag}, ожидался classificator_list")
                seen_root = True
            continue
        if el.tag == "classificator":
            code = (el.findtext("code") or "").strip()
            name = re.sub(r"\s+", " ", (el.findtext("name") or "").strip())
            if not code or not name:
                raise FormatChanged("XML: у вида нет code или name")
            out[code] = name
            el.clear()
    if not out:
        raise FormatChanged("XML: ни одного вида")
    return out


def parse_descriptions(stream, codes: set[str]) -> dict[str, tuple[str, str]]:
    out = {}
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag == "classificator":
            code = (el.findtext("code") or "").strip()
            if code in codes:
                out[code] = (re.sub(r"\s+", " ", (el.findtext("name") or "").strip()),
                             re.sub(r"\s+", " ", (el.findtext("description") or "").strip()))
            el.clear()
    return out


def write_descriptions(root: Path, data: bytes, version: str) -> int:
    codes = set(tracked_codes(root))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
        with z.open(xmls[0]) as f:
            found = parse_descriptions(f, codes)
    p = root / "raw" / "nkmi_descriptions.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["code", "name", "description", "version"])
        for code in sorted(found):
            w.writerow([code, *found[code], version])
    return len(found)


def read_descriptions(root: Path) -> dict[str, str]:
    p = root / "raw" / "nkmi_descriptions.csv"
    if not p.is_file():
        return {}
    with open(p, encoding="utf-8", newline="") as f:
        return {r["code"]: r["description"] for r in csv.DictReader(f)}


def parse_zip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if len(xmls) != 1:
            raise FormatChanged(f"zip: ожидался один XML, найдено {len(xmls)}")
        if z.getinfo(xmls[0]).file_size > MAX_XML_BYTES:
            raise FormatChanged(f"zip: XML больше {MAX_XML_BYTES // (1024 * 1024)} МБ после распаковки")
        with z.open(xmls[0]) as f:
            return parse_xml(f)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def tracked_codes(root: Path) -> list[str]:
    codes = []
    for name in ("398n.csv", "348n.csv"):
        p = root / "data" / name
        if p.is_file():
            with open(p, encoding="utf-8", newline="") as f:
                codes += [r["code"] for r in csv.DictReader(f)]
    for name in ("scan_pages.yaml",):
        p = root / "data" / "review" / name
        if p.is_file():
            codes += re.findall(r'"(\d{6})"', p.read_text(encoding="utf-8"))
    return sorted(set(codes))


def snapshot_path(root: Path) -> Path:
    return root / "data" / "snapshots" / "nkmi.json"


def load_snapshot(root: Path) -> dict | None:
    p = snapshot_path(root)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def load_snapshot_codes(root: Path) -> set[str]:
    s = load_snapshot(root)
    return set(s["codes"]) if s else set()


def build_snapshot(*, version: str, zip_url: str, zip_sha: str, xsd_sha: str, structure: str,
                   kinds: dict[str, str], codes: list[str], history: dict | None = None,
                   history_versions: list[str] | None = None) -> dict:
    snap = {
        "version": version,
        "zip_url": zip_url,
        "zip_sha256": zip_sha,
        "xsd_sha256": xsd_sha,
        "structure": structure,
        "total_kinds": len(kinds),
        "codes": {c: kinds[c] for c in sorted(codes) if c in kinds},
        "absent": [c for c in sorted(codes) if c not in kinds],
    }
    if history_versions:
        snap["history_versions"] = history_versions
        snap["history"] = history or {}
    return snap


def build_history(by_version: dict[str, dict[str, str]], codes: list[str]) -> dict[str, list[dict]]:
    versions = sorted(by_version)
    out = {}
    for code in sorted(codes):
        points, last = [], object()
        for v in versions:
            name = by_version[v].get(code)
            if name != last:
                points.append({"version": v, "name": name})
                last = name
        if len(points) > 1 or points and points[0]["name"] is None:
            out[code] = points
    return out


def extend_history(snap: dict, version: str, kinds: dict[str, str], codes: list[str]) -> tuple[dict, list[str]]:
    versions = list(snap.get("history_versions") or [snap["version"]])
    history = {c: list(p) for c, p in (snap.get("history") or {}).items()}
    if version in versions:
        return history, versions
    known = set(snap["codes"]) | set(snap.get("absent", []))
    for code in sorted(c for c in codes if c in known):
        before, now = snap["codes"].get(code), kinds.get(code)
        if now != before:
            history.setdefault(code, [{"version": versions[0], "name": before}]).append({"version": version, "name": now})
    return history, versions + [version]


def first_change(points: list[dict], name: str) -> str | None:
    seen = False
    for p in points:
        if p["name"] is not None and words(p["name"]) == words(name):
            seen = True
        elif seen:
            return p["version"]
    return None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def write_subset(root: Path, snap: dict) -> None:
    p = root / "raw" / "nkmi_subset.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["code", "name", "version"])
        for code, name in snap["codes"].items():
            w.writerow([code, name, snap["version"]])


def cache_dir(root: Path) -> Path:
    return root / "raw" / "cache" / "nkmi"


def version_zip(root: Path, entry: dict, *, get=net.get) -> bytes:
    p = cache_dir(root) / f"data-{entry['version']}.zip"
    if p.is_file():
        return p.read_bytes()
    data = get(entry["url"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def all_versions(root: Path, meta: dict, *, get=net.get) -> dict[str, dict[str, str]]:
    out = {}
    for entry in meta["data"]:
        if entry["structure"] != STRUCTURE:
            continue
        out[entry["version"]] = parse_zip(version_zip(root, entry, get=get))
    return out


def refresh(root: Path, *, get=net.get, zip_path: Path | None = None, with_history: bool = False) -> dict:
    meta = parse_meta(get(META_URL).decode("utf-8-sig"))
    top = latest(meta)
    if top["structure"] != STRUCTURE:
        raise FormatChanged(f"структура набора сменилась: {top['structure']}")
    xsd_url = meta["structures"].get(STRUCTURE)
    if not xsd_url:
        raise FormatChanged("meta.csv: нет ссылки на схему структуры")
    xsd = get(xsd_url)
    data = zip_path.read_bytes() if zip_path else version_zip(root, top, get=get)
    kinds = parse_zip(data)
    codes = tracked_codes(root)
    history, versions = None, None
    if with_history:
        by_version = all_versions(root, meta, get=get)
        by_version[top["version"]] = kinds
        history, versions = build_history(by_version, codes), sorted(by_version)
    else:
        prev = load_snapshot(root) or {}
        if prev.get("history_versions"):
            history, versions = prev["history"], prev["history_versions"]
            if prev.get("version") != top["version"]:
                history, versions = extend_history(prev, top["version"], kinds, codes)
    snap = build_snapshot(version=top["version"], zip_url=top["url"], zip_sha=sha256(data), xsd_sha=sha256(xsd),
                          structure=top["structure"], kinds=kinds, codes=codes, history=history,
                          history_versions=versions)
    write_json(snapshot_path(root), snap)
    write_subset(root, snap)
    return snap


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    ap = argparse.ArgumentParser(prog="python -m pipeline.nkmi")
    ap.add_argument("--zip", type=Path, help="уже скачанный zip набора той же версии")
    ap.add_argument("--history", action="store_true", help="скачать все версии из meta.csv и пересчитать историю имён")
    ap.add_argument("--descriptions", action="store_true", help="записать описания видов наших кодов в raw/nkmi_descriptions.csv")
    a = ap.parse_args(argv)
    root = root_dir()
    if a.descriptions:
        snap = load_snapshot(root)
        data = version_zip(root, {"version": snap["version"], "url": snap["zip_url"]})
        print(f"описаний записано: {write_descriptions(root, data, snap['version'])}")
        return 0
    snap = refresh(root, zip_path=a.zip, with_history=a.history)
    print(f"НКМИ {snap['version']}: видов {snap['total_kinds']}, наших кодов найдено {len(snap['codes'])}, "
          f"нет {len(snap['absent'])} ({dt.date.today().isoformat()})")
    for code, points in sorted((snap.get("history") or {}).items()):
        print(f"  {code}: " + "; ".join(f"{p['version']} {p['name'] or 'нет'}" for p in points))
    return 0


if __name__ == "__main__":
    sys.exit(main())
