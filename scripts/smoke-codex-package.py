#!/usr/bin/env python3
"""Extract and import a Codex package from a Unicode/space path without caches."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    archive = Path(sys.argv[1] if len(sys.argv) > 1 else "release/ft-kline-v0.6.0.zip").resolve()
    if not archive.is_file(): raise SystemExit(f"archive not found: {archive}")
    temporary = Path(tempfile.mkdtemp(prefix="ft-kline-codex-smoke-"))
    try:
        destination = temporary / "全新 安装 FT K线"
        with zipfile.ZipFile(archive) as package:
            package.extractall(destination)
        for required in ("plugin.json", ".codex-plugin/plugin.json", "mcp.json", ".mcp.json", "codex_server.py", "codex_runtime/state.py"):
            if not (destination / required).is_file(): raise SystemExit(f"missing packaged file: {required}")
            if not os.access(destination / required, os.R_OK): raise SystemExit(f"packaged file is not readable: {required}")
        for forbidden in ("chart_service.py", "server.py", "cordis.patch.yml"):
            if (destination / forbidden).exists(): raise SystemExit(f"DSH-only file leaked into Codex package: {forbidden}")
        text = (destination / "mcp.json").read_text(encoding="utf-8")
        if "${PLUGIN_ROOT}/scripts/run-ft-kline.mjs" not in text: raise SystemExit("mcp.json does not use PLUGIN_ROOT")
        env = {key: value for key, value in os.environ.items() if key not in {"FTSHARE_API_KEY", "FTSHARE_API_KEY_FILE", "DSH_KLINE_SETTINGS_KEY_FILE", "DSH_KLINE_HOST_PID", "DSH_KLINE_RUNTIME_DIR", "DSH_KLINE_CACHE_DIR"}}
        env.update({"FT_KLINE_CLIENT": "cli", "FT_KLINE_CODEX_MEMORY_ONLY": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        probe = "import codex_server; assert codex_server.IS_CLI; assert not any(name.startswith('get_chart_context') for name in codex_server.mcp._tool_manager._tools)"
        completed = subprocess.run([sys.executable, "-c", probe], cwd=destination, env=env, text=True, capture_output=True, timeout=20)
        if completed.returncode: raise SystemExit(completed.stderr or completed.stdout)
        print(f"Codex package smoke passed: {destination}")
        return 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
