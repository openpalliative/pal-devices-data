import json
import re
from pathlib import Path

from pipeline.common import read_csv, read_yaml

STOP = [(re.compile("\u00ae"), "знак товарного знака"), (re.compile("\u2122"), "знак товарного знака"),
        (re.compile(r"(?<![А-Яа-яЁё])руб(?:\.|л[а-я]*|(?![А-Яа-яЁё]))"), "цена"), (re.compile("\u20bd"), "цена")]
MODEL = re.compile(r"\b[A-Z]{2,}\d")
TERR = re.compile(r"(?<![А-Яа-яЁё])(ДНР|ЛНР)(?![А-Яа-яЁё])|[Дд]онецк|[Лл]уганск|[Зз]апорожск|[Хх]ерсонск|(?<![А-Яа-яЁё])[Кк]рым(?!ск|ов)|[Сс]евастопол")
LONG_DASH = re.compile("[\u2013\u2014]")
UNPUBLISHED = {"nutrition_items.csv", "nutrition_items_manual.yaml"}
ACT_NUMBER = re.compile(r"№\s*\d+|\b\d+-ФЗ\b|(?<![\d-])\d{2,4}\s?н(?![А-Яа-яЁё])|\b\d{2,5}-р(?![А-Яа-яЁё])")


def data_files(root: Path) -> list[Path]:
    files = [p for p in (root / "data").rglob("*") if p.is_file() and p.suffix in (".csv", ".yaml", ".json")
             and "schema" not in p.parts and p.name not in UNPUBLISHED]
    site = root / "_site" / "data"
    if site.is_dir():
        files += [p for p in site.rglob("*.json") if not p.name.endswith(".schema.json")]
    return files


def test_stoplist_in_data(root):
    for p in data_files(root):
        text = p.read_text(encoding="utf-8")
        for rx, why in STOP:
            assert not rx.search(text), f"{p}: {why}"
        bare = text.replace("CC0-1.0", "").replace("CC-BY-4.0", "")
        assert not MODEL.search(bare), f"{p}: похоже на модель {MODEL.search(bare).group(0)}"
        assert not TERR.search(text), f"{p}: исключённая территория"


def prose_fields(root: Path):
    for c in read_yaml(root / "data" / "channels.yaml"):
        yield "channels", c["id"], c["title"] + " " + c["sentence"] + " " + c.get("body", "")
    for w in read_yaml(root / "data" / "warnings.yaml"):
        yield "warnings", w["id"], w["text"]
    for a in read_csv(root / "data" / "aliases.csv"):
        yield "aliases", a["id"], a["alias"] + " " + a["seen_in"]
    for s in read_yaml(root / "data" / "sources.yaml"):
        yield "sources", s["id"], s["short_title"]
    for r in read_csv(root / "data" / "398n.csv"):
        yield "398n", r["code"], r["note"]


def test_no_act_numbers_or_long_dashes_in_prose(root):
    for name, key, text in prose_fields(root):
        assert not ACT_NUMBER.search(text), f"{name}/{key}: номер акта литералом: {ACT_NUMBER.search(text).group(0)}"
        assert not LONG_DASH.search(text), f"{name}/{key}: длинное тире"


def test_no_long_dashes_anywhere_in_data(root):
    for p in data_files(root):
        if p.parent.name == "snapshots":
            continue
        assert not LONG_DASH.search(p.read_text(encoding="utf-8")), p


def test_pipeline_hosts_allowed(root):
    allowed = {"publication.pravo.gov.ru", "roszdravnadzor.gov.ru", "github.com"}
    for p in (root / "pipeline").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for host in re.findall(r"https?://([a-zA-Z0-9.-]+)", text):
            assert host in allowed, f"{p.name}: хост {host}"
        assert "sfr.gov.ru" not in text and "ktsr" not in text


def test_no_hour_numbers_in_deadline_blocks(root):
    site = root / "_site"
    if not site.is_dir():
        return
    rx = re.compile(r"\d+\s*(-\s*\d+\s*)?час")
    block = re.compile(r'<section[^>]*(?:id|class)="[^"]*(?:deadline|srok)[^"]*"[^>]*>(.*?)</section>', re.S)
    for p in site.rglob("*.html"):
        for m in block.finditer(p.read_text(encoding="utf-8")):
            assert not rx.search(re.sub(r"<[^>]+>", " ", m.group(1))), p
