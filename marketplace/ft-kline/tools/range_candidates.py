"""Read-only candidates for a *current* horizontal trading range.

This is a bounded geometry heuristic, not a breakout signal or a professional
pattern verdict. It is deliberately separate from the guarded rectangle editor.
"""
from __future__ import annotations

import math
from statistics import median

from core.rows import RowsValidationError, validate_rows
from tools.lines import LineError

RULE_VERSION = "current_range_wick_envelope_v1"
DEFAULT_WINDOW_SIZES = (20, 30, 40, 60)
MIN_WIDTH_FRACTION = 0.005
MAX_WIDTH_FRACTION = 0.12
TOUCH_DISTANCE_TO_WIDTH = 0.10
MIN_TOUCH_SEPARATION_BARS = 3
MAX_CLOSE_DRIFT_TO_WIDTH = 0.50
MAX_FITTED_DRIFT_TO_WIDTH = 0.50
RECENT_BARS = 10
MAX_RECENT_DRIFT_TO_WIDTH = 0.50


def _separated_touch_indexes(indexes):
    kept = []
    for index in indexes:
        if not kept or index - kept[-1] >= MIN_TOUCH_SEPARATION_BARS:
            kept.append(index)
    return kept


def _fitted_drift_to_width(closes, width):
    count = len(closes)
    x_mean = (count - 1) / 2
    y_mean = math.fsum(closes) / count
    denominator = math.fsum((index - x_mean) ** 2 for index in range(count))
    slope = math.fsum((index - x_mean) * (price - y_mean)
                      for index, price in enumerate(closes)) / denominator
    return abs(slope * (count - 1)) / width


