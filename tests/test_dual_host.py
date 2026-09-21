"""Portable host adapters based on the complete upstream snapshot."""
import asyncio
import hashlib
import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import server
from adapters.host import codex_adapter, dsh_adapter, host_adapter_from_env
from adapters.mcp_apps import mcp_app_html
from core.analysis import analyze_rows
from services.analysis_service import AnalysisService
from services.chart_actions import CHART_API_ACTIONS, PROVIDER_NAMES, dispatch
from test_codex_compat import sample_rows


ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "config/upstream-baseline.json").read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def test_complete_upstream_baseline_has_no_unreviewed_drift():
    assert len(BASE["files"]) == 120
    for name, expected in BASE["files"].items():
        assert (ROOT / name).is_file(), name
        if name not in BASE["adapted_files"]:
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name


def test_mcp_controls_are_not_in_the_upstream_dsh_view():
    original = (ROOT / "view/kline.html").read_text()
    assert 'mcpDisplayModeBtn' not in original
    rendered = mcp_app_html()
    assert 'mcpDisplayModeBtn' in rendered
    assert 'window.__DSH_KLINE_MCP_APPS__.ready.then' in rendered
    assert 'ui/request-display-mode' in rendered


@pytest.mark.parametrize(("mode", "runtime_mode"), [("dsh", "auto"), ("codex", "external")])
def test_launchers_keep_upstream_public_schemas_and_isolate_hosts(mode, runtime_mode, tmp_path):
    async def run():
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DSH_", "FTSHARE_"))}
        env.update(DSH_KLINE_ADAPTER="dsh" if mode == "codex" else "codex",
                   DSH_KLINE_RUNTIME_MODE=runtime_mode,
                   DSH_KLINE_PYTHON=sys.executable, DSH_KLINE_CHART_PORT="0",
                   DSH_KLINE_HOST_PID=str(os.getpid()),
                   DSH_KLINE_RUNTIME_DIR=str(tmp_path / "runtime"),
                   DSH_KLINE_CACHE_DIR=str(tmp_path / "cache"),
                   DSH_KLINE_STATE_DIR=str(tmp_path / "state"),
                   FTSHARE_API_KEY_FILE=str(tmp_path / "credentials.json"))
        # Poison DSH-only process identity: Codex must not even import chart_service.
        if mode == "codex":
            env["DSH_KLINE_HOST_PID"] = "not-a-pid"
            env["DSH_KLINE_DEFER_BOOTSTRAP"] = "1"
        params = StdioServerParameters(command=shutil.which("node"),
            args=[str(ROOT / f"scripts/run-{mode}-kline.mjs")], env=env, cwd=tmp_path)
        with anyio.fail_after(40):
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    listed = (await session.list_tools()).tools
                    public = [t for t in listed if (t.meta or {}).get("ui", {}).get("visibility") != ["app"]]
                    assert {t.name: digest(t.inputSchema) for t in public} == BASE["tool_input_schema_sha256"]
                    assert len(listed) == (15 if mode == "codex" else 14)
                    health = await session.call_tool("health", {})
                    assert health.structuredContent["ok"]
                    result = await session.call_tool("analyze_kline_rows", {
                        "rows": sample_rows(25), "symbol": "FIXTURE", "indicators": ["boll", "rsi"],
                        "rsi_period": 5, "boll_period": 7, "boll_std": 3,
                    })
                    assert not result.isError
                    payload = result.structuredContent
                    assert payload["chart_ready"] == (mode == "dsh")
                    if mode == "codex":
                        assert payload["chart_session"] is None
                        assert payload["chart_service"]["error"] == "chart_service_disabled"
                        assert not (tmp_path / "runtime").exists()
                        assert "right sidebar" not in initialized.instructions
                        action = await session.call_tool("chart_action", {
                            "action": "analyze_key_levels", "arguments": {"rows": sample_rows(25)}})
                        assert action.structuredContent["ok"]
                        denied = await session.call_tool("chart_action", {"action": "start_chart_service", "arguments": {}})
                        assert denied.isError
                    else:
                        assert payload["chart_session"]
                        assert (tmp_path / f"runtime/services/{os.getpid()}.json").is_file()
    anyio.run(run)


