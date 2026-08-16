#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${DSH_KLINE_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" scripts/live-smoke.py --python "$PYTHON_BIN" "$@"