def range_candidates(rows, *, window_sizes=DEFAULT_WINDOW_SIZES, limit=3):
    """Return up to ``limit`` boxed-range proposals ending at the latest bar.

    Candidate edges are the actual highest high and lowest low of each fixed
    window. Both edges need at least two separated wick touches; a narrow band
    alone is insufficient. Close drift and fitted close slope must each use no
    more than half the band width, both across the full window and the recent
    ten-bar tail. No projection or chart mutation occurs.
    """
    if (not isinstance(window_sizes, (tuple, list)) or not window_sizes
            or len(window_sizes) > 8 or any(type(size) is not int or not 16 <= size <= 120 for size in window_sizes)
            or len(set(window_sizes)) != len(window_sizes)):
        raise LineError("invalid_range_candidate_windows", "window_sizes 必须是1至8个互异的16至120整数。")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise LineError("invalid_range_candidate_limit", "limit 必须是1至5的整数。")
    windows = tuple(sorted(window_sizes))
    try:
        candles = validate_rows(rows, min_len=min(windows))
    except RowsValidationError:
        raise LineError("insufficient_range_candidate_history", "已加载K线不足以计算平台区间候选；未补取行情。") from None
    # A corrupt candle must not become an envelope boundary or a fake touch.
    recent = candles[-max(windows):]
    if any(row["low"] <= 0 or row["high"] < max(row["open"], row["close"], row["low"])
           or row["low"] > min(row["open"], row["close"]) for row in recent):
        raise LineError("invalid_range_candidate_data", "平台候选需要高低价为正且 OHLC 一致的K线；未忽略异常柱。")

    candidates = []
    evaluated_windows = []
    for size in windows:
        if size > len(candles):
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "insufficient_history"})
            continue
        segment = candles[-size:]
        high_index = max(range(size), key=lambda index: segment[index]["high"])
        low_index = min(range(size), key=lambda index: segment[index]["low"])
        upper = segment[high_index]["high"]
        lower = segment[low_index]["low"]
        width = upper - lower
        center = median(row["close"] for row in segment)
        if not math.isfinite(width) or width <= 0 or center <= 0:
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "invalid_width"})
            continue
        width_fraction = width / center
        if not MIN_WIDTH_FRACTION <= width_fraction <= MAX_WIDTH_FRACTION:
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "width_fraction_outside"})
            continue
        upper_touches = _separated_touch_indexes([
            index for index, row in enumerate(segment)
            if upper - row["high"] <= width * TOUCH_DISTANCE_TO_WIDTH
        ])
        lower_touches = _separated_touch_indexes([
            index for index, row in enumerate(segment)
            if row["low"] - lower <= width * TOUCH_DISTANCE_TO_WIDTH
        ])
        if len(upper_touches) < 2 or len(lower_touches) < 2:
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "insufficient_edge_touches"})
            continue
        closes = [row["close"] for row in segment]
        close_drift = abs(closes[-1] - closes[0]) / width
        fitted_drift = _fitted_drift_to_width(closes, width)
        recent_closes = closes[-min(RECENT_BARS, size // 2):]
        recent_close_drift = abs(recent_closes[-1] - recent_closes[0]) / width
        recent_fitted_drift = _fitted_drift_to_width(recent_closes, width)
        if not all(math.isfinite(value) for value in (close_drift, fitted_drift,
                                                     recent_close_drift, recent_fitted_drift)):
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "nonfinite_drift"})
            continue
        if close_drift > MAX_CLOSE_DRIFT_TO_WIDTH or fitted_drift > MAX_FITTED_DRIFT_TO_WIDTH:
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "full_window_drift"})
            continue
        if (recent_close_drift > MAX_RECENT_DRIFT_TO_WIDTH
                or recent_fitted_drift > MAX_RECENT_DRIFT_TO_WIDTH):
            evaluated_windows.append({"window_bars": size, "accepted": False, "reason": "recent_directional_move"})
            continue
        evaluated_windows.append({"window_bars": size, "accepted": True, "reason": None})
        candidates.append({
            "start_time": segment[0]["time"], "end_time": segment[-1]["time"],
            "lower_price": lower, "upper_price": upper, "bar_count": size,
            "upper_source_time": segment[high_index]["time"],
            "lower_source_time": segment[low_index]["time"],
            "width_fraction_of_median_close": width_fraction,
            "upper_touch_count": len(upper_touches), "lower_touch_count": len(lower_touches),
            "upper_touch_times": [segment[index]["time"] for index in upper_touches],
            "lower_touch_times": [segment[index]["time"] for index in lower_touches],
            "close_drift_to_width": close_drift, "fitted_close_drift_to_width": fitted_drift,
            "recent_close_drift_to_width": recent_close_drift,
            "recent_fitted_close_drift_to_width": recent_fitted_drift,
            "boundary_rule": "full_window_max_high_min_low",
            "status": "geometry_candidate_requires_review",
        })
    # Prefer more repeated boundary contact, flatter closes, then longer spans.
    candidates.sort(key=lambda item: (-(item["upper_touch_count"] + item["lower_touch_count"]),
                                      item["fitted_close_drift_to_width"], -item["bar_count"]))
    # Overlapping windows often describe the exact same price box. Present one
    # representative instead of spending the result limit on duplicate geometry.
    unique_candidates = []
    seen_boundaries = set()
    for candidate in candidates:
        boundaries = (candidate["lower_price"], candidate["upper_price"], candidate["end_time"])
        if boundaries in seen_boundaries:
            continue
        seen_boundaries.add(boundaries)
        unique_candidates.append(candidate)
    return {
        "rule_version": RULE_VERSION,
        "window_sizes": list(windows),
        "end_policy": "latest_loaded_bar_only",
        "candidate_count": len(unique_candidates), "returned": min(limit, len(unique_candidates)),
        "truncated": len(unique_candidates) > limit,
        "duplicates_suppressed": len(candidates) - len(unique_candidates),
        "no_candidate_reason": "no_window_passed_rules" if not unique_candidates else None,
        "evaluated_windows": evaluated_windows,
        "candidates": unique_candidates[:limit],
        "thresholds": {
            "width_fraction_of_median_close": [MIN_WIDTH_FRACTION, MAX_WIDTH_FRACTION],
            "touch_distance_to_width": TOUCH_DISTANCE_TO_WIDTH,
            "minimum_separated_touches_per_edge": 2,
            "minimum_touch_separation_bars": MIN_TOUCH_SEPARATION_BARS,
            "maximum_close_drift_to_width": MAX_CLOSE_DRIFT_TO_WIDTH,
            "maximum_fitted_close_drift_to_width": MAX_FITTED_DRIFT_TO_WIDTH,
            "recent_bars": RECENT_BARS,
            "maximum_recent_drift_to_width": MAX_RECENT_DRIFT_TO_WIDTH,
        },
        "limitations": ["current_window_only", "geometry_only_requires_human_review",
                        "no_breakout_signal", "no_drawing_created"],
        "drawing_created": False,
    }
