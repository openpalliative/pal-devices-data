import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

import jsonschema
import yaml

from .messages_ru import msg

OPSITE = Path(__file__).resolve().parent
FORMAT = "openpalliative-dataset/1"
EXCLUDED_MARK = "решение за мейнтейнером в РФ"


class BuildError(Exception):
    pass


def read_yaml(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.BaseLoader)
    except yaml.YAMLError as e:
        raise BuildError(msg("yaml_error", path=path, error=e)) from e


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        head = f.read(1)
        if head == "﻿":
            raise BuildError(msg("csv_error", path=path, line=1, error="файл в UTF-8 с BOM, сохраните без BOM"))
        f.seek(0)
        rows = []
        for i, row in enumerate(csv.DictReader(f), start=2):
            if None in row:
                raise BuildError(msg("csv_error", path=path, line=i, error="лишние столбцы"))
            row["_line"] = str(i)
            rows.append(row)
        return rows


def load_schema(name: str) -> dict:
    return json.loads((OPSITE / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _types(schema: dict) -> list[str]:
    t = schema.get("type", [])
    return t if isinstance(t, list) else [t]


def coerce(obj, schema: dict):
    if not isinstance(schema, dict):
        return obj
    types = _types(schema)
    if isinstance(obj, str):
        if obj == "" and "null" in types:
            return None
        if "boolean" in types and obj in ("true", "false"):
            return obj == "true"
        if "integer" in types:
            try:
                return int(obj)
            except ValueError:
                pass
        if "number" in types:
            try:
                return float(obj.replace(",", "."))
            except ValueError:
                pass
        return obj
    if isinstance(obj, dict):
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        out = {}
        for k, v in obj.items():
            sub = props.get(k, extra if isinstance(extra, dict) else {})
            out[k] = coerce(v, sub)
        return out
    if isinstance(obj, list):
        return [coerce(v, schema.get("items", {})) for v in obj]
    return obj


def _ru_error(e: jsonschema.ValidationError) -> str:
    custom = e.schema.get("x-message-ru") if isinstance(e.schema, dict) else None
    if custom:
        return custom
    v = e.validator
    if v == "required":
        missing = e.message.split("'")[1] if "'" in e.message else e.message
        return f"нет обязательного поля {missing}"
    if v == "type":
        return f"ожидается {e.validator_value}, а здесь {json.dumps(e.instance, ensure_ascii=False)[:60]}"
    if v == "enum":
        return "допустимые значения: " + ", ".join(map(str, e.validator_value))
    if v == "pattern":
        return f"значение {e.instance!r} не подходит под формат {e.validator_value}"
    if v == "additionalProperties":
        return "лишнее поле: " + e.message.split("'")[1] if "'" in e.message else e.message
    if v in ("minLength", "minItems"):
        return "пустое значение"
    if v == "const":
        return f"ожидается {e.validator_value!r}"
    return e.message


def validate(obj, schema: dict, where: str) -> None:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    lines = []
    for e in errors[:20]:
        path = e.absolute_path
        field = ".".join(str(p) for p in path) or "(корень)"
        if isinstance(obj, dict) and path and path[0] == "items" and len(path) > 1:
            item = obj["items"][path[1]]
            if isinstance(item, dict) and item.get("_line"):
                field = f"строка {item['_line']}, поле " + ".".join(str(p) for p in list(path)[2:])
        lines.append(msg("schema_error", where=where, field=field, message=_ru_error(e)))
    raise BuildError("\n".join(lines))


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_sha256(source: list, items: list) -> str:
    return hashlib.sha256(canonical({"source": source, "items": items})).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_envelope(*, dataset: str, repo: str, items: list, source: list, meta: dict,
                  schema_version: str = "1.0.0", stale_after_days: int = 90,
                  license: str = "CC-BY-4.0", excluded: int = 0) -> dict:
    clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
    return {
        "format": FORMAT,
        "dataset": dataset,
        "repo": repo,
        "schema_version": schema_version,
        "version": meta["version"],
        "generated_at": now_utc(),
        "data_date": meta["data_date"],
        "stale_after_days": stale_after_days,
        "license": license,
        "source": source,
        "content_sha256": content_sha256(source, clean),
        "counts": {
            "items": len(clean),
            "unverified": sum(1 for it in clean if it.get("verified") is not True),
            "excluded": excluded,
        },
        "items": clean,
    }


def split_excluded(rows: list[dict]) -> tuple[list[dict], int]:
    kept = [r for r in rows if not r.get("excluded")]
    return kept, len(rows) - len(kept)


def days_old(date_str: str, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return (today - dt.date.fromisoformat(date_str[:10])).days
