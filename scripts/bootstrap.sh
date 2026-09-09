#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${DSH_KLINE_VENV:-$PROJECT_ROOT/.venv}"
RUNTIME_STAMP="$VENV_DIR/.dsh-kline-requirements"

resolve_python() {
  local candidate resolved
  local -a candidates

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidates=("$PYTHON_BIN")
  else
    candidates=(
      python3 python3.13 python3.12 python3.11 python3.10
      /opt/homebrew/bin/python3 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10
      /usr/local/bin/python3 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10
      "$HOME/miniforge3/bin/python" "$HOME/miniconda3/bin/python" "$HOME/anaconda3/bin/python"
      /opt/homebrew/Caskroom/miniforge/base/bin/python3 /opt/homebrew/Caskroom/miniconda/base/bin/python3
    )
  fi

  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    if [[ -n "$resolved" ]] && "$resolved" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(resolve_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  printf 'dsh_kline requires Python 3.10 or newer. Install it, or set PYTHON_BIN to its absolute path.\n' >&2
  exit 1
fi

requirements_fingerprint() {
  if [[ -n "${DSH_KLINE_REQUIREMENTS_FINGERPRINT:-}" ]]; then
    printf '%s\n' "$DSH_KLINE_REQUIREMENTS_FINGERPRINT"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$PROJECT_ROOT/requirements.txt" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$PROJECT_ROOT/requirements.txt" | awk '{print $1}'
  else
    cksum "$PROJECT_ROOT/requirements.txt" | awk '{print $1 ":" $2}'
  fi
}

printf '[dsh_kline] Creating or repairing the virtual environment…\n' >&2
"$PYTHON_BIN" -m venv "$VENV_DIR"
printf '[dsh_kline] Updating the package installer…\n' >&2
"$VENV_DIR/bin/python" -m pip install --upgrade pip
printf '[dsh_kline] Installing dependencies…\n' >&2
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"
printf '[dsh_kline] Verifying the runtime…\n' >&2
"$VENV_DIR/bin/python" -c 'import ftshare, mcp, pydantic, pydantic_settings'

STAMP_TMP="$RUNTIME_STAMP.tmp.$$"
printf '%s\n' "$(requirements_fingerprint)" > "$STAMP_TMP"
mv "$STAMP_TMP" "$RUNTIME_STAMP"

printf '[dsh_kline] Python runtime ready: %s\n' "$VENV_DIR" >&2
