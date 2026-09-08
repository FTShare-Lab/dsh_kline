#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/dsh_kline"
if [[ -n "${DSH_KLINE_VENV:-}" ]]; then
  VENV_DIR="$DSH_KLINE_VENV"
elif [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  # Keep a checked-out development copy on its project venv. Published GitHub
  # installs do not contain one, so they use the per-user cache below.
  VENV_DIR="$PROJECT_ROOT/.venv"
else
  VENV_DIR="$CACHE_HOME/venv"
fi
PYTHON_BIN="${DSH_KLINE_PYTHON:-$VENV_DIR/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  mkdir -p "$CACHE_HOME"
  printf 'Preparing the dsh_kline Python runtime…\n' >&2
  DSH_KLINE_VENV="$VENV_DIR" bash "$PROJECT_ROOT/scripts/bootstrap.sh" >&2
fi

exec "$PYTHON_BIN" "$PROJECT_ROOT/server.py"
