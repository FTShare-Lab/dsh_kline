#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${DSH_KLINE_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'dsh_kline Python is not executable: %s\nRun ./scripts/bootstrap.sh first.\n' "$PYTHON_BIN" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$PROJECT_ROOT/server.py"
