# pal-devices-data: как выпустить

Раздел для общего RELEASE.md. Команды `gh` выполняет владелец организации после решения о публикации. Всё ниже бесплатно на плане Free для публичного репо

## 1. До первого пуша

1. Pages через Actions: `gh api -X POST repos/openpalliative/pal-devices-data/pages -f build_type=workflow`
2. Права Actions в репо: по умолчанию только чтение и разрешение ботам открывать PR (без этого `create-pull-request` в watch и sync-data падает). То же разрешение нужно на уровне организации

   ```sh
   gh api -X PUT orgs/openpalliative/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
   gh api -X PUT repos/openpalliative/pal-devices-data/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
   ```

3. Закрытые отчёты об уязвимостях: `gh api -X PUT repos/openpalliative/pal-devices-data/private-vulnerability-reporting`. Secret scanning и push protection включаются в Settings → Code security
4. Автослияние для PR со снимком справочника: `gh repo edit openpalliative/pal-devices-data --enable-auto-merge --delete-branch-on-merge`
5. Метки: `review:data`, `review:medical`, `review:legal`, `facts`, `alias`, `good first issue`. Общий скрипт хаба `scripts/labels` создаёт их во всех репо

## 2. Порядок пуша

pal-devices-data идёт вторым, после pal-norms. `sync-data.yml` берёт снимок норм с https://openpalliative.github.io/pal-norms/data/v1/index.json, поэтому сначала должен быть зелёный `pages` у pal-norms. В репо уже лежит локальный снимок `vendor/pal-norms/`, первый деплой сайта от него не зависит

После пуша main: дождаться зелёных `checks` и `pages`, открыть https://openpalliative.github.io/pal-devices-data/ и https://openpalliative.github.io/pal-devices-data/data/v1/index.json

## 3. Защита main

Ruleset для `main`: запрет force push и удаления, изменения только через PR, обязательные проверки `gate` и `actionlint` из `checks.yml`. Обязательного ревью CODEOWNERS не ставить, пока мейнтейнер один

Боты в main напрямую не пишут:

- снимок справочника НКМИ уходит PR `watch/nkmi-facts` с меткой `facts`. Workflow сам запускает для него `checks.yml` (события `GITHUB_TOKEN` checks не запускают) и включает автослияние. Если автослияние выключено, PR ждёт человека
- новые имена видов идут PR `watch/nkmi-names` с меткой `review:medical`, их сливает человек
- снимки соседей идут PR `sync/data` с меткой `review:data`
- слияние ботом не запускает `pages.yml`, поэтому сайт пересобирается ещё и по расписанию раз в день

Обход для прямого пуша снимка (по желанию): добавить GitHub Actions в список обхода ruleset и завести переменную `WATCH_FACTS_PUSH` со значением `true`. Тогда `scripts/watch-apply facts` коммитит снимок в main и запускает `pages.yml`. Работает ли обход для `GITHUB_TOKEN` в этой организации, не проверено, по умолчанию не включать

## 4. Переменные

- `WATCH_RUNNER` (vars, не secrets): JSON-строка для `runs-on`. Пусто значит `"ubuntu-24.04"`. Для своего раннера, например `["self-hosted", "linux", "ru"]`. Раннеру нужны git, gh и uv. Self-hosted только на уровне этого репо, ephemeral, без workflow на `pull_request`, с настройкой «Require approval for all outside collaborators». Включать только после решения Кирилла, раннер в России ставит и обслуживает мейнтейнер в России
- `WATCH_FACTS_PUSH`: см. раздел 3, по умолчанию не задавать

## 5. Первые прогоны

- `checks` и `pages` запускаются сами на push
- `watch.yml` по понедельникам в 04:17 UTC читает только открытые данные Росздравнадзора. Первый ручной запуск (`gh workflow run watch.yml`) делает мейнтейнер в России или после решения Кирилла. Записать, отвечает ли roszdravnadzor.gov.ru раннерам GitHub
- `sync-data.yml` по вторникам в 05:43 UTC, ручной запуск `gh workflow run sync-data.yml` после зелёного pages у pal-norms
- watch и sync-data в конце каждого прогона включают watch, pages и sync-data через API, чтобы GitHub не выключил расписание через 60 дней без коммитов. Раз в месяц всё равно смотреть вкладку Actions

## 6. Релиз

```sh
git tag -a v0.1.0 -m "pal-devices-data 0.1.0"
git push origin v0.1.0
```

`release.yml` прогоняет pytest, наблюдателя на фикстурах, сборку и проверки сайта, потом публикует релиз с тремя файлами:

- `pal-devices-data-v0.1.0-site.zip`: готовый сайт `_site`
- `pal-devices-data-v0.1.0-data.zip`: датасеты `data/v1` с JSON Schema и `LICENSE-DATA`
- `SHA256SUMS`: проверка `sha256sum -c SHA256SUMS`

Версию в `pyproject.toml` и `package.json` поднимать вместе с тегом

## 7. Карточка репо

- Description: `Перечень медицинских изделий для паллиативной помощи на дому как открытые данные и поиск «кто выдаёт»`
- Website: https://openpalliative.github.io/pal-devices-data/
- Topics: `palliative-care`, `open-data`, `medical-devices`, `russia`, `github-pages`
- Social preview: загрузить `docs/social-preview.png` (1280×640) в Settings → General вручную, API для этого нет

## 8. Проверено локально

- actionlint 1.7.12 с shellcheck 0.10.0: 0 замечаний по 5 workflow
- `uvx zizmor --offline`: без находок. В режиме auditor остаётся `artipacked` низкой уверенности в `watch.yml`: токен сохраняется в checkout только при `WATCH_FACTS_PUSH=true`, а в артефакт уходит только `_reports`
- issue forms, `config.yml`, `dependabot.yml` и workflows проходят схемы SchemaStore (`check-jsonschema`)

Пины экшенов сверены `git ls-remote` 11.10.2026:

| Экшен | Версия | SHA |
|---|---|---|
| actions/checkout | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| astral-sh/setup-uv | v10.3.0 | `1c37ad07a6a961277cf70c0d37d6f313000f5884` |
| pnpm/action-setup | v6.1.0 | `ea17c68df8912ef543352723c149a84f56e3d413` (коммит под аннотированным тегом) |
| actions/setup-node | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| actions/upload-artifact | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| actions/upload-pages-artifact | v5.0.0 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| actions/deploy-pages | v5.0.1 | `368f82528645a54fb793d4d04e342629a3f51346` |
| peter-evans/create-pull-request | v8.1.1 | `5f6978faf089d4d20b00c7766989d076bb2fc7f1` |

`actions/configure-pages` убран: сайт собирается с базой из `site.yaml`, а экшену нужны права на Pages в job сборки. Базовый путь `/pal-devices-data/` проверяет шаг `base` в `pages.yml`
