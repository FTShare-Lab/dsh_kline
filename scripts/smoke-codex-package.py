#!/usr/bin/env python3
"""Copy a Codex ZIP or marketplace directory into a clean Unicode/space path."""
from __future__ import annotations

import os
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path


def probe_launcher(destination: Path, env: dict[str, str], *, desktop: bool) -> None:
    """Exercise the installed Node front door, not a direct Python import."""
    node = shutil.which("node")
    if not node: raise RuntimeError("Node is required for the installed Codex launcher")
    prepared_env = {key: value for key, value in env.items() if not key.startswith(("DSH_", "FT_KLINE_", "FTSHARE_"))}
    prepared_env.update({"DSH_KLINE_RUNTIME_MODE": "external", "DSH_KLINE_PYTHON": sys.executable})
    process = subprocess.Popen([node, str(destination / "scripts/run-ft-kline.mjs")], cwd=destination,
                               env=prepared_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    responses: queue.Queue = queue.Queue()
    def read():
        for line in process.stdout:
            try: responses.put(json.loads(line))
            except ValueError: continue
    threading.Thread(target=read, daemon=True).start()
    sequence = 0
    def request(method, params=None, timeout=10):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params or {}}) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            response = responses.get(timeout=max(0.01, deadline - time.monotonic()))
            if response.get("id") != sequence: continue
            if "error" in response: raise RuntimeError(str(response["error"]))
            return response["result"]
    try:
        capability = {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}} if desktop else {}
        request("initialize", {"protocolVersion": "2025-11-25", "capabilities": capability,
                               "clientInfo": {"name": "packed-smoke", "version": "1"}}, timeout=5)
        process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        # Cache exactly the first catalog, as desktop hosts may do. Never
        # refresh it in response to readiness or list_changed notifications.
        tools = request("tools/list")["tools"]
        names = {tool["name"] for tool in tools}
        assert "analyze_kline" in names, "the first catalog must contain the real tools"
        analyze = next(tool for tool in tools if tool["name"] == "analyze_kline")
        assert bool(analyze.get("_meta", {}).get("ui", {}).get("resourceUri")) is desktop
        resources = request("resources/list")["resources"]
        assert bool(resources) is desktop
        if desktop:
            request("resources/read", {"uri": "ui://ft-kline/chart-v3"})
            app = next(tool for tool in tools if tool["name"] == "ft_kline_app_action")
            assert app["_meta"]["ui"]["visibility"] == ["app"]
        deadline = time.monotonic() + 30
        while True:
            status = request("tools/call", {"name": "ft_kline_runtime_status", "arguments": {}})
            if status.get("isError") or time.monotonic() > deadline: raise RuntimeError("Installed launcher did not become ready")
            if status["structuredContent"]["phase"] == "ready": break
            time.sleep(0.1)
        assert ("prepare_chart_edit" in names) is desktop
        health = request("tools/call", {"name": "health", "arguments": {}})["structuredContent"]
        assert health["interactive_chart"] is desktop
        assert health["client"] == ("desktop" if desktop else "cli")
        rows = [{"time": 1700000000 + i * 86400, "open": 100 + i, "high": 102 + i,
                 "low": 99 + i, "close": 101 + i, "volume": 1000 + i} for i in range(40)]
        chart = request("tools/call", {"name": "analyze_kline_rows", "arguments": {"symbol": "TEST.X", "rows": rows, "limit": 30}})
        assert not chart.get("isError") and chart["structuredContent"]["chart_ready"] is desktop
    finally:
        process.stdin.close()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def main() -> int:
    archive = Path(sys.argv[1] if len(sys.argv) > 1 else "release/ft-kline-v0.6.6.zip").resolve()
    if not archive.exists(): raise SystemExit(f"package not found: {archive}")
    temporary = Path(tempfile.mkdtemp(prefix="ft-kline-codex-smoke-"))
    try:
        destination = temporary / "全新 安装 FT K线"
        if archive.is_dir():
            shutil.copytree(archive, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        else:
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
        probe_launcher(destination, env, desktop=False)
        probe_launcher(destination, env, desktop=True)
        # Windows GitHub runners can retain a cp1252 console.  The destination
        # deliberately contains Chinese characters to test installation paths,
        # so render it as ASCII escapes instead of failing after a successful
        # smoke test merely while writing the diagnostic.
        displayed_destination = str(destination).encode("ascii", "backslashreplace").decode("ascii")
        print(f"Codex package smoke passed: {displayed_destination}")
        return 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
