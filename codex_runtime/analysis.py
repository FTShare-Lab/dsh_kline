"""Provider-neutral analysis and Codex chart payload construction."""
from __future__ import annotations

import math
import re
from typing import Any

from core.adjustment import adjustment_error, normalize_adjustment
from core.calc import (DEFAULT_ATR_PERIOD, DEFAULT_BOLL_PERIOD, DEFAULT_BOLL_STD, DEFAULT_KDJ,
                       DEFAULT_MA_PERIODS, DEFAULT_RSI_PERIOD, DEFAULT_VOLUME_MA, series_atr,
                       series_boll, series_kdj, series_ma, series_macd, series_rsi, series_vol_ma, series_vwap)
from core.rows import validate_rows
from tools.calc import AVAILABLE_METRICS, run_calc_metrics
from tools.draw import draw_kline
from tools.fetch import _canonical_market_symbol, fetch_candles, search_symbols

SUPPORTED_INTERVALS = ("minute", "day", "week", "month", "quarter", "year")
SUPPORTED_INDICATORS = frozenset({"ma", "vol", "macd", "kdj", "boll", "rsi", "atr", "vwap"})
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}(?:\.[A-Z]{2,6})?$", re.IGNORECASE)


def validate_interval(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    interval = str(value or "").strip().lower()
    if interval in SUPPORTED_INTERVALS:
        return interval, None
    return None, {"error": "unsupported_interval", "message": f"不支持的 K 线周期“{value}”。",
                  "supported_intervals": list(SUPPORTED_INTERVALS)}


def resolve_symbol(value: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None, {"error": "invalid_symbol", "message": "请输入标的代码或名称。"}
    directory = search_symbols(raw, limit=8)
    results = directory.get("results") if isinstance(directory, dict) else None
    if isinstance(results, list) and results:
        exact_codes = [item for item in results if str(item.get("symbol", "")).split(".")[0] == raw]
        if len(exact_codes) > 1:
            return None, None, {"error": "ambiguous_symbol", "message": "该代码对应多个市场，请选择完整代码。", "candidates": exact_codes}
        folded = raw.casefold()
        match = next((item for item in results if str(item.get("symbol") or "").casefold() == folded
                      or str(item.get("name") or "").casefold() == folded), results[0])
        symbol = str(match.get("symbol") or "").strip().upper()
        if symbol:
            return symbol, str(match.get("name") or symbol), None
    normalized = _canonical_market_symbol(raw)
    if SYMBOL_PATTERN.fullmatch(normalized):
        return normalized, None, None
    return None, None, {"error": "invalid_symbol", "message": f"未找到标的“{raw}”。", "candidates": results[:5] if isinstance(results, list) else []}


def normalized_indicators(values: list[str] | None) -> tuple[list[str], list[str]]:
    requested = [str(value).strip().lower() for value in (values or ["ma", "vol", "macd"])]
    return (list(dict.fromkeys(value for value in requested if value in SUPPORTED_INDICATORS)),
            list(dict.fromkeys(value for value in requested if value not in SUPPORTED_INDICATORS)))


def normalized_ma_periods(values: list[int] | None) -> list[int]:
    periods = [int(value) for value in (values or DEFAULT_MA_PERIODS)]
    if not 1 <= len(periods) <= 8 or any(period < 2 or period > 400 for period in periods):
        raise ValueError("ma_periods must contain 1-8 values between 2 and 400")
    return list(dict.fromkeys(periods))


def _latest(mapping: dict[int, float], timestamp: int) -> float | None:
    value = mapping.get(timestamp)
    return float(value) if value is not None else None


def indicator_last(rows: list[dict[str, Any]], indicators: list[str], *, ma_periods: list[int], rsi_period: int,
                   boll_period: int, boll_std: float, volume_ma: int, atr_period: int) -> dict[str, Any]:
    stamp, result = int(rows[-1]["time"]), {}
    if "ma" in indicators: result["ma"] = {name: value for name, values in series_ma(rows, ma_periods).items() if (value := _latest(values, stamp)) is not None}
    if "vol" in indicators: result.update(volume=float(rows[-1].get("volume") or 0), volume_ma=_latest(series_vol_ma(rows, volume_ma), stamp))
    if "macd" in indicators: result["macd"] = {name: _latest(values, stamp) for name, values in series_macd(rows).items()}
    if "kdj" in indicators: result["kdj"] = {name: _latest(values, stamp) for name, values in series_kdj(rows, *DEFAULT_KDJ).items()}
    if "boll" in indicators: result["boll"] = {name: _latest(values, stamp) for name, values in series_boll(rows, boll_period, boll_std).items()}
    if "rsi" in indicators: result["rsi"] = _latest(series_rsi(rows, rsi_period), stamp)
    if "atr" in indicators: result["atr"] = _latest(series_atr(rows, atr_period), stamp)
    if "vwap" in indicators: result["vwap"] = _latest(series_vwap(rows), stamp)
    return result


def support_resistance_marks(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    marks: list[dict[str, Any]] = []
    levels = metrics.get("support_resistance")
    if not isinstance(levels, dict): return marks
    for kind, label, color in (("support", "支撑", "success"), ("resistance", "压力", "danger")):
        for index, level in enumerate(levels.get(kind, [])[:5] if isinstance(levels.get(kind), list) else []):
            try:
                price, stamp = float(level["price"]), int(level["last_time"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(price) and stamp > 0:
                marks.append({"id": f"{kind}:{stamp}:{index}", "time": stamp, "price": round(price, 2),
                              "text": f"{label} {price:.2f}", "color": color})
    return marks


def analyze_rows(rows: list[dict[str, Any]], *, symbol: str, name: str | None, interval: str, limit: int,
                 adjust: str, indicators: list[str] | None, metrics: list[str] | None,
                 mark_support_resistance: bool, ma_periods: list[int] | None, rsi_period: int,
                 boll_period: int, boll_std: float, volume_ma: int, atr_period: int,
                 data_source: str | None, data_source_url: str | None = None,
                 security_workspace: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = validate_rows(rows, min_len=2)
    selected = normalized[-max(2, min(int(limit), 4000)):]
    active, unknown = normalized_indicators(indicators)
    periods = normalized_ma_periods(ma_periods)
    requested_metrics = [str(value).lower() for value in metrics] if metrics is not None else ["rsi"]
    if mark_support_resistance and "support_resistance" not in requested_metrics: requested_metrics.append("support_resistance")
    metric_data = run_calc_metrics(selected, metrics=requested_metrics, rsi_period=rsi_period, boll_period=boll_period,
                                   boll_std=boll_std, atr_period=atr_period, volume_ma=volume_ma, ma_periods=periods)
    marks = support_resistance_marks(metric_data) if (mark_support_resistance or "support_resistance" in requested_metrics) else []
    source = str(data_source or "external").strip()[:120] or "external"
    payload = draw_kline(selected, indicators=active, indicators_explicit=indicators is not None, ma_periods=periods,
                         marks=marks, security_workspace=security_workspace, symbol=symbol, name=name or symbol,
                         data_source=source, data_source_url=data_source_url, interval=interval, boll_period=boll_period,
                         boll_std=boll_std, volume_ma=volume_ma, rsi_period=rsi_period, atr_period=atr_period)
    payload["adjust"] = adjust
    previous, latest = float(selected[-2]["close"]), dict(selected[-1])
    latest["change"] = round(float(latest["close"]) - previous, 6)
    latest["change_pct"] = round((float(latest["close"]) / previous - 1) * 100, 4) if previous else None
    return {"ok": True, "workflow": "codex_analyze_chart", "provider_mode": "external", "symbol": symbol,
            "name": name or symbol, "interval": interval, "adjust": adjust, "source": source, "status": "provided",
            "count": len(selected), "fetched_count": len(normalized), "freshness": "provided_by_caller",
            "latest": latest, "indicator_last": indicator_last(selected, active, ma_periods=periods, rsi_period=rsi_period,
            boll_period=boll_period, boll_std=boll_std, volume_ma=volume_ma, atr_period=atr_period), "metrics": metric_data,
            "chart": {"type": "kline", "interval": interval, "rows": selected, "indicators": active,
                      "ma_periods": periods, "marks": marks,
                      "range": {"start": int(selected[0]["time"]), "end": int(selected[-1]["time"])}},
            "chart_payload": payload, "warnings": [f"ignored unsupported indicators: {', '.join(unknown)}"] if unknown else []}


def analyze_symbol(symbol: str, *, interval: str = "day", interval_value: int = 1, session_count: int | None = None,
                   limit: int = 220, adjust: str = "none", indicators: list[str] | None = None,
                   metrics: list[str] | None = None, mark_support_resistance: bool = False,
                   ma_periods: list[int] | None = None, rsi_period: int = DEFAULT_RSI_PERIOD,
                   boll_period: int = DEFAULT_BOLL_PERIOD, boll_std: float = DEFAULT_BOLL_STD,
                   volume_ma: int = DEFAULT_VOLUME_MA, atr_period: int = DEFAULT_ATR_PERIOD) -> dict[str, Any]:
    effective_adjust = normalize_adjustment(adjust)
    if effective_adjust is None: return adjustment_error()
    valid_interval, error = validate_interval(interval)
    if error: return {"ok": False, **error}
    resolved, name, symbol_error = resolve_symbol(symbol)
    if symbol_error: return {"ok": False, **symbol_error}
    fetched = fetch_candles(resolved or symbol, interval=valid_interval or "day", interval_value=interval_value,
                            session_count=session_count, limit=min(4000, max(2, int(limit))), adjust=effective_adjust)
    if not fetched.get("ok"): return fetched
    result = analyze_rows(list(fetched.get("rows") or []), symbol=str(fetched.get("symbol") or resolved or symbol),
                          name=str(fetched.get("name") or name or symbol), interval=valid_interval or "day", limit=limit,
                          adjust=str(fetched.get("adjust") or effective_adjust), indicators=indicators, metrics=metrics,
                          mark_support_resistance=mark_support_resistance, ma_periods=ma_periods, rsi_period=rsi_period,
                          boll_period=boll_period, boll_std=boll_std, volume_ma=volume_ma, atr_period=atr_period,
                          data_source=str(fetched.get("source") or "ftshare"), data_source_url=fetched.get("source_url"))
    result.update({key: fetched.get(key) for key in ("updated_at", "as_of", "exchange_timezone", "freshness", "status", "notice", "warnings") if key in fetched})
    result["fetched_count"] = len(fetched.get("rows") or [])
    return result


__all__ = ["AVAILABLE_METRICS", "analyze_rows", "analyze_symbol", "fetch_candles", "resolve_symbol", "search_symbols", "validate_interval"]
