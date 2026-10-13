#!/bin/sh
set -eu
mkdir -p _reports
STEP=""
fail() { printf '{"ok": false, "step": "%s"}\n' "$STEP" > _reports/gate.json; echo "Ворота не пройдены на шаге: $STEP"; exit 1; }
run() { STEP="$1"; shift; echo "== $STEP"; "$@" || fail; }
run "uv sync" uv sync --frozen
run "pnpm install" pnpm install --frozen-lockfile
run "pytest" uv run pytest -q
run "watch fixtures" uv run python -m pipeline.watch --fixtures
run "build" uv run python -m opsite build
run "check" uv run python -m opsite check
run "unit" pnpm test:unit
run "e2e chromium" pnpm test:e2e
run "e2e firefox" pnpm test:e2e:firefox
run "e2e webkit" pnpm test:e2e:webkit
run "shots" pnpm shots
printf '{"ok": true}\n' > _reports/gate.json
echo "Ворота пройдены"
