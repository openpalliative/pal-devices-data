import argparse
import datetime as dt
import hashlib
import os
import shutil
import sys
from pathlib import Path

import yaml

from pipeline import net

PDF_URL = "http://publication.pravo.gov.ru/file/pdf?eoNumber={eo}"
TSV_HEAD = ["eoNumber", "url", "sha256", "bytes", "retrieved_at"]
LOCAL_NAMES = {
    "0001202508130021": ["pn/n398.pdf"],
    "0001202505290031": ["pn/208n.pdf"],
}


def root_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def read_sources_tsv(root: Path) -> dict:
    path = root / "raw" / "SOURCES.tsv"
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            parts = line.split("\t")
            rows[parts[0]] = dict(zip(TSV_HEAD, parts))
    return rows


def write_sources_tsv(root: Path, rows: dict) -> None:
    path = root / "raw" / "SOURCES.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(TSV_HEAD)] + ["\t".join(rows[k][h] for h in TSV_HEAD) for k in sorted(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def expected_sha(root: Path, eo: str) -> str:
    for s in yaml.load((root / "data" / "sources.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader):
        if s.get("eoNumber") == eo and s.get("sha256"):
            return s["sha256"]
    return read_sources_tsv(root).get(eo, {}).get("sha256", "")


def local_candidates(eo: str) -> list[Path]:
    scratch = os.environ.get("OP_SCRATCH")
    if not scratch:
        return []
    base = Path(scratch)
    names = LOCAL_NAMES.get(eo, []) + [f"dvs/{eo}.pdf", f"{eo}.pdf"]
    return [base / n for n in names]


def fetch(eo: str, root: Path | None = None, *, get=net.get, today: str | None = None) -> Path:
    root = root or root_dir()
    cache = root / "raw" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{eo}.pdf"
    want = expected_sha(root, eo)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    cached = out.is_file() and (not want or sha(out.read_bytes()) == want)
    for cand in [] if cached else local_candidates(eo):
        if cand.is_file() and (not want or sha(cand.read_bytes()) == want):
            shutil.copyfile(cand, out)
            break
    else:
        if cached:
            return _record(root, eo, out, today)
        url = PDF_URL.format(eo=eo)
        body = get(url)
        if not body.startswith(b"%PDF"):
            raise net.SourceDown(f"{url}: ответ не похож на PDF")
        if want and sha(body) != want:
            print(f"{eo}: sha256 скачанного файла отличается от записанного, возможно, публикацию заменили", file=sys.stderr)
        out.write_bytes(body)
    return _record(root, eo, out, today)


def _record(root: Path, eo: str, out: Path, today: str | None) -> Path:
    data = out.read_bytes()
    rows = read_sources_tsv(root)
    old = rows.get(eo, {})
    digest = hashlib.sha256(data).hexdigest()
    rows[eo] = {"eoNumber": eo, "url": f"http://publication.pravo.gov.ru/document/{eo}", "sha256": digest,
                "bytes": str(len(data)),
                "retrieved_at": old["retrieved_at"] if old.get("sha256") == digest else (today or dt.date.today().isoformat())}
    write_sources_tsv(root, rows)
    return out


def known_eos(root: Path) -> list[str]:
    src = yaml.load((root / "data" / "sources.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return [s["eoNumber"] for s in src if s.get("eoNumber") and s.get("sha256")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.fetch_pravo")
    ap.add_argument("eo", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    root = root_dir()
    eos = known_eos(root) if a.all else a.eo
    if not eos:
        ap.error("укажите eoNumber или --all")
    for eo in eos:
        p = fetch(eo, root)
        print(f"{eo} -> {p.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
