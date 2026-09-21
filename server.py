#!/usr/bin/env python3
"""Standalone DeepSeek Harness K-line MCP server.

This server owns the optional FTShare fetch adapter and deterministic indicator layer.
It does not spawn, import, or discover another MCP server.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

# Embedded Windows Python's ._pth excludes the script directory. Resolve
# sibling modules from this package, independently of cwd and PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp import types
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from core.calc import (
    AVAILABLE_METRICS,
    DEFAULT_ATR_PERIOD,
    DEFAULT_BOLL_PERIOD,
    DEFAULT_BOLL_STD,
    DEFAULT_KDJ,
    DEFAULT_MA_PERIODS,
    DEFAULT_RSI_PERIOD,
    DEFAULT_VOLUME_MA,
    series_atr,
    series_boll,
    series_kdj,
    series_ma,
    series_macd,
    series_rsi,
    series_vwap,
    series_vol_ma,
)
from adapters.host import host_adapter_from_env
from core.rows import RowsValidationError, validate_rows
from tools.calc import run_calc_metrics
from core.analysis import (
    analyze_rows,
    chart_spec as _chart_spec,
    indicator_last as _indicator_last,
    normalized_indicators as _normalized_indicators,
    normalized_ma_periods as _normalized_ma_periods,
    support_resistance_marks as _support_resistance_marks,
)
from services.analysis_service import AnalysisService
from services.inputs import (
    SYMBOL_PATTERN as _SYMBOL_PATTERN,
    SUPPORTED_INTERVALS as _SUPPORTED_INTERVALS,
    resolve_symbol_input,
    validate_interval,
)
from tools.fetch import (
    configure_ftshare_api_key,
    data_source_capability_contract,
    fetch_candles,
    fetch_market_board_detail,
    fetch_market_pulse,
    fetch_security_intelligence,
    ftshare_capabilities,
    ftshare_index_kline_available,
    ftshare_status,
    search_symbols as search_symbol_directory,
    test_ftshare_connection,
)
from tools.watchlist import get_watchlist_state, save_watchlist_state
try:  # Built-in free fallback feeds (optional; independent of FTShare)
    from tools.free_sources import free_source_status as builtin_free_source_status
except Exception:  # noqa: BLE001
    builtin_free_source_status = None


_HOST_ADAPTER = host_adapter_from_env()

# Compatibility aliases retained for the existing direct-import tests and the
# chart HTTP module.  Actual host behavior lives in adapters.host.
def publish_chart(payload: dict[str, Any]) -> tuple[str, str]:
    if _HOST_ADAPTER.publish_chart_fn is None:
        raise RuntimeError("host chart adapter not enabled")
    return _HOST_ADAPTER.publish_chart_fn(payload)


def start_chart_service() -> None:
    _HOST_ADAPTER.start()

mcp = FastMCP(
    "dsh_kline",
    instructions=_HOST_ADAPTER.instructions,
    json_response=True,
)


_SUPPORTED_INDICATORS = frozenset({"ma", "vol", "macd", "kdj", "boll", "rsi", "atr", "vwap"})


def _validate_interval(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Compatibility wrapper for shared interval validation."""
    return validate_interval(value)


