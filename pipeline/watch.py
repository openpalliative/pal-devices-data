import argparse
import datetime as dt
import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from pipeline import net, nkmi
from pipeline.common import nkmi_status, read_csv, write_csv

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
FAIL_LIMIT = 3


def today_iso() -> str:
    return dt.date.today().isoformat()


def marker(kind: str, source: str) -> str:
    return "[watch:" + hashlib.sha256((kind + source).encode("utf-8")).hexdigest()[:12] + "]"


def review(kind: str, title: str, body: str, source: str, **extra) -> dict:
    key = nkmi.DATASET + "".join(":" + extra[k] for k in ("code", "version") if extra.get(k))
    item = {"kind": kind, "title": f"{title} {marker(kind, key)}", "body": body, "source": source, "eoNumber": ""}
    item.update(extra)
    return item


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def run(root: Path, *, get=net.get, today: str | None = None, reports: Path | None = None) -> dict:
    today = today or today_iso()
    snap_dir = root / "data" / "snapshots"
    check_path = snap_dir / "last_check.json"
    prev_check = read_json(check_path, {})
    prev_snap = nkmi.load_snapshot(root)
    report = {"checked_at": today, "facts": [], "review": [], "proposals": []}
    check = {"checked_at": today, "ok": False, "nkmi_version": (prev_snap or {}).get("version"),
             "present_398n": 0, "missing_398n": [], "consecutive_failures": 0, "error": ""}
    rows = read_csv(root / "data" / "398n.csv") if (root / "data" / "398n.csv").is_file() else []

    def finish():
        nkmi.write_json(check_path, check)
        report["facts"].append({"path": str(check_path.relative_to(root)), "what": f"проверка справочника {today}: "
                                + ("успешно" if check["ok"] else f"ошибка: {check['error']}"), "source": nkmi.META_URL})
        out = (reports or root / "_reports") / "watch.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return report

    try:
        meta = nkmi.parse_meta(get(nkmi.META_URL).decode("utf-8-sig"))
    except nkmi.FormatChanged as e:
        check["error"] = str(e)
        report["review"].append(review("format_changed", "Изменился формат паспорта набора НКМИ", str(e), nkmi.META_URL))
        return finish()
    except net.SourceDown as e:
        check["error"] = str(e)
        check["consecutive_failures"] = int(prev_check.get("consecutive_failures", 0)) + 1
        if check["consecutive_failures"] >= FAIL_LIMIT:
            report["review"].append(review("source_down", "Справочник НКМИ недоступен три проверки подряд",
                                           f"Последняя ошибка: {e}", nkmi.META_URL))
        return finish()

    top = nkmi.latest(meta)
    snap = prev_snap
    if top["structure"] != nkmi.STRUCTURE:
        check["error"] = f"новая структура {top['structure']}"
        report["review"].append(review("format_changed", "У набора НКМИ новая структура данных",
                                       f"В meta.csv появилась версия {top['version']} со структурой {top['structure']}. "
                                       f"Снимок не обновлён, нужна правка pipeline/nkmi.py", nkmi.META_URL))
        return finish()
    if not snap or snap.get("version") != top["version"]:
        try:
            xsd = get(meta["structures"][nkmi.STRUCTURE])
            if snap and snap.get("xsd_sha256") and nkmi.sha256(xsd) != snap["xsd_sha256"]:
                raise nkmi.FormatChanged(f"схема structure-{nkmi.STRUCTURE}.xsd изменилась без смены имени")
            data = get(top["url"])
            kinds = nkmi.parse_zip(data)
        except nkmi.FormatChanged as e:
            check["error"] = str(e)
            report["review"].append(review("format_changed", "Изменился формат набора НКМИ", str(e), nkmi.META_URL))
            return finish()
        except (net.SourceDown, KeyError) as e:
            check["error"] = str(e)
            check["consecutive_failures"] = int(prev_check.get("consecutive_failures", 0)) + 1
            if check["consecutive_failures"] >= FAIL_LIMIT:
                report["review"].append(review("source_down", "Архив НКМИ не скачивается три проверки подряд", str(e), top["url"]))
            return finish()
        codes = nkmi.tracked_codes(root)
        history, versions = nkmi.extend_history(snap, top["version"], kinds, codes) if snap else (None, None)
        snap = nkmi.build_snapshot(version=top["version"], zip_url=top["url"], zip_sha=nkmi.sha256(data),
                                   xsd_sha=nkmi.sha256(xsd), structure=top["structure"], kinds=kinds,
                                   codes=codes, history=history, history_versions=versions)
        nkmi.write_json(nkmi.snapshot_path(root), snap)
        nkmi.write_subset(root, snap)
        report["facts"].append({"path": "data/snapshots/nkmi.json",
                                "what": f"снимок НКМИ {top['version']}, zip sha256 {snap['zip_sha256'][:12]}",
                                "source": top["url"]})
    kinds = snap["codes"]
    missing = [r["code"] for r in rows if r["code"] not in kinds]
    check.update({"ok": True, "nkmi_version": snap["version"], "present_398n": len(rows) - len(missing),
                  "missing_398n": missing, "consecutive_failures": 0, "error": ""})
    for code in missing:
        report["review"].append(review("code_removed", f"Кода {code} нет в справочнике НКМИ {snap['version']}",
                                       f"Код {code} из перечня изделий для дома не найден в версии {snap['version']}. "
                                       "Карточка сама показывает статус «Не проверено». Нужно понять, переименован вид или "
                                       "исключён, и решить, что писать семьям", top["url"], code=code))
    fresh = snap is not prev_snap
    before = (prev_snap or {}).get("codes") if fresh and prev_snap else None
    for r in rows:
        code, now = r["code"], kinds.get(r["code"])
        if now is None:
            continue
        was = before.get(code) if before is not None else (r["nkmi_name"] if fresh else now)
        if fresh and was is not None and now != was:
            report["review"].append(review(
                "code_changed", f"Под кодом {code} в НКМИ {snap['version']} новое название вида",
                f"В перечне: {r['name_in_act']}. Было в справочнике: {was}. Стало в НКМИ {snap['version']}: {now}. "
                "Нужно решить, что писать семьям на карточке", top["url"], code=code, version=snap["version"]))
        if now != r["nkmi_name"] and nkmi_status(r["name_in_act"], now) == "renamed":
            report["proposals"].append({"code": code, "field": "nkmi_name", "old": r["nkmi_name"], "new": now,
                                        "label": "review:medical"})
    return finish()


