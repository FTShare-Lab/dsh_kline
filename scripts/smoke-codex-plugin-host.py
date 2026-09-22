"""Install a packed plugin through the real Codex CLI and start its fallback MCP config."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def run_codex(command: str, home: Path, *args: str) -> dict:
    executable = shutil.which(command)
    if not executable:
        raise RuntimeError(f"Codex CLI not found: {command}")
    result = subprocess.run(
        [executable, *args, "--json"],
        env={**os.environ, "CODEX_HOME": str(home)},
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        shell=os.name == "nt" and executable.lower().endswith((".cmd", ".bat")),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Codex exited {result.returncode}")
    return json.loads(result.stdout)


def extract_archive(archive: Path, destination: Path) -> Path:
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as packed:
        for member in packed.getmembers():
            posix_member = PurePosixPath(member.name)
            windows_member = PureWindowsPath(member.name)
            if posix_member.is_absolute() or windows_member.anchor or ".." in posix_member.parts or ".." in windows_member.parts:
                raise RuntimeError(f"unsafe archive member: {member.name!r}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"link archive member: {member.name!r}")
            target = (root / member.name).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"archive member escapes root: {member.name!r}")
        packed.extractall(root)
    return root / "dsh-kline"


async def smoke_fallback(installed: Path) -> None:
    fallback = json.loads((installed / ".mcp.json").read_text(encoding="utf-8"))
    config = fallback["mcpServers"]["dsh-kline"]
    assert config["command"] == "node"
    assert config["args"] == ["scripts/run-codex-kline.mjs"]
    assert all("${" not in value for value in config["args"])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DSH_", "FTSHARE_"))}
    runtime_dir = installed / ".runtime"
    env.update(
        DSH_KLINE_ADAPTER="dsh",
        PLUGIN_ROOT=str(installed),
        DSH_KLINE_VENV=str(installed / ".unused-venv"),
        DSH_KLINE_CACHE_DIR=str(installed / ".cache"),
        DSH_KLINE_RUNTIME_DIR=str(runtime_dir),
        DSH_KLINE_STATE_DIR=str(installed / ".state"),
    )
    params = StdioServerParameters(command=shutil.which(config["command"]), args=config["args"], env=env, cwd=installed)
    with anyio.fail_after(120):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listed = (await session.list_tools()).tools
                assert len(listed) == 15
                assert not runtime_dir.exists()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--codex", default=os.environ.get("CODEX_BIN", "codex"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="dsh-kline-codex-host-") as temporary:
        scratch = Path(temporary)
        plugin_source = extract_archive(args.archive.resolve(), scratch / "marketplace" / "plugins")
        marketplace = scratch / "marketplace"
        marketplace_manifest = marketplace / ".agents" / "plugins" / "marketplace.json"
        marketplace_manifest.parent.mkdir(parents=True)
        marketplace_manifest.write_text(json.dumps({
            "name": "local-smoke",
            "interface": {"displayName": "Local smoke"},
            "plugins": [{
                "name": "dsh-kline",
                "source": {"source": "local", "path": "./plugins/dsh-kline"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }],
        }) + "\n", encoding="utf-8")
        codex_home = scratch / "codex-home"
        codex_home.mkdir()
        run_codex(args.codex, codex_home, "plugin", "marketplace", "add", str(marketplace))
        installed = run_codex(args.codex, codex_home, "plugin", "add", "dsh-kline@local-smoke")["installedPath"]
        installed_path = Path(installed)
        assert installed_path.is_dir() and installed_path != plugin_source
        anyio.run(smoke_fallback, installed_path)
    print("PASS real Codex CLI plugin install + fallback MCP startup")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL real Codex plugin host smoke: {exc}", file=sys.stderr)
        raise