def _resolve_symbol_input(value: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Compatibility wrapper for shared local symbol resolution."""
    return resolve_symbol_input(value, search_symbol_directory)


def _result(payload: dict[str, Any], text: str, *, error: bool = False) -> types.CallToolResult:
    if _HOST_ADAPTER.result_transform_fn is not None:
        payload = _HOST_ADAPTER.result_transform_fn(payload)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=error,
    )


if _HOST_ADAPTER.register_fn is not None:
    _HOST_ADAPTER.register_fn(mcp)


_CHART_TOOL_META = _HOST_ADAPTER.chart_tool_meta


def _error_text(payload: dict[str, Any], fallback: str) -> str:
    code = str(payload.get("error") or "").strip()
    message = str(payload.get("message") or code or fallback).strip()
    return f"{code}: {message}" if code and code not in message else message


def _analysis_service() -> AnalysisService:
    """Build the application service with late-bound compatibility hooks."""
    return AnalysisService(
        fetch_candles_fn=lambda *args, **kwargs: fetch_candles(*args, **kwargs),
        chart_payload_fn=_HOST_ADAPTER.chart_payload_fn,
        publish_chart_fn=publish_chart if _HOST_ADAPTER.publish_chart_fn is not None else None,
    )


def _analysis_from_rows(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    name: str | None,
    interval: str,
    limit: int,
    adjust: str,
    indicators: list[str] | None,
    metrics: list[str] | None,
    mark_support_resistance: bool,
    ma_periods: list[int] | None,
    rsi_period: int,
    boll_period: int,
    boll_std: float,
    volume_ma: int,
    atr_period: int,
    data_source: str | None,
    data_source_url: str | None,
    security_workspace: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compatibility wrapper for the provider-neutral analysis service."""
    return _analysis_service().analyze_rows(
        rows,
        symbol=symbol,
        name=name,
        interval=interval,
        limit=limit,
        adjust=adjust,
        indicators=indicators,
        metrics=metrics,
        mark_support_resistance=mark_support_resistance,
        ma_periods=ma_periods,
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        volume_ma=volume_ma,
        atr_period=atr_period,
        data_source=data_source,
        data_source_url=data_source_url,
        security_workspace=security_workspace,
    )


@mcp.tool(name="health")
async def health() -> types.CallToolResult:
    """Check runtime health only when the user explicitly asks for a health check."""
    ftshare = ftshare_status()
    data = {
        "ok": True,
        "server": "dsh_kline",
        "capabilities": {"external_rows": True, "ftshare_adapter": bool(ftshare.get("available"))},
        "ftshare": ftshare,
    }
    state = "available" if data["capabilities"]["ftshare_adapter"] else "optional/missing"
    return _result(data, f"health ok · external_rows=available · ftshare={state}")


@mcp.tool(name="data_source_status")
async def data_source_status() -> types.CallToolResult:
    """Return safe data-source capability/configuration status for the UI."""
    ftshare = ftshare_status()
    providers: dict[str, Any] = {
        "ftshare": {
            "available": bool(ftshare.get("available")),
            "configured": bool(ftshare.get("configured")),
            "persistent": bool(ftshare.get("persistent")),
            "credential_source": ftshare.get("credential_source", "none"),
            "can_clear": bool(ftshare.get("can_clear")),
            "capabilities": ftshare_capabilities(),
            "index_kline": ftshare_index_kline_available(),
            "sdk_version": ftshare.get("sdk_version"),
            "contracts": ftshare.get("contracts", {}),
            "optional_capabilities": ["minute_candles", "news", "market_data", "company_data"],
        }
    }
    if builtin_free_source_status is not None:
        try:
            providers["builtin_free"] = builtin_free_source_status()
        except Exception:  # noqa: BLE001
            providers["builtin_free"] = {"available": False, "source": "builtin_free"}
    data = {
        "ok": True,
        "external_rows": True,
        "providers": providers,
        "capability_contract": data_source_capability_contract(),
    }
    return _result(data, "data_source_status ok")


@mcp.tool(name="search_symbols")
async def search_symbols_tool(
    query: Annotated[str, Field(description="标的代码、名称或常用简称")],
    limit: Annotated[int, Field(ge=1, le=20, description="最多返回的候选数量")] = 8,
) -> types.CallToolResult:
    """Search the local symbol directory; this does not call a market provider."""
    data = search_symbol_directory(query, limit=limit)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "搜索失败"), error=True)
    candidates = "；".join(f"{item['name']} ({item['symbol']})" for item in data.get("results", [])[:5])
    return _result(data, f"search_symbols · {candidates or data.get('message') or '未找到匹配标的'}")


@mcp.tool(name="configure_ftshare")
async def configure_ftshare(
    api_key: Annotated[str | None, Field(description="FTShare API Key；留空可清除当前配置")]=None,
    test_connection: Annotated[bool, Field(description="配置后是否发起一次最小连接测试")]=True,
    persist: Annotated[bool, Field(description="是否保存到本机，默认保存")]=True,
) -> types.CallToolResult:
    """Configure FTShare without returning the key; results include safe capability status."""
    data = configure_ftshare_api_key(api_key, test_connection=test_connection, persist=persist)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "FTShare 配置失败"), error=True)
    return _result(data, str(data.get("message") or "FTShare 配置已更新"))


@mcp.tool(name="test_ftshare_connection")
async def test_ftshare_connection_tool() -> types.CallToolResult:
    """Test the current anonymous/API-key FTShare connection without changing it."""
    data = test_ftshare_connection()
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "FTShare 连接失败"), error=True)
    return _result(data, str(data.get("message") or "FTShare 连接成功"))


