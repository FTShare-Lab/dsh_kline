#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${DSH_KLINE_VENV:-$PROJECT_ROOT/.venv}"

"$PYTHON_BIN" -c 'import sys; raise SystemExit("Python 3.10 or newer is required") if sys.version_info < (3, 10) else None'
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements-dev.txt"

printf 'Python environment ready: %s\n' "$VENV_DIR"
printf 'Next: pnpm smoke:mcp && pnpm dsh:web\n'
