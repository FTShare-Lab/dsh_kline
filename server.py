#!/usr/bin/env python3
"""Standalone DeepSeek Harness K-line MCP server.

This server owns the FTShare fetch adapter and deterministic indicator layer.
It does not spawn, import, or discover another MCP server.
"""

from __future__ import annotations

import argparse
import json
from typing import Annotated, Any, Literal

from mcp import types
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from core.calc import (
    AVAILABLE_METRICS,
    DEFAULT_ATR_PERIOD,
    DEFAULT_BOLL_PERIOD,
    DEFAULT_BOLL_STD,
    DEFAULT_MA_PERIODS,
    DEFAULT_RSI_PERIOD,
    DEFAULT_VOLUME_MA,
    series_atr,
    series_boll,
    series_ma,
    series_macd,
    series_rsi,
    series_vwap,
    series_vol_ma,
)
from tools.calc import run_calc_metrics
from tools.fetch import fetch_candles, ftshare_status


mcp = FastMCP(
    "dsh_kline",
    instructions=(
        "Use analyze_kline as the primary entry point. It performs FTShare fetch, "
        "deterministic calculations, and chart-spec generation against one row set. "
        "Do not switch providers or reconstruct market rows."
    ),
    json_response=True,
)


def _result(payload: dict[str, Any], text: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=error,
    )


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


def _chart_spec(
    rows: list[dict[str, Any]],
    indicators: list[str],
    ma_periods: list[int],
    interval: str,
) -> dict[str, Any]:
    """Return provider-neutral chart data for future dsh-native UI support."""
    return {
        "type": "kline",
        "interval": interval,
        "rows": rows,
        "indicators": indicators,
        "ma_periods": ma_periods,
        "range": {"start": int(rows[0]["time"]), "end": int(rows[-1]["time"])},
    }


@mcp.tool(name="health")
async def health() -> types.CallToolResult:
    """Check the local Python runtime and the FTShare SDK import status."""
    data = {"ok": True, "server": "dsh_kline", "ftshare": ftshare_status()}
    available = bool(data["ftshare"].get("available"))
    data["ok"] = available
    text = f"health {'ok' if available else 'failed'} · ftshare={'available' if available else 'missing'}"
    return _result(data, text, error=not available)


@mcp.tool(name="fetch_candles")
async def fetch_candles_tool(
    symbol: Annotated[str, Field(description="标的代码，如 00700.HK / 600519.XSHG / NVDA.US")],
    interval: Annotated[Literal["minute", "day", "week", "month", "quarter", "year"], Field(description="K 线周期")] = "day",
    interval_value: Annotated[int, Field(ge=1, le=240, description="分钟粒度")] = 1,
    session_count: Annotated[int | None, Field(ge=1, le=10, description="分钟 K 的交易日数量")] = None,
    limit: Annotated[int, Field(ge=2, le=4000, description="回看窗口")] = 220,
    adjust: Annotated[Literal["none", "forward", "backward"], Field(description="复权方式")] = "none",
) -> types.CallToolResult:
    """Fetch canonical OHLCV rows directly from the installed FTShare SDK."""
    data = fetch_candles(
        symbol,
        interval=interval,
        interval_value=interval_value,
        session_count=session_count,
        limit=limit,
        adjust=adjust,
    )
    if not data.get("ok"):
        return _result(data, str(data.get("message") or data.get("error") or "fetch failed"), error=True)
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
    """Calculate deterministic indicator summaries for supplied canonical rows."""
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
    return _result(data, f"calc_metrics ok · bars={data['count']} · computed={','.join(data['metrics_computed'])}")


@mcp.tool(name="analyze_kline")
async def analyze_kline(
    symbol: Annotated[str, Field(description="标的代码，如 00700.HK / 600519.XSHG / NVDA.US")],
    interval: Annotated[Literal["minute", "day", "week", "month", "quarter", "year"], Field(description="K 线周期")] = "day",
    interval_value: Annotated[int, Field(ge=1, le=240, description="分钟粒度；非分钟周期通常为 1")] = 1,
    session_count: Annotated[int | None, Field(ge=1, le=10, description="分钟 K 的最近交易日数量")] = None,
    limit: Annotated[int, Field(ge=2, le=4000, description="最终分析使用的最近 K 线根数")] = 60,
    adjust: Annotated[Literal["none", "forward", "backward"], Field(description="复权方式")] = "none",
    indicators: Annotated[list[str] | None, Field(description="ma / vol / macd / boll / rsi / atr / vwap")] = None,
    metrics: Annotated[list[str] | None, Field(description="指标摘要子集")] = None,
    ma_periods: Annotated[list[int] | None, Field(description=f"MA 周期，默认 {DEFAULT_MA_PERIODS}")] = None,
    rsi_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_RSI_PERIOD,
    boll_period: Annotated[int, Field(ge=2, le=200)] = DEFAULT_BOLL_PERIOD,
    boll_std: Annotated[float, Field(ge=0.5, le=5.0)] = DEFAULT_BOLL_STD,
    volume_ma: Annotated[int, Field(ge=2, le=200)] = DEFAULT_VOLUME_MA,
    atr_period: Annotated[int, Field(ge=2, le=100)] = DEFAULT_ATR_PERIOD,
) -> types.CallToolResult:
    """Single-call FTShare fetch, deterministic metrics, and chart-spec workflow."""
    requested = max(2, min(int(limit), 4000))
    fetch_limit = requested if interval == "minute" else min(4000, max(requested, int(requested * 1.8)))
    fetched = fetch_candles(
        symbol,
        interval=interval,
        interval_value=interval_value,
        session_count=session_count,
        limit=fetch_limit,
        adjust=adjust,
    )
    if not fetched.get("ok"):
        return _result(fetched, str(fetched.get("message") or fetched.get("error") or "analysis failed"), error=True)

    rows = list(fetched.get("rows") or [])[-requested:]
    if len(rows) < 2:
        data = {"ok": False, "error": "insufficient_candles", "message": "fewer than two candles", "symbol": symbol}
        return _result(data, data["message"], error=True)

    active_indicators = [
        str(value).lower()
        for value in (indicators or ["ma", "vol", "macd", "rsi"])
        if str(value).lower() in {"ma", "vol", "macd", "boll", "rsi", "atr", "vwap"}
    ]
    periods = [int(value) for value in (ma_periods or DEFAULT_MA_PERIODS)]
    metric_data = run_calc_metrics(
        rows,
        metrics=metrics or ["rsi"],
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        atr_period=atr_period,
        volume_ma=volume_ma,
        ma_periods=periods,
    )
    previous = float(rows[-2]["close"])
    latest = dict(rows[-1])
    latest["change"] = round(float(latest["close"]) - previous, 6)
    latest["change_pct"] = round((float(latest["close"]) / previous - 1) * 100, 4) if previous else None
    data = {
        "ok": True,
        "workflow": "fetch_analyze_chart_spec",
        "symbol": fetched.get("symbol") or symbol,
        "name": fetched.get("name") or symbol,
        "interval": interval,
        "adjust": fetched.get("adjust") or adjust,
        "source": fetched.get("source") or "ftshare",
        "status": fetched.get("status"),
        "count": len(rows),
        "fetched_count": len(fetched.get("rows") or []),
        "as_of": fetched.get("as_of"),
        "freshness": fetched.get("freshness"),
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
        "chart": _chart_spec(rows, active_indicators, periods, interval),
    }
    summary = {key: data[key] for key in ("symbol", "name", "interval", "source", "status", "count", "as_of", "latest", "indicator_last", "metrics")}
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
