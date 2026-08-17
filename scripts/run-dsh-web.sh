#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT"
pnpm build:sidebar
dsh plugin --profile web add "link:$PROJECT_ROOT"
exec dsh --profile web --patch "$PROJECT_ROOT/config/dsh-kline.patch.yml" "$@"