def test_codex_fetched_analysis_preserves_renderer_parameters_without_dsh(monkeypatch):
    monkeypatch.setattr(server, "_HOST_ADAPTER", codex_adapter())
    monkeypatch.setattr(server, "_resolve_symbol_input", lambda value: (value, "Fixture", None))
    fetch = Mock(return_value={"ok": True, "rows": sample_rows(40), "source": "fixture"})
    monkeypatch.setattr(server, "fetch_candles", fetch)
    publisher = Mock(side_effect=AssertionError("Codex must not publish DSH charts"))
    monkeypatch.setattr(server, "publish_chart", publisher)
    result = asyncio.run(server.analyze_kline("TEST.X", limit=30, indicators=["boll", "rsi"],
        boll_period=7, boll_std=3.5, rsi_period=5, adjust="forward"))
    assert result.structuredContent["chart"]["render_options"]["boll_period"] == 7
    from tools.draw import draw_kline
    expected = draw_kline(sample_rows(40)[-30:], indicators=["boll", "rsi"],
                         boll_period=7, boll_std=3.5, rsi_period=5)
    assert result.structuredContent["chartCommands"] == expected["chartCommands"]
    assert result.structuredContent["adjust"] == "forward"
    fetch.assert_called_once()
    publisher.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_dsh_publisher_runs_once_and_failures_preserve_analysis(monkeypatch, fails):
    monkeypatch.setattr(server, "_HOST_ADAPTER", dsh_adapter())
    publisher = Mock(side_effect=RuntimeError("unavailable") if fails else None,
                     return_value=("fixture-session", "http://127.0.0.1"))
    monkeypatch.setattr(server, "publish_chart", publisher)
    result = asyncio.run(server.analyze_kline_rows(sample_rows(30), "TEST.X"))
    publisher.assert_called_once()
    assert result.structuredContent["ok"]
    assert result.structuredContent["indicator_last"]
    assert result.structuredContent["chart_ready"] is not fails


def test_every_ui_action_is_shared_and_provider_routes_use_injected_functions():
    providers = {name: Mock(return_value={"ok": True, "fixture": name}) for name in PROVIDER_NAMES}
    for action in CHART_API_ACTIONS - {"analyze_kline", "analyze_key_levels"}:
        result = dispatch(action, {}, providers=providers)
        assert result.get("ok", True), action
    assert dispatch("__import__", {})["error"] == "unsupported_chart_action"


def test_core_cannot_render_publish_or_import_hosts():
    assert "publish_chart_fn" not in inspect.signature(analyze_rows).parameters
    assert "chart_payload_fn" not in inspect.signature(analyze_rows).parameters
    source = inspect.getsource(analyze_rows)
    for forbidden in ("chart_service", "server", "tools.", "adapters."):
        assert "import " + forbidden not in source
        assert "from " + forbidden not in source


@pytest.mark.parametrize("source,can_clear", [("environment", False), ("external_file", False), ("plugin_store", True), ("session", False)])
def test_mcp_and_ui_preserve_credential_provenance(monkeypatch, source, can_clear):
    status = {"available": True, "configured": True, "credential_source": source, "can_clear": can_clear}
    monkeypatch.setattr(server, "ftshare_status", lambda: status)
    mcp_status = asyncio.run(server.data_source_status()).structuredContent
    ui_status = dispatch("data_source_status", {}, providers={"ftshare_status": lambda: status})
    for result in (mcp_status, ui_status):
        assert result["providers"]["ftshare"]["credential_source"] == source
        assert result["providers"]["ftshare"]["can_clear"] is can_clear


def test_unknown_adapter_fails_instead_of_accidentally_starting_dsh():
    with pytest.raises(ValueError):
        host_adapter_from_env({"DSH_KLINE_ADAPTER": "typo"})
