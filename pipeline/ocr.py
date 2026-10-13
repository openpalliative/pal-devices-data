import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = re.compile(r"(?<!\d)\d{6}(?!\d)")
ROTATIONS = (0, 90, 270)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"нет программы {tool}: поставьте poppler и tesseract с языком rus")
    return path


def render(pdf: Path, page: int, out_png: Path, dpi: int = 300) -> Path:
    prefix = out_png.with_suffix("")
    subprocess.run([need("pdftoppm"), "-r", str(dpi), "-png", "-singlefile", "-f", str(page), "-l", str(page),
                    str(pdf), str(prefix)], check=True, capture_output=True)
    return out_png


def rotate(png: Path, degrees: int, out: Path) -> Path:
    if degrees == 0:
        return png
    sips = shutil.which("sips")
    if sips:
        subprocess.run([sips, "-r", str(degrees), str(png), "--out", str(out)], check=True, capture_output=True)
        return out
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run([magick, str(png), "-rotate", str(degrees), str(out)], check=True, capture_output=True)
        return out
    raise RuntimeError("для поворота страницы нужна программа sips или ImageMagick")


def tesseract(png: Path, psm: int = 6) -> str:
    r = subprocess.run([need("tesseract"), str(png), "-", "-l", "rus", "--psm", str(psm)],
                       check=True, capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def score(text: str, known: set[str] | None) -> int:
    codes = CODE.findall(text)
    return len([c for c in codes if c in known]) if known else len(codes)


def ocr_page(pdf: Path, page: int, *, known_codes: set[str] | None = None, rotations=ROTATIONS,
             dpi: int = 300) -> tuple[str, int]:
    with tempfile.TemporaryDirectory() as tmp:
        png = render(pdf, page, Path(tmp) / f"p-{page:02d}.png", dpi)
        best = ("", 0, -1)
        for deg in rotations:
            img = rotate(png, deg, Path(tmp) / f"r{deg}.png")
            text = tesseract(img)
            s = score(text, known_codes)
            if s > best[2]:
                best = (text, deg, s)
            if deg == 0 and s >= 3:
                break
        return best[0], best[1]


def page_count(pdf: Path) -> int:
    r = subprocess.run([need("pdfinfo"), str(pdf)], check=True, capture_output=True)
    m = re.search(r"Pages:\s+(\d+)", r.stdout.decode("utf-8", "replace"))
    return int(m.group(1)) if m else 0


def ocr_pdf(pdf: Path, out_dir: Path, pages=None, known_codes=None, dpi: int = 300) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for p in pages or range(1, page_count(pdf) + 1):
        text, deg = ocr_page(pdf, p, known_codes=known_codes, dpi=dpi)
        out = out_dir / f"p-{p:02d}.txt"
        out.write_text(text, encoding="utf-8")
        written.append(out)
        print(f"{pdf.name} стр. {p}: поворот {deg}, кодов {len(CODE.findall(text))}")
    return written


def parse_pages(spec: str | None):
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main(argv=None) -> int:
    from pipeline.fetch_pravo import fetch, root_dir
    from pipeline.nkmi import load_snapshot_codes
    ap = argparse.ArgumentParser(prog="python -m pipeline.ocr")
    ap.add_argument("eo")
    ap.add_argument("--pages")
    ap.add_argument("--dpi", type=int, default=300, help="не 300: текст пишется в raw/ocr/<eo>-<dpi>dpi/")
    a = ap.parse_args(argv)
    root = root_dir()
    pdf = fetch(a.eo, root)
    out = root / "raw" / "ocr" / (a.eo if a.dpi == 300 else f"{a.eo}-{a.dpi}dpi")
    ocr_pdf(pdf, out, parse_pages(a.pages), load_snapshot_codes(root) or None, a.dpi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
