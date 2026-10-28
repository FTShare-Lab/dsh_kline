"""Codex v0.6.0 private-preview isolation and guarded-chart tests."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from codex_runtime.state import APP_RESOURCE_URI, CodexChartStore
from tools.lines import LineError

ROOT = Path(__file__).resolve().parents[1]


def rows(count: int = 40) -> list[dict]:
    return [{"time": 1_700_000_000 + index * 86_400, "open": 100 + index, "high": 102 + index,
             "low": 99 + index, "close": 101 + index, "volume": 1_000 + index} for index in range(count)]


def payload() -> dict:
    return {"symbol": "TEST.X", "name": "Test", "interval": "day", "adjust": "none",
            "chartCommands": [{"type": "SET_CANDLES", "rows": rows()}]}


def test_codex_runtime_never_imports_dsh_service_or_credential_locator(monkeypatch):
    monkeypatch.setenv("FT_KLINE_CODEX_MEMORY_ONLY", "1")
    import codex_server
    import codex_runtime.state

    server_source = inspect.getsource(codex_server)
    state_source = inspect.getsource(codex_runtime.state)
    assert "chart_service" not in server_source
    assert "chart_service" not in state_source
    assert "DSH_KLINE_SETTINGS_KEY_FILE" not in server_source
    from tools import fetch
    assert fetch._ftshare_credential_files() == ()


def test_memory_state_expires_and_never_uses_disk_journal():
    now = [100.0]
    store = CodexChartStore(idle_seconds=10, now=lambda: now[0])
    state = store.create(payload())
    assert state.context_ref in store._items
    now[0] = 111.0
    store.prune()
    assert state.context_ref not in store._items
    assert state.session_key is None


def test_app_source_switch_discards_the_former_current_chart_context():
    store = CodexChartStore()
    first, second = store.create(payload()), store.create(payload())
    app = "test-app-instance-012345"
    store.claim(first.context_ref, app)
    store.claim(second.context_ref, app)
    with pytest.raises(LineError, match="已结束"):
        store.context(first.context_ref)
    assert store.context(second.context_ref)["context_ref"] == second.context_ref


def test_guarded_edit_replay_conflict_and_ui_receipt_are_distinct():
    store = CodexChartStore()
    state = store.create(payload())
    first = store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "same-request", {
        "kind": "horizontal_line", "action": "create", "price": 123.4,
    })
    replay = store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "same-request", {
        "kind": "horizontal_line", "action": "create", "price": 123.4,
    })
    assert replay["replayed"] is True and replay["chart_session"] == first["chart_session"]
    with pytest.raises(LineError, match="request_id"):
        store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "same-request", {
            "kind": "horizontal_line", "action": "create", "price": 124.0,
        })
    applied = store.apply(state.context_ref, first["chart_session"])
    assert applied["state_commit"] is True
    status = store.status(state.context_ref, first["chart_session"])
    assert status["ui_receipt"] == "not_reported" and status["pixel_verified"] is False
    acknowledged = store.acknowledge(state.context_ref, first["chart_session"], rendered=True)
    assert acknowledged["ui_receipt"] == "rendered" and acknowledged["pixel_verified"] is False
    second = store.prepare(state.context_ref, 2, state.chart_session, "TEST.X", "render-failure", {
        "kind": "horizontal_line", "action": "create", "price": 124.0,
    })
    store.apply(state.context_ref, second["chart_session"])
    failed = store.acknowledge(state.context_ref, second["chart_session"], rendered=False, reason="renderer rejected object")
    assert failed["ui_receipt"] == "failed" and failed["pixel_verified"] is False and failed["ui_failure"] == "renderer rejected object"


def test_candidate_requires_explicit_confirmation_and_current_version():
    store = CodexChartStore()
    state = store.create(payload())
    candidate_ref = store.store_result(state.context_ref, revision=1, kind="range_candidates", result={"candidates": [{
        "start_time": rows()[3]["time"], "end_time": rows()[20]["time"], "lower_price": 90.0, "upper_price": 140.0,
    }]})
    with pytest.raises(LineError, match="候选"):
        store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "not-confirmed", {
            "kind": "rectangle", "action": "create", "candidate_result_ref": candidate_ref, "candidate_number": 1,
        })
    prepared = store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "confirmed", {
        "kind": "rectangle", "action": "create", "candidate_result_ref": candidate_ref, "candidate_number": 1,
        "user_confirmed_candidate": True,
    })
    store.apply(state.context_ref, prepared["chart_session"])
    with pytest.raises(LineError, match="版本"):
        store.prepare(state.context_ref, 1, state.chart_session, "TEST.X", "stale", {
            "kind": "horizontal_line", "action": "create", "price": 120.0,
        })


def test_codex_desktop_mcp_resource_app_visibility_and_cli_degradation():
    async def desktop() -> None:
        env = {"FT_KLINE_CLIENT": "desktop", "FT_KLINE_CODEX_MEMORY_ONLY": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        params = StdioServerParameters(command=sys.executable, args=["codex_server.py"], env=env, cwd=ROOT)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert tools["ft_kline_app_action"].meta["ui"]["visibility"] == ["app"]
                assert tools["ft_kline_app_action"].outputSchema is not None
                assert tools["analyze_kline"].outputSchema is not None
                assert APP_RESOURCE_URI in {str(item.uri) for item in (await session.list_resources()).resources}
                resource = await session.read_resource(APP_RESOURCE_URI)
                assert "ui/initialize" in resource.contents[0].text and "tools/call" in resource.contents[0].text
                assert "configure_session_key" in resource.contents[0].text and "sessionOnlyPresentation" in resource.contents[0].text
                analysis = await session.call_tool("analyze_kline_rows", {"rows": rows(), "symbol": "TEST.X", "limit": 30})
                assert not analysis.isError and analysis.structuredContent["chart_ready"] is True
                assert analysis.meta["ui"]["resourceUri"] == APP_RESOURCE_URI
                context_ref = analysis.structuredContent["context_ref"]
                activation = await session.call_tool("ft_kline_app_action", {"action": "activate", "arguments": {"context_ref": context_ref}, "app_instance": "test-app-instance-012345"})
                assert not activation.isError
                key = "private-session-key-not-for-output"
                configured = await session.call_tool("ft_kline_app_action", {"action": "configure_session_key", "app_instance": "test-app-instance-012345", "arguments": {"context_ref": context_ref, "api_key": key}})
                assert configured.structuredContent["credential_source"] == "session" and key not in json.dumps(configured.structuredContent)
                status = await session.call_tool("ft_kline_app_action", {"action": "data_source_status", "app_instance": "test-app-instance-012345", "arguments": {"context_ref": context_ref}})
                assert status.structuredContent["providers"]["ftshare"]["credential_source"] == "session" and status.structuredContent["providers"]["ftshare"]["can_clear"] is True and key not in json.dumps(status.structuredContent)
                cleared = await session.call_tool("ft_kline_app_action", {"action": "clear_session_key", "app_instance": "test-app-instance-012345", "arguments": {"context_ref": context_ref}})
                assert cleared.structuredContent["configured"] is False and key not in json.dumps(cleared.structuredContent)
                range_stats = await session.call_tool("ft_kline_app_action", {"action": "calc_range", "app_instance": "test-app-instance-012345", "arguments": {
                    "context_ref": context_ref, "rows": rows(8), "start_time": rows(8)[1]["time"], "end_time": rows(8)[6]["time"],
                }})
                assert range_stats.structuredContent["ok"] is True and range_stats.structuredContent["bars"] == 6
                levels = await session.call_tool("ft_kline_app_action", {"action": "analyze_key_levels", "app_instance": "test-app-instance-012345", "arguments": {"context_ref": context_ref, "symbol": "TEST.X", "rows": rows(8)}})
                assert levels.structuredContent["ok"] is True and levels.structuredContent["status"] in {"ready", "no_levels"}
                watchlist = await session.call_tool("ft_kline_app_action", {"action": "watchlist_save", "app_instance": "test-app-instance-012345", "arguments": {
                    "context_ref": context_ref, "watchlist": {"revision": 0, "groups": [{"id": "default", "name": "Default"}], "items": [{"symbol": "TEST.X", "name": "Test", "groupId": "default"}], "activeGroupId": "default", "sort": "manual"},
                }})
                assert watchlist.structuredContent["persistent"] is False and watchlist.structuredContent["watchlist"]["revision"] == 1
                prepared = await session.call_tool("ft_kline_app_action", {"action": "workbench_prepare_edit", "app_instance": "test-app-instance-012345", "arguments": {
                    "context_ref": context_ref, "expected_revision": 1, "chart_session": activation.structuredContent["chart_session"], "symbol": "TEST.X", "request_id": "app-typed-edit", "edit": {"kind": "horizontal_line", "action": "create", "price": 123.4},
                }})
                assert not prepared.isError and prepared.structuredContent["operation_status"] == "prepared"

    async def cli() -> None:
        env = {"FT_KLINE_CLIENT": "cli", "FT_KLINE_CODEX_MEMORY_ONLY": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        params = StdioServerParameters(command=sys.executable, args=["codex_server.py"], env=env, cwd=ROOT)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert "prepare_chart_edit" not in names and "ft_kline_app_action" not in names
                assert not (await session.list_resources()).resources
                response = await session.call_tool("analyze_kline_rows", {"rows": rows(), "symbol": "TEST.X", "limit": 30})
                assert response.structuredContent["chart_ready"] is False
                assert "CLI 不支持交互图表" in response.structuredContent["cli_notice"]
                assert "CLI does not support interactive charts" in initialized.instructions

    anyio.run(desktop)
    anyio.run(cli)
