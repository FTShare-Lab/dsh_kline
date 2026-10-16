#!/usr/bin/env python3
"""Standalone DeepSeek Harness K-line MCP server.

This server owns the optional FTShare fetch adapter and deterministic indicator layer.
It does not spawn, import, or discover another MCP server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
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
from chart_service import publish_chart, read_chart_snapshot, start_chart_service
from core.rows import RowsValidationError, validate_rows
from core.adjustment import AdjustmentInput, ADJUSTMENT_DESCRIPTION, normalize_adjustment, adjustment_error
from tools.calc import run_calc_metrics
from tools.draw import draw_kline
from tools.lines import ColorInput, LineError, edit_horizontal_line, horizontal_lines
from tools.trend_lines import edit_trend_line, trend_lines
from tools.channels import channels, edit_channel
from tools.rectangles import rectangles, edit_rectangle
from tools.drawing_verification import DrawingExpectation, verify_drawings
from tools.chart_context import read_chart_context
from tools.chart_edits import ChartEdit, prepare_chart_edit as prepare_guarded_chart_edit
from tools.chart_applications import request_chart_apply, read_edit_status
from tools.fetch import (
    _canonical_market_symbol,
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
        "Use market_pulse for an explicit whole-market overview, and use "
        "security_intelligence for an explicit request about a mainland stock's "
        "sector linkage, capital flows, or trading events; neither tool replaces "
        "analyze_kline for chart analysis. "
        "For the chart currently on screen, use get_chart_context with context_ref "
        "from THIS conversation's current runtime context. Never guess a reference, "
        "borrow another conversation or treat an older chart_session as live UI state. "
        "The context reports browser observations, separate loaded/visible ranges and "
        "After analyze_kline opens a chart, use the newly injected current-view reference "
        "to read its candles; an earlier launcher reference can become inactive during mounting. "
        "An inactive/loading reference is NOT a reason to call fetch_candles or analyze_kline again. "
        "Re-read a fresh reference when available, or report that the view is not ready. "
        "stored drawing objects, not visual proof. Context references are read-only "
        "and are NOT chart_session tokens. For current-view edits, prepare_chart_edit "
        "can prepare one guarded candidate using the observed revision and aligned source "
        "chart_session; supply a stable request_id for retries. Preparation does NOT apply "
        "to the browser. Then apply_chart_edit queues that exact candidate to its owning view; "
        "get_chart_edit_status reads its acknowledgment. queued/delivered are NOT applied. "
        "applied confirms view STATE, not screen pixels. Unknown results must not be automatically "
        "resent or bypassed with old snapshot-only tools. Read fresh current context before the next edit. "
        "For pending status use one bounded wait_ms=3000 query; if still pending explain it, "
        "do not tightly poll. expired/needs_attention is not an acknowledgment or permission to resend. "
        "drawing_feedback reports browser chart-object API observations, not screen pixels. "
        "created means registered object with matched shape/style; outside_time_viewport is geometric "
        "scope only, and outside_loaded_price_envelope is a warning, NOT proof the line is hidden. "
        "Explain hidden/failed/unknown items and their reasons; never turn apply_status=applied or "
        "created into a claim of visual verification. get_chart_context feedback is current-view "
        "observation; get_chart_edit_status feedback is historical for that application. "
        "Do not silently apply snapshot-only tools to a different "
        "symbol/period/range shown in the browser. If context is stale, ambiguous or "
        "unavailable explain that state instead of re-fetching market data to guess it. "
        "For explicit horizontal-line drawing use create_horizontal_line, then "
        "update_horizontal_line or delete_horizontal_line with its stable line_id. "
        "Use get_horizontal_lines to read back snapshot state. These tools never "
        "auto-select anchors. For explicit two-point segments use create_trend_line, "
        "get_trend_lines, update_trend_line, delete_trend_line. Require two explicit "
        "times and prices; date-only anchors use Asia/Shanghai and must match existing "
        "bars. Intraday anchors require exact bar-close ISO times with timezone or Unix "
        "seconds. Never fabricate unavailable anchors, snap dates, or substitute automatic levels. "
        "Distinguish literal drawing from analysis-assisted drawing. For literal requests, "
        "preserve the original USER-requested fields and ask about missing or ambiguous coordinates. "
        "When the user explicitly asks you to find/analyze a region or propose a drawing, "
        "YOU, the host, may derive a candidate from this conversation's actual chart candles; "
        "read fresh current context before making the proposal, not just old conversation rows. "
        "the plugin does not choose anchors or assess pattern quality. Do not ask the user "
        "to supply every coordinate merely because the execution tool needs explicit parameters. "
        "If the user asks for a proposal first, do not prepare, queue or mutate drawings before "
        "their confirmation. Give one preferred candidate with exact existing-bar dates, prices, "
        "a short data-grounded reason and a limitation; offer alternatives only when materially useful. "
        "Treat the user's confirmation as approval of THAT stated proposal plus their overrides. "
        "After confirmation read fresh context; if instrument/period/rows or relevant objects "
        "have changed, reassess and seek confirmation rather than silently moving the approved bounds. "
        "Numerical claims must agree with the candles; do not call volume monotonically declining "
        "when an intervening bar increases, or describe a subjective candidate as uniquely correct. "
        "For a chosen region, get_chart_context with region_start_time/region_end_time returns "
        "deterministic region_measurements without fetching or changing charts. body_envelope "
        "contains all open/close bodies; body_overlap is their common intersection, not the same range. "
        "Use boundary_evidence for the actual date and open/close field of each extremum. "
        "An empty intersection has no price shared by EVERY body; a point intersection shares exactly one. "
        "Never reinterpret relation=empty/exists=false as a shared zero-width point. "
        "Empty common intersection does NOT imply a gap uncovered by ANY body. The candidate "
        "difference is not an uncovered gap; union coverage is not measured. State only the "
        "measured result and its evidence, without extra coverage claims. "
        "Use volume_changes to distinguish a net decline from a monotonic decline. These measurements "
        "do NOT classify the region as a platform. Check chosen bounds with this before asking approval. "
        "If the data do not support a consolidation region, say so; do not force a platform, "
        "invent prices or imply a profitable prediction. Keep ordinary replies concise: proposal "
        "or changed object, reason/limitation, and one useful confirmation; omit internal IDs, "
        "revisions and protocol fields unless the user requests them or they explain a failure. "
        "For parallel channels use create_channel/get_channels/update_channel/delete_channel: "
        "two baseline anchors and a third time/price on the other boundary, within the "
        "start/end window. In literal mode ask for missing anchors; in authorized analysis mode "
        "derive and explain all three from real data under the proposal rules above. Geometry uses candle indices and "
        "linear prices, not elapsed calendar time. "
        "Before proposing a host-chosen channel, use read-only preview_chart_channel with three explicit "
        "anchors to check parallel geometry and full-region per-bar deviations. It never selects/fits "
        "anchors, draws, scores pattern quality or extends beyond the chosen dates. Horizontal body "
        "intersection is not a necessary criterion for a sloped channel. "
        "For explicit platform/range boxes use create_rectangle/get_rectangles/"
        "update_rectangle/delete_rectangle with start/end bar times and lower/upper "
        "prices. These draw finite rectangles, not automatic consolidation detection "
        "or flat channels. Ask for missing bounds in literal mode; an authorized host analysis "
        "may propose bounds from actual candles, but the execution tool always needs explicit values. "
        "Never swap reversed times/prices or replace "
        "a rectangle with two horizontal lines. "
        "Preserve the user's FULL requested label, without abbreviating T or U. Honor "
        "explicit colors: blue/蓝色=info, green/绿色=success, orange/橙色=warning, "
        "red/红色=danger. The token success in drawing style requests means green, "
        "not a generic success status. After each mutation call verify_chart_drawings "
        "with the original USER-requested fields, or the user-approved proposal and overrides, "
        "and the returned stable ID, NOT fields copied from the mutation result. Keep those "
        "expectations independently of the execution result. Verify exists=false after deletion; include "
        "requested name/color/anchors on create/update. If mismatched, correct only "
        "those requested fields using latest chart_session and verify again. Do not "
        "claim a name/color was applied merely because publication succeeded. A matched "
        "snapshot check is not visual verification. "
        "Perform drawing mutations sequentially, using each returned new chart_session; "
        "parallel edits of the same parent snapshot create branches, not a merged chart. "
        "Drawing tools never "
        "fetch candles; always use the latest chart_session returned in this "
        "conversation and its exact symbol. A mutation publishes a NEW immutable "
        "chart snapshot. It does not include manual browser edits. Do not re-run "
        "analyze_kline just to edit a line. Published commands are not proof of "
        "visible rendering: when render_verified is false say they were published, "
        "not visually verified. "
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
        exact_codes = [item for item in results if str(item.get("symbol", "")).split(".")[0] == raw]
        if len(exact_codes) > 1:
            return None, None, {"error": "ambiguous_symbol", "message": "该代码对应多个市场或标的，请选择完整代码。", "candidates": exact_codes}
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
        "message": f"未找到标的“{raw}”。" + (str(directory.get("message")) if directory.get("message") else "请使用完整代码，例如 600519.SH、00700.HK、NVDA.US。"),
        "query": raw,
        "candidates": results[:5] if isinstance(results, list) else [],
    }


def _normalized_indicators(values: list[str] | None) -> tuple[list[str], list[str]]:
    # Calm default stack: MA + VOL + MACD on the main chart. RSI, BOLL, KDJ,
    # ATR and VWAP are added only when explicitly requested.
    requested = [str(value).strip().lower() for value in (values or ["ma", "vol", "macd"])]
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
    canonical_adjust = normalize_adjustment(adjust)
    if canonical_adjust is None:
        return adjustment_error()
    adjust = canonical_adjust
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
        indicators_explicit=indicators is not None,
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
    chart_payload["adjust"] = adjust
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
    adjust: Annotated[AdjustmentInput, Field(description=ADJUSTMENT_DESCRIPTION)] = "none",
) -> types.CallToolResult:
    """Fetch raw OHLCV rows only when the user explicitly requests raw candle data."""
    canonical_adjust = normalize_adjustment(adjust)
    if canonical_adjust is None:
        data = adjustment_error()
        return _result(data, data["message"], error=True)
    adjust = canonical_adjust
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
    adjust: Annotated[AdjustmentInput, Field(description=ADJUSTMENT_DESCRIPTION + "；只标记调用方已有数据，不重新复权")] = "none",
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
    canonical_adjust = normalize_adjustment(adjust)
    if canonical_adjust is None:
        data = adjustment_error()
        return _result(data, data["message"], error=True)
    adjust = canonical_adjust
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


@mcp.tool(name="analyze_kline")
async def analyze_kline(
    symbol: Annotated[str, Field(description="标的代码，如 00700.HK / 600519.XSHG / NVDA.US")],
    interval: Annotated[str, Field(description="K 线周期：minute / day / week / month / quarter / year")] = "day",
    interval_value: Annotated[int, Field(ge=1, le=240, description="分钟粒度；非分钟周期通常为 1")] = 1,
    session_count: Annotated[int | None, Field(ge=1, le=10, description="分钟 K 的最近交易日数量")] = None,
    limit: Annotated[int, Field(ge=2, le=4000, description="最终分析使用的最近 K 线根数")] = 60,
    adjust: Annotated[AdjustmentInput, Field(description=ADJUSTMENT_DESCRIPTION)] = "none",
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
    canonical_adjust = normalize_adjustment(adjust)
    if canonical_adjust is None:
        data = adjustment_error()
        return _result(data, data["message"], error=True)
    adjust = canonical_adjust
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
    effective_adjust = normalize_adjustment(fetched.get("adjust"))
    if effective_adjust is None:
        data = adjustment_error(metadata=True)
        return _result(data, data["message"], error=True)

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
        indicators_explicit=indicators is not None,
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
    chart_payload["adjust"] = effective_adjust
    chart_payload["interval_value"] = interval_value
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
        "adjust": effective_adjust,
        **({"adjust_requested": adjust, "adjustment_warning": fetched.get("warning") or "Requested adjustment was not applied by the provider."} if effective_adjust != adjust else {}),
        "source": fetched.get("source") or "ftshare",
        "status": fetched.get("status"),
        "count": len(rows),
        "fetched_count": len(fetched.get("rows") or []),
        "history_warnings": fetched.get("warnings", []),
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
            "adjust",
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
    summary.update({key: data[key] for key in ("adjust_requested", "adjustment_warning") if key in data})
    return _result(data, "analyze_kline ok · " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))


def _horizontal_line_operation(
    action: str, chart_session: str, symbol: str, **changes: Any,
) -> types.CallToolResult:
    return _line_operation(action, chart_session, symbol, "horizontal", **changes)


def _drawing_snapshot(chart_session: str, symbol: str) -> dict[str, Any]:
    payload = read_chart_snapshot(chart_session)
    if payload is None:
        raise LineError("chart_session_not_found", "图表快照不存在或不属于当前 DSH，请使用当前对话返回的 chart_session。")
    if str(payload.get("symbol") or "").casefold() != symbol.strip().casefold():
        raise LineError("symbol_mismatch", "标的与图表快照不一致，未修改任何图形。")
    return payload


def _drawing_error(exc: LineError) -> types.CallToolResult:
    # Harness may show only TextContent for isError responses, not structuredContent.
    return _result({"ok": False, "error": exc.code}, f"{exc} · error={exc.code}", error=True)


def _line_operation(
    action: str, chart_session: str, symbol: str, family: str, **changes: Any,
) -> types.CallToolResult:
    read_lines, edit_line, title = {
        "horizontal": (horizontal_lines, edit_horizontal_line, "水平线"),
        "trend": (trend_lines, edit_trend_line, "趋势线"),
        "channel": (channels, edit_channel, "通道"),
        "rectangle": (rectangles, edit_rectangle, "平台框"),
    }[family]
    collection = {"channel": "channels", "rectangle": "rectangles"}.get(family, "lines")
    try:
        payload = _drawing_snapshot(chart_session, symbol)
    except LineError as exc:
        return _drawing_error(exc)
    data = {"ok": True, "symbol": payload.get("symbol"), "interval": payload.get("interval"),
            "count": payload.get("count"), "chart_session": chart_session,
            "render_verified": False, "scope": "explicit_chart_snapshot"}
    if action == "list":
        data[collection] = read_lines(payload)
        return _result(data, title + "快照状态 · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    if payload.get("view_source_guard"):
        return _drawing_error(LineError("current_view_source_requires_guarded_edit", "这是网页当前来源凭证，请读取新上下文并使用 prepare_chart_edit / apply_chart_edit；旧快照修改接口不适用。"))
    if payload.get("drawing_guard"):
        return _drawing_error(LineError("prepared_chart_not_applied", "该快照是尚未应用的准备结果，不能用旧绘图接口绕过当前图状态检查。"))
    try:
        edited, line = edit_line(payload, action, **changes)
    except LineError as exc:
        return _drawing_error(exc)
    edited["drawing_only"] = True
    edited["drawing_parent_session"] = chart_session
    try:
        token, _url = publish_chart(edited)
    except Exception:  # noqa: BLE001
        return _result({"ok": False, "error": "chart_service_unavailable"},
                       "绘图快照发布失败，原图未改变。 · error=chart_service_unavailable", error=True)
    data.update(chart_session=token, parent_chart_session=chart_session, chart_ready=True,
                operation=action, operation_status="published", render_status="not_verified",
                verification_required=True)
    data[{"channel": "channel", "rectangle": "rectangle"}.get(family, "line")] = line
    data[collection] = read_lines(edited)
    rows = next((c.get("rows", []) for c in payload["chartCommands"] if c.get("type") == "SET_CANDLES"), [])
    if family == "channel":
        prices = [line[edge][point]["price"] for edge in ("upper", "lower") for point in ("from", "to")]
    elif family == "rectangle":
        prices = [line["lower_price"], line["upper_price"]]
    else:
        prices = [line["from"]["price"], line["to"]["price"]] if family == "trend" else [line["price"]]
    if rows and action != "delete":
        low, high = min(r["low"] for r in rows), max(r["high"] for r in rows)
        outside = [p for p in prices if not low <= p <= high]
        if outside:
            data["out_of_range_prices"] = outside
            data["candle_price_range"] = {"low": low, "high": high}
            price_label = "通道边界价格" if family == "channel" else "指定价格"
            data["warnings"] = [f"{price_label} {outside} 超出当前 K 线高低范围 [{low}, {high}]，不是与最新收盘价比较；图形可能不在当前可见价格区间。"]
    return _result(data, title + "操作已发布，尚未核验屏幕呈现 · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="get_chart_context", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_chart_context(
    context_ref: Annotated[str, Field(description="当前对话运行时上下文提供的32字符引用；不是chart_session，不得猜测其他对话")],
    candle_scope: Literal["visible", "loaded", "none"] = "visible",
    limit: Annotated[int, Field(ge=1, le=4000, strict=True)] = 200,
    region_start_time: Annotated[str | None, Field(strict=True, description="可选：宿主选定测量区域的已有K线起点；与region_end_time同时填写") ] = None,
    region_end_time: Annotated[str | None, Field(strict=True, description="可选：测量终点；精确时间规则同画线，不吸附、不扩充行情") ] = None,
) -> types.CallToolResult:
    """Read the current conversation's live browser observation without fetching or changing charts.

    Read fresh context before analysis proposals and again after user confirmation before edits.
    When the user asks to find a drawing region, the HOST may choose a candidate from actual
    candles; the plugin does not choose/classify it. Before asking approval for that chosen
    region, call this with paired region_start_time/region_end_time to check numeric claims.
    A proposal-first request must not prepare/apply drawings before confirmation. Keep ordinary
    proposals concise; avoid arbitrary universal pattern thresholds and internal IDs.
    An inactive initial reference during mounting requires a newly injected current-view
    reference, NOT another market fetch or analyze call.
    Visible candles are actual viewport-index rows, not all loaded candles; unknown viewport
    stays unknown. Limit samples the last rows with explicit truncation. Stored object inventory
    is not proof of rendering; live_view_editable=false. No old-snapshot or global-latest fallback.
    data_provenance reports provider metadata and browser-input vs displayed intervals, not
    vendor-native granularity. local_aggregation (e.g. day -> week) explains a normal interval
    difference, not stale data by itself; aggregation completeness is NOT verified. Unknown
    providers/transforms must not be guessed. This metadata is not source-snapshot alignment
    or edit authorization; guarded edits still require exact current candles and AI inventory.
    After local period/range/symbol changes the browser can seal and confirm its current
    source without fetching or drawing. A pending/unconfirmed source is not editable: wait
    for fresh context, never refetch or fall back to old snapshot tools. Source binding does
    not approve a drawing proposal or move existing objects into a different period.
    Use time_display's deterministic +08:00 ISO/date labels when reporting dates; do not
    mentally convert Unix seconds or guess dates. Minute anchors require exact ISO times.
    Optional paired region times measure the full loaded region (max 4000 bars), independently
    of returned candle sampling. source_status is allowlisted diagnostic metadata only:
    checking means wait for a fresh report, blocked means follow next_action; an uncertain
    drawing outcome must be checked via get_chart_edit_status, never resent automatically.
    Source aligned is not drawing approval, pixel proof, vendor freshness or a guard bypass.
    Recheck only republishes/checks the current browser chart; it does not fetch quotes or queue drawings.
    Body envelope != common body intersection; volume net change
    != monotonic change. Measurements do not select/classify a platform or authorize drawing.
    boundary_evidence gives an actual bar's +08:00 date/ISO, source_fields (open/close/low/high),
    price and matched_bar_count for each extreme; ties use the first matching bar, not a unique
    or preferred drawing anchor. Cite these, not guessed dates. body_overlap's candidate lower
    is max(body lows), candidate upper is min(body highs): lower>upper is EMPTY (no shared
    price shared by EVERY body), equality is a POINT, lower<upper is a RANGE. Never turn exists=false/relation=empty
    into a shared point. These diagnostic candidates are not drawable bounds when empty.
    Empty common intersection does NOT imply a gap uncovered by ANY body. The candidate
    difference is not an uncovered gap; union coverage is not measured. Report the measured
    result with its witnesses, not extra coverage claims. A claim about a specific bar must
    be checked against that bar's actual open/close values, not inferred from the intersection.
    """
    try:
        data = read_chart_context(context_ref, candle_scope=candle_scope, limit=limit,
                                 region_start_time=region_start_time, region_end_time=region_end_time)
    except LineError as exc:
        return _drawing_error(exc)
    return _result(data, "当前图表上下文（网页观察，只读） · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="preview_chart_channel", annotations=types.ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def preview_chart_channel(
    context_ref: Annotated[str, Field(description="本对话运行时的当前视图引用；不是chart_session")],
    start_time: Annotated[str, Field(strict=True, description="基准线起点，必须精确对应当前图已有K线")],
    start_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    end_time: Annotated[str, Field(strict=True, description="基准线终点，必须晚于起点，不交换、不吸附")],
    end_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    parallel_time: Annotated[str, Field(strict=True, description="另一边界的第三点，须在起止区间内")],
    parallel_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    bar_limit: Annotated[int, Field(ge=1, le=4000, strict=True, description="逐根结果只返回前N根；汇总核对完整区间，最多4000根") ] = 200,
) -> types.CallToolResult:
    """Preview a HOST-chosen three-anchor channel against fresh current browser candles, read-only.

    The host selects explicit anchors from fresh actual candles under user-authorized analysis;
    this tool never searches/fits/selects anchors or judges professional pattern quality. Use it
    before proposing a channel, without shell arithmetic or refetching candles. Date-only anchors
    use UTC+08:00 on daily/larger bars; minute bars need exact timezone ISO or Unix seconds.
    Geometry is identical to channel execution: candle_index_linear_price, finite inclusive
    start/end, no calendar-time slope or extrapolated bars. Returns upper/lower boundaries,
    raw signed wick/body distances, full-region exceedance counts and worst-bar witnesses.
    Positive high_minus_upper is above the upper boundary; negative low_minus_lower is below
    the lower. Body variants use max/min(open, close). Counts ignore only the disclosed floating
    roundoff allowance, NOT a market tolerance; no touch count, fit score or recognition is given.
    An empty horizontal body intersection does not disqualify a sloped channel. Containment does
    not prove a meaningful pattern, predictive power or uniqueness. Do not add unsupported claims.
    bar_limit truncates only the returned per-bar list, never the full-region summary (max4000).
    exact_matching_ohlc_fields are exact matches only; caller-supplied prices need not be extrema.
    No chart fetch, snapshot publication, prepare/apply, drawing or edit authorization occurs.
    A preview is arithmetic, NOT a visual preview or rendering receipt. Re-read fresh context
    after user confirmation and preserve the independently approved anchors for guarded execution.
    """
    try:
        observed = read_chart_context(context_ref, candle_scope="none", channel_candidate=dict(
            start_time=start_time, start_price=start_price, end_time=end_time, end_price=end_price,
            parallel_time=parallel_time, parallel_price=parallel_price, bar_limit=bar_limit))
    except LineError as exc:
        return _drawing_error(exc)
    data = {k: observed[k] for k in ("ok", "context_ref", "conversation_id", "view_id", "revision",
            "observed_at_ms", "observation_source", "source_chart_session", "symbol", "interval",
            "interval_value", "ui_interval", "source_interval", "data_provenance", "adjust", "channel_preview")}
    return _result(data, "通道几何与偏差核对（只读，不绘图） · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="prepare_chart_edit")
async def prepare_chart_edit(
    context_ref: Annotated[str, Field(description="本对话 get_chart_context 返回的当前视图引用")],
    expected_revision: Annotated[int, Field(gt=0, strict=True, description="刚读回的观察 revision，不猜测或递增")],
    chart_session: Annotated[str, Field(description="当前观察的 source_chart_session；必须经行情与 AI 图形核对对齐")],
    symbol: str,
    request_id: Annotated[str, Field(min_length=1, max_length=128, description="同一次准备及重试使用同一 ID；不同参数不可复用")],
    edit: ChartEdit,
) -> types.CallToolResult:
    """Prepare, NOT APPLY, one current-view drawing candidate with revision/alignment guards.

    For proposal-first requests, call only AFTER the user approves the host's stated candidate;
    read fresh current context first, and preserve independently saved approved coordinates
    and user overrides. If relevant state changed, reassess before preparing. The host reasons,
    the executor does not choose points or validate pattern quality.
    Reuses the four deterministic AI drawing families. Reject stale/ambiguous/inactive contexts,
    unaligned snapshots, manual objects and parallel edits from a consumed revision.
    A replay returns the same candidate, never publishes another. Unknown publication outcomes
    stop retries. No fetching or automatic chart selection. Use apply_chart_edit explicitly next.
    """
    try:
        data = prepare_guarded_chart_edit(context_ref, expected_revision, chart_session, symbol, request_id, edit)
    except LineError as exc:
        return _drawing_error(exc)
    except OSError:
        return _drawing_error(LineError("chart_edit_storage_unavailable", "修改记录存储不可用，未确认准备结果；当前网页未修改。"))
    return _result(data, "绘图修改已准备，尚未应用到网页 · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="apply_chart_edit")
async def apply_chart_edit(context_ref: str, candidate_chart_session: str) -> types.CallToolResult:
    """Queue exactly this prepared candidate for its owning live view, never select a global chart.

    Idempotent for this immutable candidate. Queued/delivered do not prove application.
    Read get_chart_edit_status; applied confirms view state only, not screen pixels.
    Unknown outcomes stop automatic retries. No candle fetch or ordinary renderer bypass.
    """
    try: data = request_chart_apply(context_ref, candidate_chart_session)
    except LineError as exc: return _drawing_error(exc)
    except (OSError, ValueError, TypeError, KeyError):
        return _drawing_error(LineError("chart_application_unavailable", "应用请求未确认，请读取原候选状态，不自动创建或重发新候选。"))
    return _result(data, "绘图应用请求状态（不是屏幕核验） · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="get_chart_edit_status", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_chart_edit_status(
    context_ref: str, candidate_chart_session: str,
    wait_ms: Annotated[int, Field(ge=0, le=5000, strict=True)] = 0,
) -> types.CallToolResult:
    """Read the exact candidate's historical preparation/application state, not screen visibility.

    A verified prepared candidate without an application request returns prepared/not_requested.
    This does not prove the current view is editable or permit applying an old candidate after refresh.
    Optional bounded wait avoids tight polling; never fetches, republishes or invents a receipt.
    Read fresh get_chart_context separately before another mutation.
    """
    try:
        data = read_edit_status(context_ref, candidate_chart_session)
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while data["apply_status"] in {"queued", "delivered"} and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(min(0.2, max(0, deadline - asyncio.get_running_loop().time())))
            data = read_edit_status(context_ref, candidate_chart_session)
    except LineError as exc: return _drawing_error(exc)
    return _result(data, "绘图准备 / 应用历史（不代表当前视图或屏幕像素） · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


@mcp.tool(name="get_horizontal_lines", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_horizontal_lines(
    chart_session: Annotated[str, Field(description="当前对话最近一次工具返回的 chart_session")],
    symbol: Annotated[str, Field(description="该快照的完整标的代码")],
) -> types.CallToolResult:
    """Read exact AI horizontal lines in the named snapshot; no market fetch or UI claim."""
    return _horizontal_line_operation("list", chart_session, symbol)


@mcp.tool(name="create_horizontal_line")
async def create_horizontal_line(
    chart_session: Annotated[str, Field(description="当前对话最近一次工具返回的 chart_session")],
    symbol: Annotated[str, Field(description="该快照的完整标的代码")],
    price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True, description="用户指定的精确价格")],
    name: Annotated[str, Field(max_length=48, description="用户指定的完整名称，原样保留，不得缩写")] = "",
    color: Annotated[ColorInput, Field(description="按用户颜色填写；蓝色/info、绿色/success、橙色/warning、红色/danger；success不是成功状态")] = "info",
    request_id: Annotated[str | None, Field(min_length=1, max_length=128, description="可选重试标识；相同操作重试使用同一值")] = None,
) -> types.CallToolResult:
    """Create a user-requested full-width horizontal line and publish a new chart snapshot."""
    return _horizontal_line_operation("create", chart_session, symbol, price=price, name=name, color=color, request_id=request_id)


@mcp.tool(name="update_horizontal_line")
async def update_horizontal_line(
    chart_session: Annotated[str, Field(description="当前对话最新的 chart_session，不要使用旧快照")],
    symbol: str,
    line_id: Annotated[str, Field(description="create_horizontal_line 或 get_horizontal_lines 返回的 line.id")],
    price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    name: Annotated[str | None, Field(max_length=48, description="修改为用户完整指定名称，不缩写")] = None,
    color: Annotated[ColorInput | None, Field(description="仅在用户要求改色时填写，可直接传绿色/红色等；success=绿色")] = None,
) -> types.CallToolResult:
    """Move/rename/recolor one AI line by ID; preserve source candles and other lines."""
    return _horizontal_line_operation("update", chart_session, symbol, line_id=line_id, price=price, name=name, color=color)


@mcp.tool(name="delete_horizontal_line")
async def delete_horizontal_line(chart_session: str, symbol: str, line_id: str) -> types.CallToolResult:
    """Delete only the specified AI horizontal line; return a new snapshot, not a live UI receipt."""
    return _horizontal_line_operation("delete", chart_session, symbol, line_id=line_id)


@mcp.tool(name="create_trend_line")
async def create_trend_line(
    chart_session: str, symbol: str,
    start_time: Annotated[str, Field(description="起点：已有K线日期 YYYY-MM-DD（上海时区），或精确带时区ISO收盘时间/Unix秒字符串")],
    start_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    end_time: Annotated[str, Field(description="终点：必须是当前图中已有K线，且晚于起点；不自动就近匹配")],
    end_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    name: Annotated[str, Field(max_length=48, description="用户指定的完整趋势线名称，不缩写、不省略前缀")] = "",
    color: Annotated[ColorInput, Field(description="用户指定颜色；蓝色/info、绿色/success、橙色/warning、红色/danger")] = "info",
    request_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
) -> types.CallToolResult:
    """Draw an exact finite two-point segment. No rays, auto anchors, channels or market fetches.

    Use the latest chart_session in this conversation and perform mutations sequentially.
    """
    return _line_operation("create", chart_session, symbol, "trend", start_time=start_time,
                           start_price=start_price, end_time=end_time, end_price=end_price,
                           name=name, color=color, request_id=request_id)


@mcp.tool(name="get_trend_lines", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_trend_lines(chart_session: str, symbol: str) -> types.CallToolResult:
    """Read exact AI trend segments and stable IDs in this conversation's latest snapshot."""
    return _line_operation("list", chart_session, symbol, "trend")


