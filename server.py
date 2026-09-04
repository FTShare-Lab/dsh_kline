#!/usr/bin/env python3
"""Standalone DeepSeek Harness K-line MCP server.

This server owns the optional FTShare fetch adapter and deterministic indicator layer.
It does not spawn, import, or discover another MCP server.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from typing import Annotated, Any, Literal

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
from chart_service import publish_chart
from core.rows import RowsValidationError, validate_rows
from tools.calc import run_calc_metrics
from tools.draw import draw_kline
from tools.fetch import (
    _canonical_market_symbol,
    configure_ftshare_api_key,
    fetch_candles,
    ftshare_capabilities,
    ftshare_index_kline_available,
    ftshare_status,
    search_symbols as search_symbol_directory,
    test_ftshare_connection,
)


mcp = FastMCP(
    "dsh_kline",
    instructions=(
        "IMPORTANT workflow policy: For ordinary K-line requests, call analyze_kline "
        "exactly once. It performs one configured-source fetch, deterministic calculations, "
        "and chart generation against one row set. FTShare is optional: when another tool "
        "or application already has OHLCV rows, call analyze_kline_rows exactly once. "
        "Never call health, fetch_candles, "
        "or calc_metrics as a preflight or follow-up; never use shell, filesystem, "
        "scripts, web probes, or another chart generator for the same request. Do "
        "not switch providers or reconstruct market rows. If the provider rejects a "
        "symbol or interval, explain that error and stop; do not probe other symbols "
        "or substitute another interval unless the user explicitly asks. Use "
        "fetch_candles only when raw OHLCV rows are explicitly requested, and use "
        "calc_metrics only for caller-supplied rows. analyze_kline_rows accepts OHLCV rows "
        "from any user-selected data source without persisting provider state. Only calculate and annotate support "
        "and resistance when the user explicitly requests it: pass metrics including "
        "support_resistance or set mark_support_resistance=true. "
        " In DeepSeek Harness, say that the interactive chart is open in the right "
        "sidebar only when chart_ready is true; otherwise explain that the chart "
        "service is unavailable. Do not create files or claim that a chart was "
        "rendered based on a script or URL. Report count, interval, latest, and "
        "indicator values exactly as returned; do not infer a different bar count "
        "from the selected timeframe. Keep support/resistance labels from the "
        "metrics, but describe whether each level is above or below the latest "
        "close instead of calling an above-price support a current support. "
        "Use data_source_status, configure_ftshare, or test_ftshare_connection only "
        "when the user explicitly asks to inspect or configure a data source. "
        "Market data may be delayed, incomplete, or unavailable; results and indicators "
        "are informational and do not constitute investment advice."
    ),
    json_response=True,
)


_SUPPORTED_INDICATORS = frozenset({"ma", "vol", "macd", "kdj", "boll", "rsi", "atr", "vwap"})
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}(?:\.[A-Z]{2,6})?$", re.IGNORECASE)
_SUPPORTED_INTERVALS = ("minute", "day", "week", "month", "quarter", "year")


def _validate_interval(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Return a normalized interval and a user-facing error without Pydantic internals."""
    raw = str(value or "").strip().lower()
    if raw in _SUPPORTED_INTERVALS:
        return raw, None
    return None, {
        "error": "unsupported_interval",
        "message": f"不支持的 K 线周期“{value}”。请选择：{'、'.join(_SUPPORTED_INTERVALS)}。",
        "supported_intervals": list(_SUPPORTED_INTERVALS),
    }


