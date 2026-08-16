#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${DSH_KLINE_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" "$SCRIPT_DIR/smoke-mcp.py" --python "$PYTHON_BIN"
