MESSAGES = {
    "no_site_yaml": "Не найден site.yaml в {root}. Запускайте команду из корня репо",
    "schema_error": "{where}: {field}: {message}",
    "yaml_error": "{path}: не удалось прочитать YAML: {error}",
    "csv_error": "{path}, строка {line}: {error}",
    "dataset_schema_missing": "Нет схемы data/schema/{name}.schema.json для датасета {name}",
    "dataset_too_big": "Датасет {name} весит {size} байт, это больше 1 МБ. Разделите его",
    "template_error": "{template}: {error}",
    "frontmatter_error": "{path}: в начале файла нужен блок --- с полями title и description ---",
    "build_ok": "Собрано: {pages} страниц, {datasets} датасетов в {seconds:.1f} с -> {out}",
    "manifest_mismatch": "Файлы в opsite/ правят только в хабе: {files}",
    "manifest_ok": "opsite {version}: {count} файлов в MANIFEST.sha256",
    "manifest_stale": "MANIFEST.sha256 устарел. В хабе запустите: uv run python -m opsite manifest",
    "unknown_norm": "Норма {id} не найдена в данных pal-norms",
    "norm_unsafe": "Норма {id}: статус {status}, проверена: {verified}. В документ не попадает",
    "check_ok": "Проверка пройдена: ошибок 0, предупреждений {warnings}",
    "check_failed": "Проверка не пройдена: ошибок {errors}, предупреждений {warnings}",
    "no_site": "Нет папки _site. Сначала соберите: uv run python -m opsite build",
    "serve": "Сайт {repo}: {url}  (остановить: Ctrl+C)",
    "sync_major": "{repo} выпустил v{got}, а в deps.yaml указан v{want}. Обновите deps.yaml и код вручную",
    "sync_unavailable": "{repo}: источник недоступен ({error}), оставляю старый снимок",
    "sync_sha": "{repo}/{file}: sha256 не совпадает с index.json",
    "sync_same": "{repo}: данные не изменились",
    "sync_updated": "{repo}: обновлено до {version} (данные от {data_date})",
    "stale": "Снимок {repo}/{name} от {data_date} старше {days} дней",
}


def msg(key: str, **kw) -> str:
    return MESSAGES[key].format(**kw)
