#!/usr/bin/env python3
"""FT K-Line Codex MCP server.

Desktop mode exposes a private MCP App and guarded drawing protocol.  CLI mode
registers only analysis tools and intentionally has no chart resource or write
operations.  This module never imports the DSH server or its loopback service.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import math
import os
from typing import Annotated, Any

# Must precede the provider import: Codex may use an environment key or an
# in-memory App key, but never searches DSH/profile credential files.
os.environ.setdefault("FT_KLINE_CODEX_MEMORY_ONLY", "1")

from mcp import types
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from pydantic import BaseModel, ConfigDict

from codex_runtime.analysis import (AVAILABLE_METRICS, analyze_rows, analyze_symbol, fetch_candles,
                                    resolve_symbol, search_symbols, validate_interval)
from codex_runtime.functions import (list_chart_functions, list_ta_catalog, read_ta, run_chart_function, run_ta)
from codex_runtime.mcp_app import APP_META, register_resource
from codex_runtime.state import APP_RESOURCE_URI, CodexChartEdit, CodexChartStore
from core.adjustment import ADJUSTMENT_DESCRIPTION, normalize_adjustment
from core.calc import DEFAULT_ATR_PERIOD, DEFAULT_BOLL_PERIOD, DEFAULT_BOLL_STD, DEFAULT_MA_PERIODS, DEFAULT_RSI_PERIOD, DEFAULT_VOLUME_MA, calc_range
from core.rows import validate_rows
from tools.calc import run_calc_metrics
from tools.chart_indicators import calculate_chart_indicators
from tools.fetch import (clear_provider_caches, data_source_capability_contract, ftshare_capabilities,
                         fetch_comparison_candles, fetch_market_board_detail, fetch_market_pulse,
                         fetch_market_ticker, fetch_security_intelligence, fetch_security_workspace,
                         ftshare_index_kline_available, ftshare_status, symbol_directory, test_ftshare_connection)
from tools.lines import LineError

CLIENT = (os.environ.get("FT_KLINE_CLIENT") or "desktop").strip().lower()
IS_CLI = CLIENT == "cli"
STORE = CodexChartStore()


class ToolOutput(BaseModel):
    """Declared schema for every Codex/App result, with extensible domain fields."""
    model_config = ConfigDict(extra="allow")
    ok: bool | None = None

INSTRUCTIONS = (
    "For ordinary K-line requests call analyze_kline once. It fetches, calculates and opens the FT K-Line App. "
    "For current chart drawing, always use get_chart_context -> prepare_chart_edit -> apply_chart_edit -> get_chart_edit_status. "
    "A prepared candidate is not a commit. An applied result confirms server chart state; a UI receipt and pixel verification are separate. "
    "Never use a context_ref from another conversation. FTShare keys are never accepted by model tools."
    if not IS_CLI else
    "Codex CLI provides FT K-Line market data, analysis and TA-Lib results only. CLI does not support interactive charts, current-chart context, or drawing writes."
)
mcp = FastMCP("ft-kline", instructions=INSTRUCTIONS, json_response=True)


def result(payload: dict[str, Any], text: str, *, error: bool = False, chart: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structuredContent=payload,
                                _meta=APP_META if chart and not IS_CLI else None, isError=error)


def failure(exc: Exception) -> types.CallToolResult:
    code = getattr(exc, "code", "codex_chart_error")
    return result({"ok": False, "error": code, "message": str(exc)}, str(exc), error=True)


@contextmanager
def _session_credential(context_ref: str | None):
    """Temporarily expose an App-entered key only to the provider call.

    The process environment always wins. The App key stays in the chart state,
    is never written to a file, and is removed from the provider environment
    immediately after the call.
    """
    original = os.environ.get("FTSHARE_API_KEY")
    state = None
    try:
        if not original and context_ref:
            state = STORE._state(context_ref)  # Internal state lookup; no DSH state involved.
            if state.session_key: os.environ["FTSHARE_API_KEY"] = state.session_key
        yield
    finally:
        if original is None: os.environ.pop("FTSHARE_API_KEY", None)
        else: os.environ["FTSHARE_API_KEY"] = original
        if state is not None: clear_provider_caches()


def _attach_chart(analysis: dict[str, Any]) -> dict[str, Any]:
    payload = analysis.pop("chart_payload", None)
    if not analysis.get("ok") or not isinstance(payload, dict): return analysis
    state = STORE.create(payload)
    analysis.update(STORE.chart_payload(state.context_ref))
    analysis["chart_ready"] = True
    analysis["chart_host"] = {"ok": True, "mode": "mcp_apps_memory"}
    return analysis


def _data_source_payload() -> dict[str, Any]:
    """Describe the active process credential state without ever returning it."""
    ftshare = ftshare_status()
    return {"ok": True, "providers": {"ftshare": {"available": bool(ftshare.get("available")),
            "configured": bool(ftshare.get("configured")), "credential_source": "environment" if ftshare.get("configured") else "none",
            "persistent": False, "can_clear": False, "capabilities": ftshare_capabilities(),
            "index_kline": ftshare_index_kline_available(), "contracts": ftshare.get("contracts", {})}},
            "capability_contract": data_source_capability_contract(),
            "anonymous_mode": not bool(ftshare.get("configured")),
            "credential_notice": "Environment key is used when set; otherwise anonymous/free capabilities remain available."}


def _app_context(arguments: dict[str, Any], app_instance: str, *, consume: bool = False) -> str:
    """Validate the UI-provided context before an App-only action.

    Guarded chart methods still need ``context_ref`` as their explicit public
    parameter, while provider helpers must have it removed before dispatch.
    """
    context_ref = str(arguments.get("context_ref", "") or "")
    if not context_ref:
        raise LineError("chart_context_required", "当前 App 没有可用图表会话，请重新生成图表。")
    STORE._state(context_ref, app_instance=app_instance, claim=True)
    if consume:
        arguments.pop("context_ref", None)
    return context_ref


def _key_levels_from_rows(symbol: Any, supplied_rows: Any) -> dict[str, Any]:
    """Calculate the App's key-level cards from its displayed rows only."""
    if not isinstance(supplied_rows, list) or len(supplied_rows) > 4_000:
        return {"ok": False, "error": "invalid_rows", "message": "请提供不超过 4000 根已加载 K 线。"}
    rows = validate_rows(supplied_rows, min_len=1)
    if len(rows) < 5:
        return {"ok": False, "error": "insufficient_candles", "message": "关键点位分析至少需要 5 根有效 K 线。"}
    metrics = run_calc_metrics(rows, metrics=["support_resistance"])
    marks: list[dict[str, Any]] = []
    levels = metrics.get("support_resistance") if isinstance(metrics, dict) else None
    if isinstance(levels, dict):
        for kind, label, color in (("support", "支撑", "success"), ("resistance", "压力", "danger")):
            for index, level in enumerate(levels.get(kind, [])[:5] if isinstance(levels.get(kind), list) else []):
                try:
                    price, timestamp = float(level["price"]), int(level["last_time"])
                    touches = max(0, int(level.get("touches") or 0))
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(price) and timestamp > 0:
                    text = f"{label} {price:.2f}" + (f" · 邻近{touches}根" if touches else "")
                    marks.append({"type": "TEXT_MARKER", "id": f"{kind}:{timestamp}:{index}", "time": timestamp,
                                  "price": round(price, 2), "text": text, "color": color})
    return {"ok": True, "symbol": str(symbol or ""), "count": len(rows), "chartCommands": marks,
            "metrics": metrics, "status": "ready" if marks else "no_levels"}


