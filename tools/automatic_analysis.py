"""Shared dispatch contract for automatic drawings in both chart hosts.

The recognizers own geometry and ordering. This module owns parameter defaults,
the closed-daily gate, and the analysis result shape. A new recognizer should be
registered here before either host exposes it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.channel_candidates import channel_candidates
from tools.closed_daily import closed_daily
from tools.lines import LineError
from tools.nine_count import nine_count
from tools.price_patterns import TYPES as PATTERN_TYPES, price_pattern_candidates
from tools.range_candidates import DEFAULT_WINDOW_SIZES, range_candidates
from tools.recent_drawing_candidates import recent_drawing_candidates


@dataclass(frozen=True)
class AnalysisSpec:
    required: tuple[str, ...]
    optional: tuple[str, ...]
    selection: str  # newest candidate first, or a complete count sequence
    defaults: dict[str, Any]
    version: str = "1"
    drawing_kind: str | None = None


AUTOMATIC_ANALYSES = {
    "recent_drawing_candidates": AnalysisSpec(("drawing_type",), ("lookback_bars", "max_candidates"), "first_candidate",
        {"lookback_bars": 120, "max_candidates": 5}),
    "channel_candidates": AnalysisSpec((), ("direction", "scope", "lookback_bars", "left_bars", "right_bars", "min_span_bars", "max_candidates", "closed_daily_only"), "first_candidate",
        {"direction": "both", "scope": "current", "lookback_bars": 120, "left_bars": 2, "right_bars": 2, "min_span_bars": 12, "max_candidates": 3}, "3", "channel"),
    "range_candidates": AnalysisSpec((), ("window_sizes", "max_candidates", "closed_daily_only"), "first_candidate",
        {"window_sizes": list(DEFAULT_WINDOW_SIZES), "max_candidates": 3}, drawing_kind="rectangle"),
    "price_pattern_candidates": AnalysisSpec((), ("pattern_types", "lookback_bars", "max_candidates", "anchor_times"), "first_candidate",
        {"pattern_types": list(PATTERN_TYPES), "lookback_bars": 240, "max_candidates": 5}, drawing_kind="price_pattern"),
    "nine_count": AnalysisSpec((), ("display_bars",), "whole_sequence", {"display_bars": 120}),
}

RECENT_DRAWING_KINDS = {"horizontal_line": "horizontal", "trend_line": "trend",
                        "fibonacci_retracement": "fibonacci", "labeled_polyline": "abc"}


def analyze_automatic(function: str, candles: list[dict[str, Any]], *,
                      symbol: str, interval: str, source_interval: str | None,
                      interval_value: int | None, provider: str | None,
                      volume_unit: str | None = None,
                      parameters: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (summary, normalized parameters), without modifying a chart."""
    spec = AUTOMATIC_ANALYSES.get(function)
    if spec is None:
        raise LineError("unknown_chart_function", "未知自动绘图分析函数。")
    values = dict(parameters or {})
    if values.keys() - set(spec.required + spec.optional):
        raise LineError("invalid_function_parameters", "参数不适用于该分析函数。")
    if any(key not in values or values[key] is None for key in spec.required):
        raise LineError("missing_anchor", "缺少必要的绘图类型。")
    effective = {**spec.defaults, **{key: value for key, value in values.items() if value is not None}}
    if not isinstance(candles, list):
        code = ("channel_candidate_data_unavailable" if function == "channel_candidates" else
                "range_candidate_data_unavailable" if function == "range_candidates" else "daily_analysis_unavailable")
        raise LineError(code, "当前图缺少可核对的已加载K线，未补取行情。")

    common = dict(symbol=symbol, interval=interval, source_interval=source_interval,
                  interval_value=interval_value, provider=provider)
    if function == "recent_drawing_candidates":
        result = recent_drawing_candidates(candles, **common, drawing_type=effective["drawing_type"],
            lookback_bars=effective["lookback_bars"], max_candidates=effective["max_candidates"])
        return result, values
    if function == "price_pattern_candidates":
        result = price_pattern_candidates(candles, **common, volume_unit=volume_unit,
            pattern_types=effective["pattern_types"], lookback_bars=effective["lookback_bars"],
            max_candidates=effective["max_candidates"],
            anchor_times=tuple(effective["anchor_times"]) if "anchor_times" in effective else None)
        return result, values
    if function == "nine_count":
        return nine_count(candles, **common, display_bars=effective["display_bars"]), values

    quality = None
    if effective.get("closed_daily_only"):
        candles, quality = closed_daily(candles, **common)
    if function == "channel_candidates":
        result = channel_candidates(candles, direction=effective["direction"],
            scope=effective["scope"], lookback_bars=effective["lookback_bars"],
            left_bars=effective["left_bars"], right_bars=effective["right_bars"],
            min_span_bars=effective["min_span_bars"], limit=effective["max_candidates"])
        normalized = {key: result[key] for key in ("direction", "scope", "lookback_bars", "left_bars", "right_bars", "min_span_bars")}
    else:
        result = range_candidates(candles, window_sizes=effective["window_sizes"],
                                  limit=effective["max_candidates"])
        normalized = {"window_sizes": result["window_sizes"]}
    normalized["max_candidates"] = effective["max_candidates"]
    if quality is not None:
        result = {**result, "as_of": quality["as_of"], "data_quality": quality}
        normalized["closed_daily_only"] = True
    return result, normalized


