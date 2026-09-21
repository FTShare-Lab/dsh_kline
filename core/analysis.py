"""Provider- and host-neutral K-line analysis pipeline.

This module deliberately knows nothing about DSH, Codex, sidebar state, or
runtime locator files. Rendering and publication belong to the application layer.
"""

from __future__ import annotations

import math
from typing import Any

from core.calc import (
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
from core.metrics import run_calc_metrics


_SUPPORTED_INDICATORS = frozenset({"ma", "vol", "macd", "kdj", "boll", "rsi", "atr", "vwap"})


def normalized_indicators(values: list[str] | None) -> tuple[list[str], list[str]]:
    """Normalize chart indicators while preserving first-seen order."""
    requested = [str(value).strip().lower() for value in (values or ["ma", "vol", "macd"])]
    active = list(dict.fromkeys(value for value in requested if value in _SUPPORTED_INDICATORS))
    unknown = list(dict.fromkeys(value for value in requested if value not in _SUPPORTED_INDICATORS))
    return active, unknown


def normalized_ma_periods(values: list[int] | None) -> list[int]:
    periods = [int(value) for value in (values or DEFAULT_MA_PERIODS)]
    if not 1 <= len(periods) <= 8 or any(period < 2 or period > 400 for period in periods):
        raise ValueError("ma_periods must contain 1-8 values between 2 and 400")
    return list(dict.fromkeys(periods))


def latest(mapping: dict[int, float], timestamp: int) -> float | None:
    value = mapping.get(timestamp)
    return float(value) if value is not None else None


def indicator_last(
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
            if (value := latest(values, timestamp)) is not None
        }
    if "vol" in indicators:
        result["volume"] = float(rows[-1].get("volume") or 0.0)
        result["volume_ma"] = latest(series_vol_ma(rows, volume_ma), timestamp)
    if "macd" in indicators:
        result["macd"] = {name: latest(values, timestamp) for name, values in series_macd(rows).items()}
    if "kdj" in indicators:
        result["kdj"] = {name: latest(values, timestamp) for name, values in series_kdj(rows, *DEFAULT_KDJ).items()}
    if "boll" in indicators:
        result["boll"] = {name: latest(values, timestamp) for name, values in series_boll(rows, boll_period, boll_std).items()}
    if "rsi" in indicators:
        result["rsi"] = latest(series_rsi(rows, rsi_period), timestamp)
    if "atr" in indicators:
        result["atr"] = latest(series_atr(rows, atr_period), timestamp)
    if "vwap" in indicators:
        result["vwap"] = latest(series_vwap(rows), timestamp)
    return result


def support_resistance_marks(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    levels = metrics.get("support_resistance")
    if not isinstance(levels, dict):
        return []

    marks: list[dict[str, Any]] = []
    for kind, label, color in (("support", "支撑", "success"), ("resistance", "压力", "danger")):
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
            marks.append({"id": f"{kind}:{timestamp}:{index}", "time": timestamp, "price": price,
                          "text": text, "color": color})
    return marks


def chart_spec(rows: list[dict[str, Any]], indicators: list[str], ma_periods: list[int], interval: str,
               marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"type": "kline", "interval": interval, "rows": rows, "indicators": indicators,
            "ma_periods": ma_periods, "marks": list(marks or []),
            "range": {"start": int(rows[0]["time"]), "end": int(rows[-1]["time"])}}


def analyze_rows(
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
    """Run deterministic analysis on caller-supplied canonical OHLCV rows."""
    from core.rows import validate_rows

    normalized = validate_rows(rows, min_len=2)
    selected = normalized[-max(2, min(int(limit), 4000)):]
    active_indicators, unknown_indicators = normalized_indicators(indicators)
    periods = normalized_ma_periods(ma_periods)
    requested_metrics = [str(value).lower() for value in metrics] if metrics is not None else ["rsi"]
    should_mark_levels = mark_support_resistance or "support_resistance" in requested_metrics
    if mark_support_resistance and "support_resistance" not in requested_metrics:
        requested_metrics.append("support_resistance")
    metric_data = run_calc_metrics(selected, metrics=requested_metrics, rsi_period=rsi_period,
                                   boll_period=boll_period, boll_std=boll_std, atr_period=atr_period,
                                   volume_ma=volume_ma, ma_periods=periods)
    analysis_marks = support_resistance_marks(metric_data) if should_mark_levels else []
    previous = float(selected[-2]["close"])
    latest_row = dict(selected[-1])
    latest_row["change"] = round(float(latest_row["close"]) - previous, 6)
    latest_row["change_pct"] = round((float(latest_row["close"]) / previous - 1) * 100, 4) if previous else None
    source = str(data_source or "external").strip()[:120] or "external"
    chart = chart_spec(selected, active_indicators, periods, interval, analysis_marks)
    chart["render_options"] = {
        "indicators_explicit": indicators is not None,
        "boll_period": boll_period, "boll_std": boll_std, "volume_ma": volume_ma,
        "rsi_period": rsi_period, "atr_period": atr_period,
        "security_workspace": security_workspace, "data_source_url": data_source_url,
    }
    chart_session = None
    chart_service_status = {"ok": False, "error": "chart_service_disabled"}
    return {
        "ok": True, "workflow": "provided_rows_analyze_chart_session", "provider_mode": "external",
        "symbol": symbol, "name": name or symbol, "interval": interval, "adjust": adjust, "source": source,
        "status": "provided", "count": len(selected), "fetched_count": len(normalized),
        "freshness": "provided_by_caller", "chart_session": chart_session,
        "chart_ready": bool(chart_session and chart_service_status.get("ok")),
        "chart_service": chart_service_status, "latest": latest_row,
        "indicator_last": indicator_last(selected, active_indicators, ma_periods=periods, rsi_period=rsi_period,
                                           boll_period=boll_period, boll_std=boll_std, volume_ma=volume_ma,
                                           atr_period=atr_period),
        "metrics": metric_data, "chart": chart,
        "warnings": ([f"ignored unsupported indicators: {', '.join(unknown_indicators)}"] if unknown_indicators else []),
    }


__all__ = ["analyze_rows", "chart_spec", "indicator_last", "normalized_indicators", "normalized_ma_periods",
           "support_resistance_marks"]