@mcp.tool(name="update_trend_line")
async def update_trend_line(
    chart_session: str, symbol: str, line_id: str,
    start_time: str | None = None,
    start_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    end_time: str | None = None,
    end_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    name: Annotated[str | None, Field(max_length=48, description="用户指定的完整名称，不缩写")] = None,
    color: Annotated[ColorInput | None, Field(description="仅修改所请求颜色；绿色/green/success同义，红色/red/danger同义")] = None,
) -> types.CallToolResult:
    """Modify only supplied anchors/name/color by AI trend line ID. Preserve all other shapes.

    Same exact time rules as create_trend_line. Use latest chart_session, never the old parent.
    """
    return _line_operation("update", chart_session, symbol, "trend", line_id=line_id,
                           start_time=start_time, start_price=start_price, end_time=end_time,
                           end_price=end_price, name=name, color=color)


@mcp.tool(name="delete_trend_line")
async def delete_trend_line(chart_session: str, symbol: str, line_id: str) -> types.CallToolResult:
    """Delete one AI trend segment by ID from the latest snapshot; preserve horizontal/manual/auto lines."""
    return _line_operation("delete", chart_session, symbol, "trend", line_id=line_id)


@mcp.tool(name="create_channel")
async def create_channel(
    chart_session: Annotated[str, Field(description="当前对话最新chart_session，每次操作依次使用新快照")],
    symbol: str,
    start_time: Annotated[str, Field(description="基准线起点：已有K线日期，或带时区收盘时间/Unix秒字符串")],
    start_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    end_time: Annotated[str, Field(description="基准线终点：已有K线时间，必须晚于起点")],
    end_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    parallel_time: Annotated[str, Field(description="第三点：另一平行边界的已有K线时间，位于起止时间内；必须由用户明确提供")],
    parallel_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True, description="第三点精确价格，不得落在基准线上；不自动猜通道宽度")],
    name: Annotated[str, Field(max_length=48, description="用户指定的完整通道名称，不缩写")] = "",
    color: Annotated[ColorInput, Field(description="蓝色/info、绿色/success、橙色/warning、红色/danger")] = "info",
    show_midline: Annotated[bool, Field(strict=True, description="是否显示通道中线，默认显示")] = True,
    request_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
) -> types.CallToolResult:
    """Create one finite parallel channel (ascending/descending/horizontal) from three explicit anchors.

    Exact bar-time rules as trend lines. Uses candle-index spacing and linear prices, not calendar
    elapsed time; no rays, log-price geometry, automatic identification or invented anchors.
    Read returned upper/lower edges; verify user-requested fields via verify_chart_drawings.
    """
    return _line_operation("create", chart_session, symbol, "channel", start_time=start_time,
                           start_price=start_price, end_time=end_time, end_price=end_price,
                           parallel_time=parallel_time, parallel_price=parallel_price,
                           name=name, color=color, show_midline=show_midline, request_id=request_id)