@mcp.tool(name="health", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
async def health() -> Annotated[types.CallToolResult, ToolOutput]:
    return result({"ok": True, "server": "ft-kline", "client": "cli" if IS_CLI else "desktop",
                   "interactive_chart": not IS_CLI, "credential_storage": "environment_or_memory_session"}, "health ok")


@mcp.tool(name="data_source_status", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
async def data_source_status() -> Annotated[types.CallToolResult, ToolOutput]:
    # FT_KLINE_CODEX_MEMORY_ONLY makes these functions report environment state
    # only; no DSH/plugin key file is considered.
    return result(_data_source_payload(), "data_source_status ok")


@mcp.tool(name="search_symbols", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
async def search_symbols_tool(query: Annotated[str, Field(min_length=1, max_length=120)],
                              limit: Annotated[int, Field(ge=1, le=20)] = 8) -> Annotated[types.CallToolResult, ToolOutput]:
    data = search_symbols(query, limit=limit)
    return result(data, "search_symbols ok" if data.get("ok") else str(data.get("message") or data.get("error")), error=not data.get("ok", False))


@mcp.tool(name="fetch_candles", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
async def fetch_candles_tool(symbol: str, interval: str = "day", interval_value: Annotated[int, Field(ge=1, le=240)] = 1,
                             session_count: Annotated[int | None, Field(ge=1, le=10)] = None,
                             limit: Annotated[int, Field(ge=2, le=4000)] = 220,
                             adjust: str = "none") -> Annotated[types.CallToolResult, ToolOutput]:
    canonical = normalize_adjustment(adjust)
    valid_interval, interval_error = validate_interval(interval)
    resolved, _name, symbol_error = resolve_symbol(symbol)
    if canonical is None: return result(adjustment_error(), "invalid adjustment", error=True)
    if interval_error: return result({"ok": False, **interval_error}, interval_error["message"], error=True)
    if symbol_error: return result({"ok": False, **symbol_error}, symbol_error["message"], error=True)
    data = fetch_candles(resolved or symbol, interval=valid_interval or "day", interval_value=interval_value,
                         session_count=session_count, limit=limit, adjust=canonical)
    return result(data, "fetch_candles ok" if data.get("ok") else str(data.get("message") or data.get("error")), error=not data.get("ok", False))


@mcp.tool(name="calc_metrics", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
async def calc_metrics(rows: list[dict[str, Any]], metrics: list[str] | None = None,
                       rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
                       boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
                       boll_std: Annotated[float, Field(ge=0.5, le=5)] = DEFAULT_BOLL_STD,
                       atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
                       volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA) -> Annotated[types.CallToolResult, ToolOutput]:
    if not isinstance(rows, list) or len(rows) > 12000:
        return result({"ok": False, "error": "invalid_external_rows", "message": "rows must contain at most 12000 values"}, "invalid rows", error=True)
    try: data = run_calc_metrics(rows, metrics=metrics, rsi_period=rsi_period, boll_period=boll_period, boll_std=boll_std, atr_period=atr_period, volume_ma=volume_ma)
    except Exception as exc: return result({"ok": False, "error": "calc_failed", "message": str(exc)}, str(exc), error=True)
    return result(data, "calc_metrics ok")


async def _analyze_rows(rows: list[dict[str, Any]], symbol: str, name: str | None, interval: str, limit: int, adjust: str,
                        indicators: list[str] | None, metrics: list[str] | None, mark_support_resistance: bool,
                        ma_periods: list[int] | None, rsi_period: int, boll_period: int, boll_std: float,
                        volume_ma: int, atr_period: int, data_source: str | None, data_source_url: str | None) -> types.CallToolResult:
    canonical, error = normalize_adjustment(adjust), None
    valid_interval, interval_error = validate_interval(interval)
    if canonical is None: return result(adjustment_error(), "invalid adjustment", error=True)
    if interval_error: return result({"ok": False, **interval_error}, interval_error["message"], error=True)
    try: data = analyze_rows(rows, symbol=symbol, name=name, interval=valid_interval or "day", limit=limit, adjust=canonical,
                             indicators=indicators, metrics=metrics, mark_support_resistance=mark_support_resistance,
                             ma_periods=ma_periods, rsi_period=rsi_period, boll_period=boll_period, boll_std=boll_std,
                             volume_ma=volume_ma, atr_period=atr_period, data_source=data_source, data_source_url=data_source_url)
    except Exception as exc: return result({"ok": False, "error": "analysis_failed", "message": str(exc)}, str(exc), error=True)
    if IS_CLI:
        data.pop("chart_payload", None); data.update({"chart_ready": False, "chart_host": {"ok": False, "error": "cli_interactive_chart_unsupported"}, "cli_notice": "CLI 不支持交互图表。"})
        return result(data, "analyze_kline_rows ok · CLI 不支持交互图表")
    return result(_attach_chart(data), "analyze_kline_rows ok", chart=True)


@mcp.tool(name="analyze_kline_rows", structured_output=True)
async def analyze_kline_rows_tool(rows: list[dict[str, Any]], symbol: str, name: str | None = None, interval: str = "day",
                                  limit: Annotated[int, Field(ge=2, le=4000)] = 60, adjust: str = "none",
                                  indicators: list[str] | None = None, metrics: list[str] | None = None,
                                  mark_support_resistance: bool = False, ma_periods: list[int] | None = None,
                                  rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
                                  boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
                                  boll_std: Annotated[float, Field(ge=0.5, le=5)] = DEFAULT_BOLL_STD,
                                  volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
                                  atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
                                  data_source: str | None = None, data_source_url: str | None = None) -> Annotated[types.CallToolResult, ToolOutput]:
    return await _analyze_rows(rows, symbol, name, interval, limit, adjust, indicators, metrics, mark_support_resistance,
                               ma_periods, rsi_period, boll_period, boll_std, volume_ma, atr_period, data_source, data_source_url)


@mcp.tool(name="analyze_kline", structured_output=True)
async def analyze_kline_tool(symbol: str, interval: str = "day", interval_value: Annotated[int, Field(ge=1, le=240)] = 1,
                             session_count: Annotated[int | None, Field(ge=1, le=10)] = None,
                             limit: Annotated[int, Field(ge=2, le=4000)] = 220, adjust: str = "none",
                             indicators: list[str] | None = None, metrics: list[str] | None = None,
                             mark_support_resistance: bool = False, ma_periods: list[int] | None = None,
                             rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
                             boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
                             boll_std: Annotated[float, Field(ge=0.5, le=5)] = DEFAULT_BOLL_STD,
                             volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
                             atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD) -> Annotated[types.CallToolResult, ToolOutput]:
    try: data = analyze_symbol(symbol, interval=interval, interval_value=interval_value, session_count=session_count, limit=limit,
                               adjust=adjust, indicators=indicators, metrics=metrics, mark_support_resistance=mark_support_resistance,
                               ma_periods=ma_periods, rsi_period=rsi_period, boll_period=boll_period, boll_std=boll_std,
                               volume_ma=volume_ma, atr_period=atr_period)
    except Exception as exc: return result({"ok": False, "error": "analysis_failed", "message": str(exc)}, str(exc), error=True)
    if not data.get("ok"): return result(data, str(data.get("message") or data.get("error")), error=True)
    if IS_CLI:
        data.pop("chart_payload", None); data.update({"chart_ready": False, "chart_host": {"ok": False, "error": "cli_interactive_chart_unsupported"}, "cli_notice": "CLI 不支持交互图表。"})
        return result(data, "analyze_kline ok · CLI 不支持交互图表")
    return result(_attach_chart(data), "analyze_kline ok", chart=True)


if not IS_CLI:
    register_resource(mcp)

    @mcp.tool(name="get_chart_context", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def get_chart_context(context_ref: str) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(STORE.context(context_ref), "get_chart_context ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="list_chart_functions", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def list_chart_functions_tool() -> Annotated[types.CallToolResult, ToolOutput]:
        return result(list_chart_functions(), "list_chart_functions ok", chart=True)

    @mcp.tool(name="list_ta_functions", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def list_ta_functions_tool(group: str | None = None, query: str | None = None,
                                     offset: Annotated[int, Field(ge=0)] = 0, limit: Annotated[int, Field(ge=1, le=50)] = 25) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(list_ta_catalog(group=group, query=query, offset=offset, limit=limit), "list_ta_functions ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="run_ta_function", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def run_ta_function(context_ref: str, expected_revision: Annotated[int, Field(gt=0)], chart_session: str, symbol: str,
                              function: str, parameters: dict[str, int | float] | None = None,
                              price_sources: dict[str, str] | None = None, periods_constant: Annotated[int, Field(ge=2, le=4000)] = 14) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(run_ta(STORE, context_ref, expected_revision, chart_session, symbol, function, parameters, price_sources, periods_constant), "run_ta_function ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="read_ta_result", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def read_ta_result(context_ref: str, expected_revision: Annotated[int, Field(gt=0)], chart_session: str, symbol: str,
                             result_ref: str, output_name: str, offset: Annotated[int, Field(ge=0)] = 0,
                             limit: Annotated[int, Field(ge=1, le=250)] = 200) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(read_ta(STORE, context_ref, expected_revision, chart_session, symbol, result_ref, output_name, offset, limit), "read_ta_result ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="run_chart_function", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def run_chart_function_tool(context_ref: str, expected_revision: Annotated[int, Field(gt=0)], chart_session: str,
                                      symbol: str, function: str, parameters: dict[str, Any]) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(run_chart_function(STORE, context_ref, expected_revision, chart_session, symbol, function, parameters), "run_chart_function ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="prepare_chart_edit", structured_output=True)
    async def prepare_chart_edit(context_ref: str, expected_revision: Annotated[int, Field(gt=0)], chart_session: str, symbol: str,
                                 request_id: Annotated[str, Field(min_length=1, max_length=128)], edit: CodexChartEdit) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(STORE.prepare(context_ref, expected_revision, chart_session, symbol, request_id, edit), "prepare_chart_edit ok", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="apply_chart_edit", structured_output=True)
    async def apply_chart_edit(context_ref: str, candidate_chart_session: str) -> Annotated[types.CallToolResult, ToolOutput]:
        try: return result(STORE.apply(context_ref, candidate_chart_session), "apply_chart_edit committed; UI receipt pending", chart=True)
        except Exception as exc: return failure(exc)

    @mcp.tool(name="get_chart_edit_status", annotations=types.ToolAnnotations(readOnlyHint=True), structured_output=True)
    async def get_chart_edit_status(context_ref: str, candidate_chart_session: str,
                                    wait_ms: Annotated[int, Field(ge=0, le=5000)] = 0) -> Annotated[types.CallToolResult, ToolOutput]:
        if wait_ms: await asyncio.sleep(wait_ms / 1000)
        try: return result(STORE.status(context_ref, candidate_chart_session), "get_chart_edit_status ok", chart=True)
        except Exception as exc: return failure(exc)

    APP_ACTIONS = frozenset({"activate", "observe", "close", "analyze_kline", "search_symbols", "fetch_candles", "data_source_status",
                             "symbol_directory", "watchlist_get", "watchlist_save", "fetch_market_ticker",
                             "fetch_market_pulse", "fetch_market_board_detail", "fetch_security_intelligence",
                             "fetch_security_workspace", "fetch_comparison_candles", "market_ticker",
                             "calculate_chart_indicators", "calc_range", "analyze_key_levels", "test_ftshare_connection",
                             "configure_session_key", "clear_session_key", "workbench_run_ta", "workbench_run_chart_function",
                             "workbench_prepare_edit", "workbench_apply_edit", "workbench_edit_status", "ack_render"})

    @mcp.tool(name="ft_kline_app_action", meta={"ui": {"resourceUri": APP_RESOURCE_URI, "visibility": ["app"]}}, structured_output=True)
    async def ft_kline_app_action(action: str, arguments: dict[str, Any], app_instance: str) -> Annotated[types.CallToolResult, ToolOutput]:
        """Private MCP App bridge. Model-visible tools cannot invoke this action."""
        if action not in APP_ACTIONS: return result({"ok": False, "error": "unsupported_app_action"}, "unsupported_app_action", error=True)
        try:
            if action == "activate": data = STORE.claim(str(arguments.get("context_ref") or ""), app_instance)
            elif action == "observe":
                state = STORE._state(str(arguments.get("context_ref") or ""), app_instance=app_instance, claim=True)
                data = {"ok": True, "context_ref": state.context_ref, "revision": state.revision, "chart_session": state.chart_session}
            elif action == "close": STORE.close(str(arguments.get("context_ref") or ""), app_instance=app_instance); data = {"ok": True}
            elif action == "configure_session_key":
                state = STORE._state(str(arguments.get("context_ref") or ""), app_instance=app_instance, claim=True)
                key = str(arguments.get("api_key") or "").strip()
                if len(key) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in key): raise LineError("invalid_api_key", "FTShare API Key 格式无效。")
                if os.environ.get("FTSHARE_API_KEY"): state.session_key = None; source = "environment"
                else: state.session_key = key or None; source = "session" if key else "none"
                clear_provider_caches(); data = {"ok": True, "configured": bool(os.environ.get("FTSHARE_API_KEY") or state.session_key), "credential_source": source, "persistent": False, "key_echoed": False}
            elif action == "clear_session_key":
                state = STORE._state(str(arguments.get("context_ref") or ""), app_instance=app_instance, claim=True); state.session_key = None; clear_provider_caches(); data = {"ok": True, "configured": bool(os.environ.get("FTSHARE_API_KEY")), "credential_source": "environment" if os.environ.get("FTSHARE_API_KEY") else "none", "persistent": False}
            elif action == "workbench_run_ta":
                _app_context(arguments, app_instance); data = run_ta(STORE, **arguments)
            elif action == "workbench_run_chart_function":
                _app_context(arguments, app_instance); data = run_chart_function(STORE, **arguments)
            elif action == "workbench_prepare_edit":
                _app_context(arguments, app_instance)
                arguments["edit"] = CodexChartEdit.model_validate(arguments.get("edit"))
                data = STORE.prepare(**arguments)
            elif action == "workbench_apply_edit":
                _app_context(arguments, app_instance); data = STORE.apply(**arguments)
            elif action == "workbench_edit_status":
                _app_context(arguments, app_instance); data = STORE.status(**arguments)
            elif action == "ack_render":
                _app_context(arguments, app_instance); data = STORE.acknowledge(**arguments)
            elif action == "analyze_kline":
                context_ref = _app_context(arguments, app_instance, consume=True)
                with _session_credential(context_ref): analyzed = analyze_symbol(**arguments)
                data = _attach_chart(analyzed) if analyzed.get("ok") else analyzed
            elif action == "search_symbols":
                _app_context(arguments, app_instance, consume=True); data = search_symbols(**arguments)
            elif action == "fetch_candles":
                context_ref = _app_context(arguments, app_instance, consume=True)
                with _session_credential(context_ref): data = fetch_candles(**arguments)
            elif action == "data_source_status":
                context_ref = _app_context(arguments, app_instance)
                with _session_credential(context_ref): data = _data_source_payload()
                if not os.environ.get("FTSHARE_API_KEY"):
                    data["providers"]["ftshare"]["credential_source"] = "session" if STORE._state(context_ref).session_key else "none"
                    data["anonymous_mode"] = not bool(STORE._state(context_ref).session_key)
                    data["providers"]["ftshare"]["can_clear"] = bool(STORE._state(context_ref).session_key)
            elif action == "symbol_directory":
                context_ref = _app_context(arguments, app_instance)
                with _session_credential(context_ref): data = symbol_directory(force_refresh=bool(arguments.get("refresh", False)))
            elif action == "watchlist_get":
                data = STORE.get_watchlist(_app_context(arguments, app_instance), app_instance=app_instance)
            elif action == "watchlist_save":
                data = STORE.save_watchlist(_app_context(arguments, app_instance), arguments.get("watchlist"), app_instance=app_instance)
            elif action == "calculate_chart_indicators":
                _app_context(arguments, app_instance, consume=True); data = calculate_chart_indicators(**arguments)
            elif action == "calc_range":
                _app_context(arguments, app_instance, consume=True); data = {"ok": True, **calc_range(**arguments)}
            elif action == "analyze_key_levels":
                _app_context(arguments, app_instance, consume=True); data = _key_levels_from_rows(arguments.get("symbol"), arguments.get("rows"))
            elif action == "test_ftshare_connection":
                context_ref = _app_context(arguments, app_instance, consume=True)
                with _session_credential(context_ref): data = test_ftshare_connection()
                data["persistent"] = False
                data["credential_source"] = "environment" if os.environ.get("FTSHARE_API_KEY") else ("session" if STORE._state(context_ref).session_key else "none")
            else:
                context_ref = _app_context(arguments, app_instance, consume=True)
                market_action = {
                    "fetch_market_ticker": fetch_market_ticker, "market_ticker": fetch_market_ticker,
                    "fetch_market_pulse": fetch_market_pulse,
                    "fetch_market_board_detail": fetch_market_board_detail,
                    "fetch_security_intelligence": fetch_security_intelligence,
                    "fetch_security_workspace": fetch_security_workspace,
                    "fetch_comparison_candles": fetch_comparison_candles,
                }[action]
                with _session_credential(context_ref): data = market_action(**arguments)
            return result(data, "app action ok" if data.get("ok") else str(data.get("message") or data.get("error")), error=not data.get("ok", False), chart=True)
        except Exception as exc:
            return failure(exc)


if __name__ == "__main__":
    mcp.run()
