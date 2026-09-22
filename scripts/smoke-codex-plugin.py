"""Verify a relocatable Codex plugin bundle without changing real Codex config."""
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    archive = Path(sys.argv[1]).resolve()
    scratch = Path(tempfile.mkdtemp(prefix="dsh-kline-codex-"))
    relocated = scratch / "plugin cache 空格"
    relocated.mkdir()
    root = relocated.resolve()
    with tarfile.open(archive) as packed:
        members = packed.getmembers()
        for member in members:
            posix_member = PurePosixPath(member.name)
            windows_member = PureWindowsPath(member.name)
            assert not posix_member.is_absolute() and not windows_member.anchor, f"absolute or rooted archive member: {member.name!r}"
            assert ".." not in posix_member.parts and ".." not in windows_member.parts, f"parent path archive member: {member.name!r}"
            assert not member.issym() and not member.islnk(), f"link archive member: {member.name!r}"
            target = (root / member.name).resolve()
            assert target.is_relative_to(root), f"archive member escapes extraction root: {member.name!r}"
            assert not {".git", ".venv", "node_modules", "tests", "__pycache__"}.intersection(Path(member.name).parts)
        packed.extractall(root)
    plugin = relocated / "dsh-kline"
    manifests = {
        "portable_plugin": json.loads((plugin / "plugin.json").read_text(encoding="utf-8")),
        "portable_mcp": json.loads((plugin / "mcp.json").read_text(encoding="utf-8")),
        "codex_plugin": json.loads((plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8")),
        "codex_mcp": json.loads((plugin / ".mcp.json").read_text(encoding="utf-8")),
        "package": json.loads((plugin / "package.json").read_text(encoding="utf-8")),
    }
    assert {
        manifests["portable_plugin"]["version"],
        manifests["codex_plugin"]["version"],
        manifests["package"]["version"],
    } == {manifests["package"]["version"]}
    manifest = manifests["portable_plugin"]
    config = manifests["portable_mcp"]["mcpServers"]["dsh-kline"]
    fallback_config = manifests["codex_mcp"]["mcpServers"]["dsh-kline"]
    assert manifest["name"] == plugin.name
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert "mcp" not in manifest
    interface = manifest["extensions"]["com.openai"]["interface"]
    assert interface["composerIcon"] == "./assets/logo.jpg"
    assert interface["logo"] == "./assets/logo.jpg"
    assert interface["websiteURL"] == "https://ft.tech/"
    assert interface["category"] == "Finance"
    assert "icon" not in interface
    assert manifests["portable_mcp"]["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert manifest["extensions"]["com.openai"]["mcpApps"]["resourceUri"] == "ui://dsh-kline/kline"
    assert (plugin / "assets" / "logo.jpg").is_file()
    assert config["type"] == "stdio" and config["command"] == "node"
    assert config["args"] == ["${PLUGIN_ROOT}/scripts/run-codex-kline.mjs"]
    assert set(config) == {"type", "command", "args", "env"}
    assert manifests["codex_plugin"]["mcpServers"] == "./.mcp.json"
    assert fallback_config["args"] == ["scripts/run-codex-kline.mjs"]
    assert all("${" not in value for value in fallback_config["args"])
    plugin_root_token = "${PLUGIN_ROOT}"
    launcher = config["args"][0]
    assert launcher.startswith(plugin_root_token + "/")
    args = [str(plugin / launcher.removeprefix(plugin_root_token + "/"))]
    assert Path(args[0]).is_relative_to(plugin)
    assert not (plugin / "cordis.patch.yml").exists(), "Codex package must not ship DSH's Cordis patch"
    assert (plugin / "view" / "kline.html").is_file(), "Codex package needs the shared chart frontend"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FTSHARE_", "DSH_"))}
    runtime = scratch / "must-not-exist"
    env.update(PLUGIN_ROOT=str(plugin), DSH_KLINE_ADAPTER="dsh", DSH_KLINE_HOST_PID="not-a-dsh-pid",
               DSH_KLINE_RUNTIME_DIR=str(runtime), DSH_KLINE_CACHE_DIR=str(scratch / "cache"),
               DSH_KLINE_VENV=str(scratch / "fresh-venv"), DSH_KLINE_STATE_DIR=str(scratch / "state"),
               FTSHARE_API_KEY_FILE=str(scratch / "no-credentials.json"))
    params = StdioServerParameters(command=shutil.which(config["command"]), args=args, env=env, cwd=scratch)
    rows = [{"time": 1700000000 + i * 86400, "open": 100 + i, "high": 102 + i,
             "low": 99 + i, "close": 101 + i, "volume": 1000 + i} for i in range(30)]
    with anyio.fail_after(300):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listed = (await session.list_tools()).tools
                public = [t for t in listed if (t.meta or {}).get("ui", {}).get("visibility") != ["app"]]
                assert len(public) == 14 and len(listed) == 15
                print("PASS relocated plugin + fresh Python runtime + 14 public tools / 1 App-only tool")
                for tool, arguments in [("health", {}), ("search_symbols", {"query": "600519"}),
                                        ("calc_metrics", {"rows": rows})]:
                    assert not (await session.call_tool(tool, arguments)).isError, tool
                result = await session.call_tool("analyze_kline_rows", {"rows": rows, "symbol": "FIXTURE"})
                assert not result.isError
                payload = result.structuredContent
                assert payload["chart_session"] is None and not payload["chart_ready"]
                assert payload["chart_service"]["error"] == "chart_service_disabled"
                assert payload["chartCommands"]
                app = await session.read_resource("ui://dsh-kline/kline")
                assert "mcpDisplayModeBtn" in app.contents[0].text
                assert "ui/request-display-mode" in app.contents[0].text
                for action, arguments in [("watchlist_get", {}), ("calc_range", {"rows": rows}),
                                          ("analyze_key_levels", {"rows": rows})]:
                    response = await session.call_tool("chart_action", {"action": action, "arguments": arguments})
                    assert not response.isError, (action, response)
                assert not runtime.exists(), "Codex must not create DSH locator/session files"
                print("PASS MCP Apps resource + chart actions + no DSH service/locator")
    fallback_env = dict(env)
    fallback_env["PLUGIN_ROOT"] = str(plugin)
    fallback_params = StdioServerParameters(
        command=shutil.which(fallback_config["command"]),
        args=fallback_config["args"],
        env=fallback_env,
        cwd=plugin,
    )
    with anyio.fail_after(60):
        async with stdio_client(fallback_params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listed = (await session.list_tools()).tools
                assert len(listed) == 15
                print("PASS Codex compatibility manifest + relative launcher")
    print("PASS isolated Codex plugin smoke")


if __name__ == "__main__":
    anyio.run(main)