@mcp.tool(name="get_channels", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_channels(chart_session: str, symbol: str) -> types.CallToolResult:
    """Read AI channels, three source anchors, derived upper/lower edges and stable IDs. No market fetch."""
    return _line_operation("list", chart_session, symbol, "channel")


@mcp.tool(name="update_channel")
async def update_channel(
    chart_session: str, symbol: str,
    channel_id: Annotated[str, Field(description="创建/读取返回的channel.id，不是边界线ID")],
    start_time: str | None = None,
    start_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    end_time: str | None = None,
    end_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    parallel_time: str | None = None,
    parallel_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    name: Annotated[str | None, Field(max_length=48, description="完整名称，不缩写")] = None,
    color: Annotated[ColorInput | None, Field(description="可直接传绿色/红色等；省略表示不改色")] = None,
    show_midline: Annotated[bool | None, Field(strict=True)] = None,
) -> types.CallToolResult:
    """Edit one channel atomically; recalculate parallel boundaries from its three explicit anchors.

    Unspecified anchors remain fixed. Changing baseline may change width relative to the unchanged
    third anchor. To change width adjust parallel_price; no partial updates on invalid geometry.
    Use latest chart_session and verify original user-requested fields after publication.
    """
    return _line_operation("update", chart_session, symbol, "channel", channel_id=channel_id,
                           start_time=start_time, start_price=start_price, end_time=end_time,
                           end_price=end_price, parallel_time=parallel_time, parallel_price=parallel_price,
                           name=name, color=color, show_midline=show_midline)


@mcp.tool(name="delete_channel")
async def delete_channel(chart_session: str, symbol: str, channel_id: str) -> types.CallToolResult:
    """Delete one whole AI channel (both edges and optional midline), preserving all other drawings."""
    return _line_operation("delete", chart_session, symbol, "channel", channel_id=channel_id)


@mcp.tool(name="create_rectangle")
async def create_rectangle(
    chart_session: Annotated[str, Field(description="当前对话最新 chart_session，操作后依次使用新快照")],
    symbol: str,
    start_time: Annotated[str, Field(description="平台框起点：已有 K 线日期，或精确带时区收盘时间/Unix秒字符串")],
    end_time: Annotated[str, Field(description="平台框终点：已有 K 线时间，必须晚于起点；不自动就近匹配")],
    lower_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True, description="明确下沿：用户指定，或用户确认的宿主分析方案；执行器不选点")],
    upper_price: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True, description="平台上沿价格，必须高于下沿，不自动交换")],
    name: Annotated[str, Field(max_length=48, description="用户指定或确认方案的完整平台框名称，不缩写")] = "",
    color: Annotated[ColorInput, Field(description="蓝色/info、绿色/success、橙色/warning、红色/danger")] = "info",
    show_fill: Annotated[bool, Field(strict=True, description="是否显示淡色填充，默认显示；关闭后保留完整边框")] = True,
    request_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
) -> types.CallToolResult:
    """Create one finite time/price rectangle using explicit user or approved-proposal bounds.

    The executor does no pattern recognition: the host may analyze real candles when authorized,
    propose exact bounds, and honor a user's request to confirm before drawing. No invented bars or rays.
    Owns all four edges and optional fill under one stable ID. Verify the original requested/approved
    name/color/time/bounds/show_fill via verify_chart_drawings(kind='rectangle').
    """
    return _line_operation("create", chart_session, symbol, "rectangle", start_time=start_time,
                           end_time=end_time, lower_price=lower_price, upper_price=upper_price,
                           name=name, color=color, show_fill=show_fill, request_id=request_id)


