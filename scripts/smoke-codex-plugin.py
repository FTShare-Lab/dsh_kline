"""Verify a relocatable Codex plugin bundle without changing real Codex config."""
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    archive = Path(sys.argv[1]).resolve()
    scratch = Path(tempfile.mkdtemp(prefix="dsh-kline-codex-"))
    relocated = scratch / "plugin cache 空格"
    relocated.mkdir()
    with tarfile.open(archive) as packed:
        members = packed.getmembers()
        for member in members:
            target = (relocated / member.name).resolve()
            assert target.is_relative_to(relocated) and not member.issym() and not member.islnk()
            assert not {".git", ".venv", "node_modules", "tests", "__pycache__"}.intersection(Path(member.name).parts)
        packed.extractall(relocated)
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
    assert manifest["name"] == plugin.name
    assert manifest["mcp"] == "./mcp.json"
    assert manifest["extensions"]["com.openai"]["mcpApps"]["resourceUri"] == "ui://dsh-kline/kline"
    assert config["type"] == "stdio" and config["command"] == "node"
    assert config["args"] == ["${PLUGIN_ROOT}/scripts/run-codex-kline.mjs"]
    assert manifests["codex_plugin"]["mcpServers"] == "./.mcp.json"
    assert manifests["codex_mcp"]["mcpServers"]["dsh-kline"]["args"] == ["${CLAUDE_PLUGIN_ROOT}/scripts/run-codex-kline.mjs"]
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
    print(f"Isolated plugin retained at {plugin}")


if __name__ == "__main__":
    anyio.run(main)
