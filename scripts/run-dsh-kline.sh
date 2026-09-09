#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/dsh_kline"
MANAGED_RUNTIME=1
if [[ -n "${DSH_KLINE_VENV:-}" ]]; then
  VENV_DIR="$DSH_KLINE_VENV"
elif [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  # Keep a checked-out development copy on its project venv. Published GitHub
  # installs do not contain one, so they use the per-user cache below.
  VENV_DIR="$PROJECT_ROOT/.venv"
  MANAGED_RUNTIME=0
else
  VENV_DIR="$CACHE_HOME/venv"
fi
PYTHON_BIN="${DSH_KLINE_PYTHON:-$VENV_DIR/bin/python}"
RUNTIME_STAMP="$VENV_DIR/.dsh-kline-requirements"
BOOTSTRAP_LOG="$CACHE_HOME/bootstrap.log"

requirements_fingerprint() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$PROJECT_ROOT/requirements.txt" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$PROJECT_ROOT/requirements.txt" | awk '{print $1}'
  else
    cksum "$PROJECT_ROOT/requirements.txt" | awk '{print $1 ":" $2}'
  fi
}

runtime_imports_work() {
  "$PYTHON_BIN" -c 'import ftshare, mcp, pydantic, pydantic_settings' >/dev/null 2>&1
}

runtime_stamp_matches() {
  [[ -f "$RUNTIME_STAMP" ]] && [[ "$(<"$RUNTIME_STAMP")" == "$REQUIREMENTS_FINGERPRINT" ]]
}

BOOTSTRAP_REASON=""
REQUIREMENTS_FINGERPRINT="$(requirements_fingerprint)"

if [[ ! -x "$PYTHON_BIN" ]]; then
  BOOTSTRAP_REASON="Python runtime is missing"
elif ! runtime_imports_work; then
  if [[ "$MANAGED_RUNTIME" -eq 0 ]]; then
    printf '[dsh_kline] The project .venv is incomplete. Run: pnpm bootstrap\n' >&2
    exit 1
  fi
  BOOTSTRAP_REASON="installed dependencies are incomplete"
elif [[ "$MANAGED_RUNTIME" -eq 1 ]] && ! runtime_stamp_matches; then
  BOOTSTRAP_REASON="dependency requirements changed"
fi

if [[ -n "$BOOTSTRAP_REASON" ]]; then
  mkdir -p "$CACHE_HOME"
  printf '[dsh_kline] Preparing Python runtime: %s.\n' "$BOOTSTRAP_REASON" >&2
  printf '[dsh_kline] Installation details: %s\n' "$BOOTSTRAP_LOG" >&2
  if ! DSH_KLINE_VENV="$VENV_DIR" \
       DSH_KLINE_REQUIREMENTS_FINGERPRINT="$REQUIREMENTS_FINGERPRINT" \
       bash "$PROJECT_ROOT/scripts/bootstrap.sh" 2>&1 | tee "$BOOTSTRAP_LOG" >&2; then
    printf '[dsh_kline] Runtime preparation failed. See: %s\n' "$BOOTSTRAP_LOG" >&2
    exit 1
  fi
fi

exec "$PYTHON_BIN" "$PROJECT_ROOT/server.py"
