#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec node "$PROJECT_ROOT/scripts/run-dsh-kline.mjs" --prepare-project