@mcp.tool(name="market_pulse")
async def market_pulse(
    refresh: Annotated[bool, Field(description="是否绕过短时缓存并重新拉取")] = False,
    sections: Annotated[list[str] | None, Field(description="可选：仅加载 breadth、flows、sectors、concepts、rankings、events 中指定分组")]=None,
) -> types.CallToolResult:
    """Read selected market-intelligence sections; callers can load groups progressively."""
    data = fetch_market_pulse(refresh=refresh, sections=sections)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "市场脉搏加载失败"), error=True)
    pulse = data.get("market_pulse") or {}
    return _result(data, f"market_pulse · {pulse.get('as_of') or 'latest'} · sectors={len(pulse.get('hot_sectors') or [])}")


@mcp.tool(name="market_board_detail")
async def market_board_detail(
    name: Annotated[str, Field(description="行业或概念板块名称")],
    board_code: Annotated[str | None, Field(description="市场快照返回的板块代码")] = None,
    kind: Annotated[Literal["industry", "concept"], Field(description="板块类型")] = "industry",
) -> types.CallToolResult:
    """Read a market board snapshot and available funding history."""
    data = fetch_market_board_detail(name, board_code=board_code, kind=kind)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "板块详情加载失败"), error=True)
    board = data.get("board") or {}
    return _result(data, f"market_board_detail · {board.get('name') or name} · history={len(board.get('history') or [])}")


@mcp.tool(name="security_intelligence")
async def security_intelligence(
    symbol: Annotated[str, Field(description="沪深北股票代码，例如 600519.XSHG")],
    refresh: Annotated[bool, Field(description="是否绕过短时缓存并重新拉取")] = False,
) -> types.CallToolResult:
    """Read sector linkage, stock capital flow and trading-event context independently from charts."""
    resolved_symbol, resolved_name, symbol_error = _resolve_symbol_input(symbol)
    if symbol_error:
        return _result({"ok": False, **symbol_error}, symbol_error["message"], error=True)
    data = fetch_security_intelligence(resolved_symbol or symbol, name=resolved_name, refresh=refresh)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "标的情报加载失败"), error=True)
    intel = data.get("security_intelligence") or {}
    return _result(data, f"security_intelligence · {data.get('symbol')} · flows={len(intel.get('flows') or [])} · events={len(intel.get('events') or [])}")


@mcp.tool(name="get_watchlist")
async def get_watchlist() -> types.CallToolResult:
    """Read the user's persistent dsh_kline watchlist, shared across conversations."""
    data = {"ok": True, "watchlist": get_watchlist_state()}
    return _result(data, f"get_watchlist · {len(data['watchlist'].get('items') or [])} symbols")


@mcp.tool(name="save_watchlist")
async def save_watchlist(
    watchlist: Annotated[dict[str, Any], Field(description="完整自选状态：groups、items、activeGroupId、sort")],
) -> types.CallToolResult:
    """Replace the user's persistent watchlist with a validated complete state."""
    data = save_watchlist_state(watchlist)
    if not data.get("ok"):
        return _result(data, str(data.get("message") or "自选保存失败"), error=True)
    saved = data.get("watchlist") or {}
    return _result(data, f"save_watchlist · {len(saved.get('items') or [])} symbols")


@mcp.tool(name="fetch_candles")
async def fetch_candles_tool(
    symbol: Annotated[str, Field(description="标的代码，如 00700.HK / 600519.XSHG / NVDA.US")],
    interval: Annotated[str, Field(description="K 线周期：minute / day / week / month / quarter / year")] = "day",
    interval_value: Annotated[int, Field(ge=1, le=240, description="分钟粒度")] = 1,
    session_count: Annotated[int | None, Field(ge=1, le=10, description="分钟 K 的交易日数量")] = None,
    limit: Annotated[int, Field(ge=2, le=4000, description="回看窗口")] = 220,
    adjust: Annotated[Literal["none", "forward", "backward"], Field(description="复权方式")] = "none",
) -> types.CallToolResult:
    """Fetch raw OHLCV rows only when the user explicitly requests raw candle data."""
    normalized_interval, interval_error = _validate_interval(interval)
    if interval_error:
        return _result({"ok": False, **interval_error}, interval_error["message"], error=True)
    resolved_symbol, _resolved_name, symbol_error = _resolve_symbol_input(symbol)
    if symbol_error:
        return _result({"ok": False, **symbol_error}, symbol_error["message"], error=True)
    data = fetch_candles(
        resolved_symbol or symbol,
        interval=normalized_interval or "day",
        interval_value=interval_value,
        session_count=session_count,
        limit=limit,
        adjust=adjust,
    )
    if not data.get("ok"):
        return _result(data, _error_text(data, "fetch failed"), error=True)
    return _result(
        data,
        f"fetch_candles · {data.get('symbol')} · {data.get('count')} bars · source={data.get('source')}",
    )