def stored_automatic_result(function: str, summary: dict[str, Any]) -> dict[str, Any]:
    """Persist only the immutable material needed by the guarded apply step."""
    if AUTOMATIC_ANALYSES[function].selection == "whole_sequence":
        return {key: summary[key] for key in ("marks", "events", "rule_version", "as_of")}
    return {key: summary[key] for key in ("candidates", "rule_version", "as_of", "drawing_type") if key in summary}


def candidate_function_for_kind(kind: str) -> str:
    if kind in RECENT_DRAWING_KINDS:
        return "recent_drawing_candidates"
    for function, spec in AUTOMATIC_ANALYSES.items():
        if spec.drawing_kind == kind:
            return function
    raise LineError("invalid_candidate_selection", "该图形不支持从候选结果绘制。")


def candidate_edit_parameters(kind: str, summary: dict[str, Any], number: int) -> dict[str, Any]:
    """Turn a guarded, 1-based candidate selection into editor parameters."""
    candidate_function_for_kind(kind)
    candidates = summary.get("candidates")
    if type(number) is not int or not 1 <= number <= 5 or not isinstance(candidates, list) or number > len(candidates):
        raise LineError("candidate_not_found", "所选候选不存在或不属于当前图。")
    selected = candidates[number - 1]
    if kind in RECENT_DRAWING_KINDS:
        if summary.get("drawing_type") != RECENT_DRAWING_KINDS[kind]:
            raise LineError("candidate_result_mismatch", "候选与当前绘图工具不匹配。")
        anchors = selected.get("anchors") if isinstance(selected, dict) else None
        count = 1 if kind == "horizontal_line" else 3 if kind == "labeled_polyline" else 2
        if not isinstance(anchors, list) or len(anchors) != count or any(
                not isinstance(anchor, dict) or "time" not in anchor or "price" not in anchor for anchor in anchors):
            raise LineError("candidate_result_invalid", "候选锚点不完整。")
        if kind == "horizontal_line":
            return {"price": anchors[0]["price"]}
        if kind == "labeled_polyline":
            return {"points": [{"label": "ABC"[index], "time": str(anchor["time"]), "price": anchor["price"]}
                               for index, anchor in enumerate(anchors)]}
        return {"start_time": str(anchors[0]["time"]), "start_price": anchors[0]["price"],
                "end_time": str(anchors[1]["time"]), "end_price": anchors[1]["price"]}
    if kind == "price_pattern":
        try:
            return {"pattern": selected, "rule_version": summary["rule_version"], "as_of": summary["as_of"]}
        except (TypeError, KeyError):
            raise LineError("candidate_result_invalid", "形态候选缺少规则版本或截止日。") from None
    if kind == "channel":
        try:
            anchors = selected["anchors"]
            return {prefix + "_time": str(anchors[key]["time"])
                    for prefix, key in (("start", "from"), ("end", "to"), ("parallel", "parallel"))} | {
                    prefix + "_price": anchors[key]["price"]
                    for prefix, key in (("start", "from"), ("end", "to"), ("parallel", "parallel"))}
        except (TypeError, KeyError):
            raise LineError("candidate_result_invalid", "通道候选锚点不完整。") from None
    try:
        return {"start_time": str(selected["start_time"]), "end_time": str(selected["end_time"]),
                "lower_price": selected["lower_price"], "upper_price": selected["upper_price"]}
    except (TypeError, KeyError):
        raise LineError("candidate_result_invalid", "平台候选边界不完整。") from None