def apply_proposals(root: Path, report_path: Path) -> int:
    report = read_json(report_path, {})
    props = {p["code"]: p for p in report.get("proposals", []) if p.get("field") == "nkmi_name"}
    if not props:
        return 0
    path = root / "data" / "398n.csv"
    with open(path, encoding="utf-8", newline="") as f:
        header = f.readline().strip().split(",")
    rows = read_csv(path)
    for r in rows:
        if r["code"] in props:
            r["nkmi_name"] = props[r["code"]]["new"]
    write_csv(path, header, rows)
    return len(props)


def open_issues(report_path: Path, *, runner=subprocess.run) -> int:
    report = read_json(report_path, {})
    opened = 0
    for item in report.get("review", []):
        mark = item["title"].rsplit(" ", 1)[-1]
        found = runner(["gh", "issue", "list", "--state", "open", "--search", f"{mark} in:title", "--json", "number"],
                       capture_output=True, text=True, check=True)
        if json.loads(found.stdout or "[]"):
            continue
        body = item["body"] + f"\n\nИсточник: {item['source']}\nТип: {item['kind']}"
        runner(["gh", "issue", "create", "--title", item["title"], "--body", body], check=True)
        opened += 1
    return opened


def stale_check(root: Path, days: int, out: Path, today: str | None = None) -> bool:
    check = read_json(root / "data" / "snapshots" / "last_check.json", {})
    when = check.get("checked_at")
    age = (dt.date.fromisoformat(today or today_iso()) - dt.date.fromisoformat(when)).days if when else None
    if age is not None and age <= days:
        return False
    report = {"checked_at": today or today_iso(), "facts": [], "proposals": [], "review": [
        review("watch_stale", "Наблюдатель НКМИ не запускался",
               f"Последняя проверка справочника: {when or 'ни разу'}. Проверьте расписание watch.yml и доступ раннера к сайту Росздравнадзора",
               "data/snapshots/last_check.json")]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def fixture_get(meta_name: str = "meta.csv"):
    xml = (FIXTURES / "nkmi_sample.xml").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data-20261001-structure-20180615.xml", xml)
    files = {"meta.csv": (FIXTURES / meta_name).read_bytes(), ".xsd": (FIXTURES / "structure.xsd").read_bytes(),
             ".zip": buf.getvalue()}

    def get(url: str, **_):
        net.check_host(url)
        for suffix, body in files.items():
            if url.endswith(suffix):
                return body
        raise net.SourceDown(url)
    return get


def run_fixtures(root: Path) -> dict:
    sandbox = root / "_reports" / "watch-fixtures"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    (sandbox / "data").mkdir(parents=True)
    rows = read_csv(root / "data" / "398n.csv")
    sample = {r["code"] for r in rows} & set(nkmi.parse_xml(io.BytesIO((FIXTURES / "nkmi_sample.xml").read_bytes())))
    keep = [r for r in rows if r["code"] in sample]
    keep.append({**rows[0], "code": "999990", "name_in_act": "Вид, который исчез из справочника", "nkmi_name": "Вид, который исчез из справочника"})
    with open(root / "data" / "398n.csv", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    write_csv(sandbox / "data" / "398n.csv", header, keep)
    return run(sandbox, get=fixture_get(), reports=root / "_reports")


def main(argv=None) -> int:
    from pipeline.fetch_pravo import root_dir
    ap = argparse.ArgumentParser(prog="python -m pipeline.watch")
    ap.add_argument("--fixtures", action="store_true", help="прогон на фикстурах, без сети, данные репо не меняются")
    ap.add_argument("--apply-proposals", type=Path, metavar="WATCH_JSON")
    ap.add_argument("--open-issues", type=Path, metavar="WATCH_JSON")
    ap.add_argument("--stale-check", type=int, metavar="DAYS")
    a = ap.parse_args(argv)
    root = root_dir()
    if a.apply_proposals:
        print(f"предложено правок имени вида: {apply_proposals(root, a.apply_proposals)}")
        return 0
    if a.open_issues:
        print(f"открыто задач: {open_issues(a.open_issues)}")
        return 0
    if a.stale_check is not None:
        stale = stale_check(root, a.stale_check, root / "_reports" / "watch-stale.json")
        print("наблюдатель давно не запускался" if stale else "наблюдатель запускался недавно")
        return 0
    report = run_fixtures(root) if a.fixtures else run(root)
    print(f"фактов: {len(report['facts'])}, на проверку людям: {len(report['review'])}, правок имени: {len(report['proposals'])}")
    for r in report["review"]:
        print(f"  {r['kind']}: {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