@mcp.tool(name="calc_metrics")
async def calc_metrics(
    rows: Annotated[list[dict[str, Any]], Field(description="canonical OHLCV rows with unix-second time")],
    metrics: Annotated[list[str] | None, Field(description="指标子集：" + ", ".join(AVAILABLE_METRICS))] = None,
    rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
    boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
    boll_std: Annotated[float, Field(ge=0.5, le=5.0)] = DEFAULT_BOLL_STD,
    atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
    volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
) -> types.CallToolResult:
    """Calculate metrics only for rows explicitly supplied by the caller."""
    if not isinstance(rows, list):
        data = {"ok": False, "error": "invalid_external_rows", "message": "rows must be a list"}
        return _result(data, data["message"], error=True)
    if len(rows) > 12000:
        data = {"ok": False, "error": "too_many_rows", "message": "rows exceeds the 12000-item input safety limit"}
        return _result(data, data["message"], error=True)
    try:
        data = run_calc_metrics(
            rows,
            metrics=metrics,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            atr_period=atr_period,
            volume_ma=volume_ma,
        )
    except Exception as exc:  # noqa: BLE001
        return _result({"ok": False, "error": "calc_failed", "message": str(exc)}, str(exc), error=True)
    unknown = data.get("metrics_unknown") or []
    warning = f" · warnings=ignored unsupported metrics: {','.join(unknown)}" if unknown else ""
    return _result(data, f"calc_metrics ok · bars={data['count']} · computed={','.join(data['metrics_computed'])}{warning}")


@mcp.tool(name="analyze_kline_rows", meta=_CHART_TOOL_META)
async def analyze_kline_rows(
    rows: Annotated[list[dict[str, Any]], Field(description="来自任意数据源的 OHLCV 行；time 可为 Unix 秒或毫秒")],
    symbol: Annotated[str, Field(description="标的代码或名称")],
    name: Annotated[str | None, Field(description="标的名称")] = None,
    interval: Annotated[str, Field(description="K 线周期：minute / day / week / month / quarter / year")] = "day",
    limit: Annotated[int, Field(ge=2, le=4000, description="最终分析使用的最近 K 线根数")] = 60,
    adjust: Annotated[Literal["none", "forward", "backward"], Field(description="复权方式或外部数据源的标记")] = "none",
    indicators: Annotated[list[str] | None, Field(description="ma / vol / macd / kdj / boll / rsi / atr / vwap")] = None,
    metrics: Annotated[list[str] | None, Field(description="指标摘要子集，可选：" + ", ".join(AVAILABLE_METRICS))] = None,
    mark_support_resistance: Annotated[bool, Field(description="仅在用户明确要求支撑位/压力位时设为 true")] = False,
    ma_periods: Annotated[list[int] | None, Field(description=f"MA 周期，默认 {DEFAULT_MA_PERIODS}")] = None,
    rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
    boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
    boll_std: Annotated[float, Field(ge=0.5, le=5.0)] = DEFAULT_BOLL_STD,
    volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
    atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
    data_source: Annotated[str | None, Field(description="数据源名称，不要放 API key 或其他秘密")] = None,
    data_source_url: Annotated[str | None, Field(description="可选的 HTTPS 数据源说明链接")] = None,
    security_workspace: Annotated[dict[str, Any] | None, Field(description="可选的标准化新闻/简况数据")] = None,
) -> types.CallToolResult:
    """Analyze caller-supplied OHLCV rows and render the host's interactive chart."""
    normalized_interval, interval_error = _validate_interval(interval)
    if interval_error:
        return _result({"ok": False, **interval_error}, interval_error["message"], error=True)
    if not isinstance(rows, list):
        data = {"ok": False, "error": "invalid_external_rows", "message": "rows must be a list"}
        return _result(data, data["message"], error=True)
    if len(rows) > 12000:
        data = {"ok": False, "error": "too_many_rows", "message": "rows exceeds the 12000-item input safety limit"}
        return _result(data, data["message"], error=True)
    try:
        # In external-rows mode the symbol is only a display label.  Do not
        # resolve it through the local directory: BTC, TEST.X, backtest labels,
        # and custom Chinese names must remain completely provider-independent.
        resolved_symbol = str(symbol or "external").strip() or "external"
        resolved_name = name or resolved_symbol
        data = _analysis_from_rows(
            rows,
            symbol=resolved_symbol or symbol,
            name=name or resolved_name,
            interval=normalized_interval or "day",
            limit=limit,
            adjust=adjust,
            indicators=indicators,
            metrics=metrics,
            mark_support_resistance=mark_support_resistance,
            ma_periods=ma_periods,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            atr_period=atr_period,
            data_source=data_source,
            data_source_url=data_source_url,
            security_workspace=security_workspace,
        )
    except (RowsValidationError, TypeError, ValueError) as exc:
        data = {"ok": False, "error": "invalid_external_rows", "message": str(exc)}
        return _result(data, data["message"], error=True)
    return _result(data, f"analyze_kline_rows ok · {data['symbol']} · {data['count']} bars · source={data['source']} · chart_session={data['chart_session']}")


