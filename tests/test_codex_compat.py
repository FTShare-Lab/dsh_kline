import os
import re
import shutil
import sys
import tempfile
import inspect
from pathlib import Path

import anyio

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from core.analysis import analyze_rows
from adapters.host import codex_adapter, dsh_adapter, host_adapter_from_env
from services.analysis_service import AnalysisService


ROOT = Path(__file__).resolve().parents[1]


def sample_rows(count=12):
    return [
        {
            "time": 1_700_000_000 + index * 86_400,
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "volume": 1000 + index,
        }
        for index in range(count)
    ]


def test_provider_neutral_analysis_does_not_require_host_chart_adapter():
    result = analyze_rows(
        sample_rows(),
        symbol="TEST.X",
        name="Test",
        interval="day",
        limit=10,
        adjust="none",
        indicators=["ma", "rsi"],
        metrics=["rsi"],
        mark_support_resistance=False,
        ma_periods=[5, 10],
        rsi_period=14,
        boll_period=20,
        boll_std=2.0,
        volume_ma=20,
        atr_period=14,
        data_source="local-fixture",
        data_source_url=None,
        security_workspace=None,
    )
    assert result["ok"]
    assert result["chart_session"] is None
    assert result["chart_ready"] is False
    assert result["chart_service"]["error"] == "chart_service_disabled"
    assert result["chart"]["type"] == "kline"


def test_core_analysis_has_no_host_or_legacy_tools_dependency():
    source = inspect.getsource(__import__("core.analysis", fromlist=["analyze_rows"]))
    assert "from chart_service" not in source
    assert "import chart_service" not in source
    assert "from server" not in source
    assert "import server" not in source
    assert "tools." not in source


def test_host_adapters_have_explicitly_separate_capabilities():
    dsh = dsh_adapter()
    codex = codex_adapter()
    assert dsh.name == "dsh"
    assert dsh.chart_payload_fn is not None
    assert dsh.publish_chart_fn is not None
    assert "right sidebar" in dsh.instructions
    assert codex.name == "codex"
    assert codex.chart_payload_fn is None
    assert codex.publish_chart_fn is None
    assert "right sidebar" not in codex.instructions
    assert host_adapter_from_env({"DSH_KLINE_ADAPTER": "codex"}).name == "codex"
    assert host_adapter_from_env({}).name == "dsh"


def test_codex_application_service_analyzes_fetched_rows_without_publishing():
    calls = []

    def fake_fetch(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return {"ok": True, "symbol": symbol, "name": "Fixture", "rows": sample_rows(8),
                "source": "fixture", "status": "ready", "freshness": "fixture"}

    service = AnalysisService(fetch_candles_fn=fake_fetch)
    result = service.analyze_symbol(
        "TEST.X",
        resolved_name="Fixture",
        interval="day",
        interval_value=1,
        session_count=None,
        limit=8,
        adjust="none",
        indicators=["ma"],
        metrics=["rsi"],
        mark_support_resistance=False,
        ma_periods=None,
        rsi_period=14,
        boll_period=20,
        boll_std=2.0,
        volume_ma=20,
        atr_period=14,
    )
    assert calls and result["ok"]
    assert result["workflow"] == "fetch_analyze_chart_session"
    assert result["chart_session"] is None
    assert result["chart_service"]["error"] == "chart_service_disabled"


def test_codex_stdio_initialize_list_and_external_rows():
    async def run():
        env = dict(os.environ)
        env["DSH_KLINE_ADAPTER"] = "codex"
        env["DSH_KLINE_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="dsh-kline-codex-")
        env["DSH_KLINE_PYTHON"] = sys.executable
        env.pop("DSH_HOME", None)
        env.pop("DSH_KLINE_HOST_PID", None)
        params = StdioServerParameters(
            command=shutil.which("node") or "node",
            args=["scripts/run-codex-kline.mjs"],
            env=env,
            cwd=ROOT,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                assert "right sidebar" not in (initialized.instructions or "")
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"search_symbols", "analyze_kline", "analyze_kline_rows"} <= names
                chart_tools = {tool.name: tool for tool in tools.tools if tool.name in {"analyze_kline", "analyze_kline_rows"}}
                assert all(tool.meta["ui"]["resourceUri"] == "ui://dsh-kline/kline" for tool in chart_tools.values())
                resources = await session.list_resources()
                chart_resource = next(item for item in resources.resources if str(item.uri) == "ui://dsh-kline/kline")
                assert chart_resource.mimeType == "text/html;profile=mcp-app"
                rendered = await session.read_resource("ui://dsh-kline/kline")
                assert rendered.contents and "ui/initialize" in rendered.contents[0].text
                app_html = rendered.contents[0].text
                assert "mcpDisplayModeBtn" in app_html
                assert "ui/request-display-mode" in app_html
                assert "data:image/jpeg;base64," in app_html
                assert 'class="btn mcp-app-only mcp-display-mode-btn"' in app_html
                assert '<span class="icon-glyph" aria-hidden="true"><svg' in app_html
                display_button = re.search(
                    r'<button[^>]+id="mcpDisplayModeBtn"[^>]*>(.*?)</button>',
                    app_html,
                    re.DOTALL,
                )
                assert display_button is not None
                assert re.sub(r"<[^>]+>", "", display_button.group(1)).strip() == ""
                result = await session.call_tool(
                    "analyze_kline_rows",
                    {"rows": sample_rows(), "symbol": "TEST.X", "limit": 10},
                )
                assert result.isError is False
                assert result.structuredContent["chart_ready"] is False
                assert result.structuredContent["chart_service"]["error"] == "chart_service_disabled"
                assert result.structuredContent["chart"]["type"] == "kline"
                assert result.structuredContent["chartCommands"][0]["type"] == "SET_CANDLES"
                assert result.structuredContent["chart_ui"] == {
                    "ready": True,
                    "mode": "mcp_apps",
                    "resource_uri": "ui://dsh-kline/kline",
                }

    anyio.run(run)