@mcp.tool(name="get_rectangles", annotations=types.ToolAnnotations(readOnlyHint=True))
async def get_rectangles(chart_session: str, symbol: str) -> types.CallToolResult:
    """Read AI platform rectangles, exact time/price bounds, fill state and stable IDs. No market fetch."""
    return _line_operation("list", chart_session, symbol, "rectangle")


@mcp.tool(name="update_rectangle")
async def update_rectangle(
    chart_session: str, symbol: str,
    rectangle_id: Annotated[str, Field(description="创建/读回返回的 rectangle.id，不是名称或手动图形 ID")],
    start_time: str | None = None, end_time: str | None = None,
    lower_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    upper_price: Annotated[float | None, Field(gt=0, allow_inf_nan=False, strict=True)] = None,
    name: Annotated[str | None, Field(max_length=48, description="用户指定的完整名称，不缩写")] = None,
    color: Annotated[ColorInput | None, Field(description="仅修改所请求颜色；绿色/green/success同义")] = None,
    show_fill: Annotated[bool | None, Field(strict=True)] = None,
) -> types.CallToolResult:
    """Atomically edit one platform rectangle by ID; unspecified bounds/style remain fixed.

    Change one bound or both together; invalid time/price order rejects the whole update.
    Use the latest chart_session and verify original requested fields, not copied actual values.
    """
    return _line_operation("update", chart_session, symbol, "rectangle", rectangle_id=rectangle_id,
                           start_time=start_time, end_time=end_time, lower_price=lower_price,
                           upper_price=upper_price, name=name, color=color, show_fill=show_fill)


