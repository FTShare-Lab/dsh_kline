#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_FT_KLINE_ROOT="$(cd "$PROJECT_ROOT/../ft-kline-view" && pwd)"

FT_KLINE_ROOT="${FT_KLINE_VIEW_ROOT:-$DEFAULT_FT_KLINE_ROOT}"
FT_KLINE_PYTHON="${FT_KLINE_VIEW_PYTHON:-/opt/homebrew/Caskroom/miniforge/base/envs/ft-kline-view/bin/python}"

if [[ ! -x "$FT_KLINE_PYTHON" ]]; then
  printf 'ft-kline-view Python is not executable: %s\n' "$FT_KLINE_PYTHON" >&2
  exit 1
fi

if [[ ! -f "$FT_KLINE_ROOT/server.py" ]]; then
  printf 'ft-kline-view server.py was not found under: %s\n' "$FT_KLINE_ROOT" >&2
  exit 1
fi

exec "$FT_KLINE_PYTHON" "$FT_KLINE_ROOT/server.py"
