import csv
import re
from pathlib import Path

import yaml

EO_398N = "0001202508130021"
EO_348N = "0001201907010015"
WORD = re.compile(r"[а-яa-z0-9]+")


def read_yaml(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


def norm_text(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def words(s: str) -> set[str]:
    return set(WORD.findall(norm_text(s)))


def nkmi_status(name_in_act: str, name_now: str | None) -> str:
    if name_now is None:
        return "missing"
    a, b = words(name_in_act), words(name_now)
    if a == b:
        return "present"
    if a and b and len(a & b) / len(a | b) >= 0.5:
        return "renamed"
    return "mismatch"


def scan_pages(root: Path, eo: str) -> list[dict]:
    return [p for p in read_yaml(root / "data" / "review" / "scan_pages.yaml") if p["eo"] == eo]