@mcp.tool(name="analyze_kline", meta=_CHART_TOOL_META)
async def analyze_kline(
    symbol: Annotated[str, Field(description="标的代码，如 00700.HK / 600519.XSHG / NVDA.US")],
    interval: Annotated[str, Field(description="K 线周期：minute / day / week / month / quarter / year")] = "day",
    interval_value: Annotated[int, Field(ge=1, le=240, description="分钟粒度；非分钟周期通常为 1")] = 1,
    session_count: Annotated[int | None, Field(ge=1, le=10, description="分钟 K 的最近交易日数量")] = None,
    limit: Annotated[int, Field(ge=2, le=4000, description="最终分析使用的最近 K 线根数")] = 60,
    adjust: Annotated[Literal["none", "forward", "backward"], Field(description="复权方式")] = "none",
    indicators: Annotated[list[str] | None, Field(description="ma / vol / macd / kdj / boll / rsi / atr / vwap")] = None,
    metrics: Annotated[list[str] | None, Field(description="指标摘要子集，可选：" + ", ".join(AVAILABLE_METRICS))] = None,
    mark_support_resistance: Annotated[bool, Field(description="仅在用户明确要求支撑位/压力位时设为 true；默认不标注")] = False,
    ma_periods: Annotated[list[int] | None, Field(description=f"MA 周期，默认 {DEFAULT_MA_PERIODS}")] = None,
    rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
    boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
    boll_std: Annotated[float, Field(ge=0.5, le=5.0)] = DEFAULT_BOLL_STD,
    volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
    atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
) -> types.CallToolResult:
    """Use this single call for K-line analysis and the host's interactive chart."""
    normalized_interval, interval_error = _validate_interval(interval)
    if interval_error:
        return _result({"ok": False, **interval_error}, interval_error["message"], error=True)
    resolved_symbol, resolved_name, symbol_error = _resolve_symbol_input(symbol)
    if symbol_error:
        return _result({"ok": False, **symbol_error}, symbol_error["message"], error=True)
    data = _analysis_service().analyze_symbol(
        resolved_symbol or symbol,
        resolved_name=resolved_name,
        interval=normalized_interval or "day",
        interval_value=interval_value,
        session_count=session_count,
        limit=limit,
        adjust=adjust,
        indicators=indicators,
        metrics=metrics,
        mark_support_resistance=mark_support_resistance,
        ma_periods=ma_periods,
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        volume_ma=volume_ma,
        atr_period=atr_period,
    )
    if not data.get("ok"):
        return _result(data, _error_text(data, "analysis failed"), error=True)
    summary = {
        key: data[key]
        for key in (
            "symbol",
            "name",
            "interval",
            "source",
            "status",
            "count",
            "as_of",
            "latest",
            "indicator_last",
            "metrics",
            "chart_ready",
            "chart_session",
            "warnings",
            "history_warnings",
        )
    }
    return _result(data, "analyze_kline ok · " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Standalone dsh_kline MCP server")
    parser.add_argument("--http", action="store_true", help="Run streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    _HOST_ADAPTER.start()
    if args.http:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