def _resolve_symbol_input(value: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Resolve a local-directory name/code without making a provider request."""
    raw = str(value or "").strip()
    if not raw:
        return None, None, {
            "error": "invalid_symbol",
            "message": "请输入标的代码或名称，例如 600519.SH、00700.HK、NVDA.US。",
        }
    directory = search_symbol_directory(raw, limit=8)
    results = directory.get("results") if isinstance(directory, dict) else None
    if isinstance(results, list) and results:
        folded = raw.casefold()
        exact = next(
            (item for item in results if str(item.get("symbol") or "").casefold() == folded
             or str(item.get("name") or "").casefold() == folded),
            results[0],
        )
        symbol = str(exact.get("symbol") or "").strip().upper()
        if symbol:
            return symbol, str(exact.get("name") or symbol), None
    normalized = _canonical_market_symbol(raw)
    # Keep provider-specific symbols usable even when the local directory has
    # not been refreshed yet; reject unresolved natural-language names with a
    # useful, actionable message instead of a cryptic upstream error.
    if _SYMBOL_PATTERN.fullmatch(normalized):
        return normalized, None, None
    return None, None, {
        "error": "invalid_symbol",
        "message": f"未找到标的“{raw}”。请使用代码或完整代码格式，例如 600519.SH、00700.HK、NVDA.US。",
        "query": raw,
        "candidates": results[:5] if isinstance(results, list) else [],
    }


def _normalized_indicators(values: list[str] | None) -> tuple[list[str], list[str]]:
    requested = [str(value).strip().lower() for value in (values or ["ma", "vol", "macd", "rsi"])]
    active = list(dict.fromkeys(value for value in requested if value in _SUPPORTED_INDICATORS))
    unknown = list(dict.fromkeys(value for value in requested if value not in _SUPPORTED_INDICATORS))
    return active, unknown


def _normalized_ma_periods(values: list[int] | None) -> list[int]:
    periods = [int(value) for value in (values or DEFAULT_MA_PERIODS)]
    if not 1 <= len(periods) <= 8 or any(period < 2 or period > 400 for period in periods):
        raise ValueError("ma_periods must contain 1-8 values between 2 and 400")
    return list(dict.fromkeys(periods))


def _result(payload: dict[str, Any], text: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=error,
    )


def _error_text(payload: dict[str, Any], fallback: str) -> str:
    code = str(payload.get("error") or "").strip()
    message = str(payload.get("message") or code or fallback).strip()
    return f"{code}: {message}" if code and code not in message else message


def _latest(mapping: dict[int, float], timestamp: int) -> float | None:
    value = mapping.get(timestamp)
    return float(value) if value is not None else None


def _indicator_last(
    rows: list[dict[str, Any]],
    indicators: list[str],
    *,
    ma_periods: list[int],
    rsi_period: int,
    boll_period: int,
    boll_std: float,
    volume_ma: int,
    atr_period: int,
) -> dict[str, Any]:
    timestamp = int(rows[-1]["time"])
    result: dict[str, Any] = {}
    if "ma" in indicators:
        result["ma"] = {
            name: value
            for name, values in series_ma(rows, ma_periods).items()
            if (value := _latest(values, timestamp)) is not None
        }
    if "vol" in indicators:
        result["volume"] = float(rows[-1].get("volume") or 0.0)
        result["volume_ma"] = _latest(series_vol_ma(rows, volume_ma), timestamp)
    if "macd" in indicators:
        result["macd"] = {
            name: _latest(values, timestamp)
            for name, values in series_macd(rows).items()
        }
    if "kdj" in indicators:
        result["kdj"] = {
            name: _latest(values, timestamp)
            for name, values in series_kdj(rows, *DEFAULT_KDJ).items()
        }
    if "boll" in indicators:
        result["boll"] = {
            name: _latest(values, timestamp)
            for name, values in series_boll(rows, boll_period, boll_std).items()
        }
    if "rsi" in indicators:
        result["rsi"] = _latest(series_rsi(rows, rsi_period), timestamp)
    if "atr" in indicators:
        result["atr"] = _latest(series_atr(rows, atr_period), timestamp)
    if "vwap" in indicators:
        result["vwap"] = _latest(series_vwap(rows), timestamp)
    return result


def _support_resistance_marks(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    levels = metrics.get("support_resistance")
    if not isinstance(levels, dict):
        return []

    marks: list[dict[str, Any]] = []
    for kind, label, color in (
        ("support", "支撑", "success"),
        ("resistance", "压力", "danger"),
    ):
        candidates = levels.get(kind)
        if not isinstance(candidates, list):
            continue
        for index, level in enumerate(candidates[:5]):
            if not isinstance(level, dict):
                continue
            try:
                price = float(level["price"])
                timestamp = int(level["last_time"])
                touches = max(0, int(level.get("touches") or 0))
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(price) or timestamp <= 0:
                continue
            text = f"{label} {price:.2f}"
            if touches:
                text += f" · 触及{touches}次"
            marks.append(
                {
                    "id": f"{kind}:{timestamp}:{index}",
                    "time": timestamp,
                    "price": price,
                    "text": text,
                    "color": color,
                }
            )
    return marks


def _chart_spec(
    rows: list[dict[str, Any]],
    indicators: list[str],
    ma_periods: list[int],
    interval: str,
    marks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return provider-neutral chart data for future dsh-native UI support."""
    return {
        "type": "kline",
        "interval": interval,
        "rows": rows,
        "indicators": indicators,
        "ma_periods": ma_periods,
        "marks": list(marks or []),
        "range": {"start": int(rows[0]["time"]), "end": int(rows[-1]["time"])},
    }


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
    """Run the complete chart workflow on caller-supplied rows."""
    normalized = validate_rows(rows, min_len=2)
    selected = normalized[-max(2, min(int(limit), 4000)):]
    active_indicators, unknown_indicators = _normalized_indicators(indicators)
    periods = _normalized_ma_periods(ma_periods)
    requested_metrics = [str(value).lower() for value in metrics] if metrics is not None else ["rsi"]
    should_mark_levels = mark_support_resistance or "support_resistance" in requested_metrics
    if mark_support_resistance and "support_resistance" not in requested_metrics:
        requested_metrics.append("support_resistance")
    metric_data = run_calc_metrics(
        selected,
        metrics=requested_metrics,
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        atr_period=atr_period,
        volume_ma=volume_ma,
        ma_periods=periods,
    )
    analysis_marks = _support_resistance_marks(metric_data) if should_mark_levels else []
    previous = float(selected[-2]["close"])
    latest = dict(selected[-1])
    latest["change"] = round(float(latest["close"]) - previous, 6)
    latest["change_pct"] = round((float(latest["close"]) / previous - 1) * 100, 4) if previous else None
    source = str(data_source or "external").strip()[:120] or "external"
    chart_payload = draw_kline(
        selected,
        indicators=active_indicators,
        ma_periods=periods,
        marks=analysis_marks,
        security_workspace=security_workspace,
        symbol=symbol,
        name=name or symbol,
        data_source=source,
        data_source_url=data_source_url,
        interval=interval,
        boll_period=boll_period,
        boll_std=boll_std,
        volume_ma=volume_ma,
        rsi_period=rsi_period,
        atr_period=atr_period,
    )
    chart = _chart_spec(selected, active_indicators, periods, interval, analysis_marks)
    chart_session: str | None = None
    chart_service_status: dict[str, Any]
    try:
        chart_session, _service_url = publish_chart(chart_payload)
        chart["session_id"] = chart_session
        chart_service_status = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        chart_service_status = {"ok": False, "error": "chart_service_unavailable", "message": str(exc)}
    return {
        "ok": True,
        "workflow": "provided_rows_analyze_chart_session",
        "provider_mode": "external",
        "symbol": symbol,
        "name": name or symbol,
        "interval": interval,
        "adjust": adjust,
        "source": source,
        "status": "provided",
        "count": len(selected),
        "fetched_count": len(normalized),
        "freshness": "provided_by_caller",
        "chart_session": chart_session,
        "chart_ready": bool(chart_session and chart_service_status.get("ok")),
        "chart_service": chart_service_status,
        "latest": latest,
        "indicator_last": _indicator_last(
            selected,
            active_indicators,
            ma_periods=periods,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            atr_period=atr_period,
        ),
        "metrics": metric_data,
        "chart": chart,
        "warnings": ([f"ignored unsupported indicators: {', '.join(unknown_indicators)}"] if unknown_indicators else []),
    }


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
    data = {
        "ok": True,
        "external_rows": True,
        "providers": {
            "ftshare": {
                "available": bool(ftshare.get("available")),
                    "configured": bool(ftshare.get("configured")),
                    "persistent": bool(ftshare.get("persistent")),
                    "capabilities": ftshare_capabilities(),
                    "index_kline": ftshare_index_kline_available(),
                    "sdk_version": ftshare.get("sdk_version"),
                    "contracts": ftshare.get("contracts", {}),
                    "optional_capabilities": ["minute_candles", "news", "market_data", "company_data"],
            }
        },
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
    return _result(data, f"search_symbols ok · {data.get('count', 0)} results")


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


@mcp.tool(name="analyze_kline_rows")
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
    """Analyze caller-supplied OHLCV rows and open the native chart sidebar."""
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
    return _result(data, f"analyze_kline_rows ok · {data['symbol']} · {data['count']} bars · source={data['source']}")


@mcp.tool(name="analyze_kline")
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
    """Use this single call for ordinary K-line analysis; it also opens the native chart sidebar."""
    normalized_interval, interval_error = _validate_interval(interval)
    if interval_error:
        return _result({"ok": False, **interval_error}, interval_error["message"], error=True)
    resolved_symbol, resolved_name, symbol_error = _resolve_symbol_input(symbol)
    if symbol_error:
        return _result({"ok": False, **symbol_error}, symbol_error["message"], error=True)
    requested = max(2, min(int(limit), 4000))
    fetch_limit = requested if normalized_interval == "minute" else min(4000, max(requested, int(requested * 1.8)))
    fetched = fetch_candles(
        resolved_symbol or symbol,
        interval=normalized_interval or "day",
        interval_value=interval_value,
        session_count=session_count,
        limit=fetch_limit,
        adjust=adjust,
    )
    if not fetched.get("ok"):
        return _result(fetched, _error_text(fetched, "analysis failed"), error=True)

    rows = list(fetched.get("rows") or [])[-requested:]
    if len(rows) < 2:
        data = {"ok": False, "error": "insufficient_candles", "message": "fewer than two candles", "symbol": symbol}
        return _result(data, data["message"], error=True)

    active_indicators, unknown_indicators = _normalized_indicators(indicators)
    periods = _normalized_ma_periods(ma_periods)
    requested_metrics = [str(value).lower() for value in metrics] if metrics is not None else ["rsi"]
    should_mark_levels = mark_support_resistance or "support_resistance" in requested_metrics
    if mark_support_resistance and "support_resistance" not in requested_metrics:
        requested_metrics.append("support_resistance")
    metric_data = run_calc_metrics(
        rows,
        metrics=requested_metrics,
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        atr_period=atr_period,
        volume_ma=volume_ma,
        ma_periods=periods,
    )
    analysis_marks = _support_resistance_marks(metric_data) if should_mark_levels else []
    previous = float(rows[-2]["close"])
    latest = dict(rows[-1])
    latest["change"] = round(float(latest["close"]) - previous, 6)
    latest["change_pct"] = round((float(latest["close"]) / previous - 1) * 100, 4) if previous else None
    chart_payload = draw_kline(
        rows,
        indicators=active_indicators,
        ma_periods=periods,
        marks=analysis_marks,
        symbol=str(fetched.get("symbol") or resolved_symbol or symbol),
        name=str(fetched.get("name") or resolved_name or symbol),
        data_source=str(fetched.get("source") or "ftshare"),
        interval=normalized_interval or "day",
        boll_period=boll_period,
        boll_std=boll_std,
        volume_ma=volume_ma,
        rsi_period=rsi_period,
        atr_period=atr_period,
    )
    chart = _chart_spec(rows, active_indicators, periods, normalized_interval or "day", analysis_marks)
    chart_session: str | None = None
    chart_service_status: dict[str, Any]
    try:
        chart_session, _service_url = publish_chart(chart_payload)
        chart["session_id"] = chart_session
        chart_service_status = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        chart_service_status = {
            "ok": False,
            "error": "chart_service_unavailable",
            "message": str(exc),
        }
    data = {
        "ok": True,
        "workflow": "fetch_analyze_chart_session",
        "symbol": fetched.get("symbol") or resolved_symbol or symbol,
        "name": fetched.get("name") or resolved_name or symbol,
        "interval": normalized_interval or "day",
        "adjust": fetched.get("adjust") or adjust,
        "source": fetched.get("source") or "ftshare",
        "status": fetched.get("status"),
        "count": len(rows),
        "fetched_count": len(fetched.get("rows") or []),
        "as_of": fetched.get("as_of"),
        "freshness": fetched.get("freshness"),
        "chart_session": chart_session,
        "chart_ready": bool(chart_session and chart_service_status.get("ok")),
        "chart_service": chart_service_status,
        "latest": latest,
        "indicator_last": _indicator_last(
            rows,
            active_indicators,
            ma_periods=periods,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            atr_period=atr_period,
        ),
        "metrics": metric_data,
        "chart": chart,
        "warnings": ([f"ignored unsupported indicators: {', '.join(unknown_indicators)}"] if unknown_indicators else []),
    }
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
            "warnings",
        )
    }
    return _result(data, "analyze_kline ok · " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Standalone dsh_kline MCP server")
    parser.add_argument("--http", action="store_true", help="Run streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    if args.http:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