@mcp.tool(name="delete_rectangle")
async def delete_rectangle(chart_session: str, symbol: str, rectangle_id: str) -> types.CallToolResult:
    """Delete one whole AI rectangle (all four edges and fill), preserving every other drawing."""
    return _line_operation("delete", chart_session, symbol, "rectangle", rectangle_id=rectangle_id)


@mcp.tool(name="verify_chart_drawings", annotations=types.ToolAnnotations(readOnlyHint=True))
async def verify_chart_drawings(
    chart_session: str, symbol: str,
    expectations: Annotated[list[DrawingExpectation], Field(min_length=1, max_length=180,
        description="按原始要求或用户确认的方案及覆盖项独立填写期望，不抄修改结果；核对名称/颜色/锚点，删除填exists=false")],
) -> types.CallToolResult:
    """Read-only exact snapshot verification. Catch shortened labels, omitted colors and wrong anchors.

    Return each expected/actual field and mismatch; matches=false must not be described as success.
    Never publishes a snapshot or proves visible rendering. Verify only supplied expectations,
    not inferred human intent. Repair mismatches only within the user's existing instructions
    or confirmed proposal; never alter an approved plan to make a mismatching result pass.
    """
    try:
        payload = _drawing_snapshot(chart_session, symbol)
        checked = verify_drawings(payload, expectations)
    except LineError as exc:
        return _drawing_error(exc)
    data = {"ok": True, "chart_session": chart_session, "symbol": payload.get("symbol"),
            "interval": payload.get("interval"), **checked}
    return _result(data, "绘图参数核对（不代表屏幕核验） · " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Standalone dsh_kline MCP server")
    parser.add_argument("--http", action="store_true", help="Run streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    start_chart_service()
    if args.http:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
