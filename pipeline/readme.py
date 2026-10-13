import argparse
import sys
from pathlib import Path

from pipeline import export
from pipeline.common import read_yaml

START = "<!-- numbers:start -->"
END = "<!-- numbers:end -->"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def ru_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def block(root: Path) -> str:
    envs = {e["dataset"]: e for e in export.datasets(root)}
    meta = read_yaml(root / "data" / "meta.yaml")
    dev = envs["devices-398n"]["items"]
    fn2 = sum(d["fn2"] for d in dev)
    diff = envs["devices-348n-diff"]["items"]
    by = {s: sum(i["status"] == s and i["verified"] for i in diff) for s in ("kept", "removed", "added")}
    old_total = sum(i["status"] != "added" for i in diff)
    unver_diff = sum(not i["verified"] for i in diff)
    al = envs["aliases"]["items"]
    al_unver = sum(not a["verified"] for a in al)
    nut = sorted(envs["nutrition-3551r"]["items"], key=lambda n: n["date"])
    amend = [n for n in nut if n["kind"] == "amendment"]
    last_item = max(int(n["items_to"]) for n in nut) if nut else 0
    lines = [
        START,
        f"Числа на {ru_date(meta['data_date'])}, считаются из данных командой `uv run python -m pipeline.readme`, "
        "точные значения на странице /data/ сайта",
        "",
        f"- {plural(len(dev), 'позиция', 'позиции', 'позиций')} действующего перечня, у каждой код, группа, подгруппа "
        f"и страница скана. {plural(fn2, 'позиция отмечена', 'позиции отмечены', 'позиций отмечены')} сноской 2",
        f"- {plural(len(al), 'бытовое название', 'бытовых названия', 'бытовых названий')} и вариантов написания, "
        f"которые ведут к видам изделий"
        + (f", {plural(al_unver, 'ещё не сверено', 'ещё не сверены', 'ещё не сверены')} с описанием вида" if al_unver else ""),
        f"- сравнение с прежним перечнем ({plural(old_total, 'позиция', 'позиции', 'позиций')}) и поправкой к нему: "
        f"{plural(by['kept'], 'вид остался', 'вида остались', 'видов остались')}, "
        f"{plural(by['removed'], 'выбыл', 'выбыли', 'выбыли')}, {plural(by['added'], 'добавился', 'добавились', 'добавились')}"
        + (f", {unver_diff} не сверено" if unver_diff else ""),
        f"- перечень лечебного питания для детей с инвалидностью: {plural(len(nut), 'документ', 'документа', 'документов')}, "
        f"сам перечень и {plural(len(amend), 'изменение', 'изменения', 'изменений')} к нему, пункты 1-{last_item} "
        "(номера и реквизиты, без списка продуктов)",
        END,
    ]
    return "\n".join(lines)


def render(root: Path, text: str) -> str:
    a, b = text.index(START), text.index(END) + len(END)
    return text[:a] + block(root) + text[b:]


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    ap = argparse.ArgumentParser(prog="python -m pipeline.readme")
    ap.add_argument("--check", action="store_true", help="только проверить, что числа в README совпадают с данными")
    a = ap.parse_args(argv)
    root = root_dir()
    path = root / "README.md"
    text = path.read_text(encoding="utf-8")
    new = render(root, text)
    if a.check:
        if new != text:
            print("числа в README.md расходятся с данными, запустите python -m pipeline.readme")
            return 1
        return 0
    path.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
