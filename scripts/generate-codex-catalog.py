#!/usr/bin/env python3
"""Generate/verify startup catalogs from the real Python MCP definitions."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def export(mode: str) -> str:
    sys.path.insert(0, str(ROOT))
    os.environ.update(FT_KLINE_CLIENT=mode, FT_KLINE_CODEX_MEMORY_ONLY="1")
    import anyio
    import codex_server
    from codex_runtime.mcp_app import _bridge
    async def collect():
        return {
            "version": json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"],
            "mode": mode,
            "instructions": codex_server.INSTRUCTIONS,
            "tools": [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in await codex_server.mcp.list_tools()],
            "resources": [resource.model_dump(mode="json", by_alias=True, exclude_none=True) for resource in await codex_server.mcp.list_resources()],
            "bridge": _bridge() if mode == "desktop" else None,
        }
    return json.dumps(anyio.run(collect), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--mode", choices=("desktop", "cli"))
    args = parser.parse_args()
    if args.mode:
        print(export(args.mode), end="")
        return
    env = {key: value for key, value in os.environ.items() if not key.startswith(("FTSHARE_", "DSH_KLINE_", "FT_KLINE_"))}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for mode in ("desktop", "cli"):
        result = subprocess.run([sys.executable, __file__, "--mode", mode], env=env,
                                capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
        path = ROOT / "codex_runtime" / f"catalog-{mode}.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != result.stdout:
                raise SystemExit(f"Stale startup catalog: {path.name}; run scripts/generate-codex-catalog.py")
        else:
            path.write_text(result.stdout, encoding="utf-8")
    print("Codex startup catalogs verified" if args.check else "Codex startup catalogs generated")

if __name__ == "__main__":
    main()
