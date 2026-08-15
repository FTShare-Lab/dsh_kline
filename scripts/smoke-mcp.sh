#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FT_KLINE_ROOT="${FT_KLINE_VIEW_ROOT:-$(cd "$PROJECT_ROOT/../ft-kline-view" && pwd)}"
FT_KLINE_PYTHON="${FT_KLINE_VIEW_PYTHON:-/opt/homebrew/Caskroom/miniforge/base/envs/ft-kline-view/bin/python}"

exec "$FT_KLINE_PYTHON" "$SCRIPT_DIR/smoke-mcp.py" \
  --python "$FT_KLINE_PYTHON" \
  --root "$FT_KLINE_ROOT"
