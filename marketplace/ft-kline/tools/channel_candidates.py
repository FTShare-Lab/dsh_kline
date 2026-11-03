"""Read-only, rule-based three-anchor channel candidates on loaded candles.

This module proposes geometry for human review. It neither publishes drawings
nor claims that a candidate is the uniquely correct technical-analysis channel.
"""
from __future__ import annotations

from collections import Counter
import math
from statistics import median

from core.rows import RowsValidationError, validate_rows
from tools.lines import LineError
from tools.pivots import confirmed_pivots

RULE_VERSION = "confirmed_pivots_v3"
MIN_TOTAL_MOVE_FRACTION = 0.03
MAX_EXCESS_TO_WIDTH = 0.25
MAX_OUTSIDE_BAR_FRACTION = 0.20
MAX_WIDTH_FRACTION = 0.12
MAX_WIDTH_TO_BASE_MOVE = 2.0
MAX_CURRENT_END_AGE_BARS = 8
SAME_FAMILY_SLOPE_TOLERANCE = 0.10
SAME_FAMILY_WIDTH_TOLERANCE = 0.10


def _measure_region(rows, *, first, start_price, slope, width, direction, start, stop):
    """Measure actual wicks against index-based edges, including any extension."""
    maximum = 0.0
    outside_count = 0
    latest_close_position = None
    for index in range(start, stop):
        base = start_price + slope * (index - first)
        upper, lower = (base + width, base) if direction == "ascending" else (base, base - width)
        row = rows[index]
        excess = max(0.0, row["high"] - upper, lower - row["low"])
        if not all(math.isfinite(value) for value in (base, upper, lower, excess)) or lower <= 0:
            return None
        maximum = max(maximum, excess)
        outside_count += excess > max(upper, lower) * 1e-12
        tolerance = max(upper, lower) * 1e-12
        latest_close_position = ("above_projected_upper" if row["close"] > upper + tolerance else
                                 "below_projected_lower" if row["close"] < lower - tolerance else "inside")
    return {"bar_count": stop - start, "outside_bar_count": outside_count,
            "outside_bar_fraction": outside_count / (stop - start) if stop > start else 0.0,
            "max_wick_excess_price": maximum, "max_wick_excess_to_width": maximum / width,
            "latest_close_position": latest_close_position}


def _same_geometric_family(candidate, representative):
    """Collapse near-identical alternatives built around the same parallel pivot."""
    anchors, other = candidate["anchors"], representative["anchors"]
    if (candidate["direction"] != representative["direction"]
            or anchors["parallel"]["time"] != other["parallel"]["time"]):
        return False
    slope_scale = max(abs(candidate["slope_per_bar"]), abs(representative["slope_per_bar"]))
    width_scale = max(candidate["width"], representative["width"])
    return (abs(candidate["slope_per_bar"] - representative["slope_per_bar"])
            <= SAME_FAMILY_SLOPE_TOLERANCE * slope_scale
            and abs(candidate["width"] - representative["width"])
            <= SAME_FAMILY_WIDTH_TOLERANCE * width_scale)


def channel_candidates(
    rows,
    *,
    direction="both",
    lookback_bars=120,
    left_bars=2,
    right_bars=2,
    min_span_bars=12,
    limit=3,
    scope="current",
):
    """Propose channels from two confirmed same-side pivots and one opposite pivot.

    Ascending channels use two rising pivot lows as the base and a pivot high
    between them as the parallel anchor; descending channels are symmetric.
    All coordinates are candle-index based, never elapsed-time or screen pixels.
    The anchor interval is measured in full. Current proposals must have a
    recent confirmed end pivot and pass an explicit arithmetic extension check
    through the latest loaded bar. Historical proposals never infer a current
    breakout. Neither scope confirms professional pattern quality.
    """
    if not isinstance(direction, str) or direction not in {"ascending", "descending", "both"}:
        raise LineError("invalid_channel_candidate_direction", "direction 只能是 ascending、descending 或 both。")
    if not isinstance(scope, str) or scope not in {"current", "historical"}:
        raise LineError("invalid_channel_candidate_scope", "scope 只能是 current 或 historical。")
    if type(lookback_bars) is not int or not 30 <= lookback_bars <= 300:
        raise LineError("invalid_channel_candidate_lookback", "lookback_bars 必须是30至300的整数。")
    if type(min_span_bars) is not int or not 10 <= min_span_bars <= 100 or min_span_bars >= lookback_bars:
        raise LineError("invalid_channel_candidate_span", "min_span_bars 必须是10至100且小于 lookback_bars。")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise LineError("invalid_channel_candidate_limit", "limit 必须是1至5的整数。")
    if type(left_bars) is not int or not 1 <= left_bars <= 20 or type(right_bars) is not int or not 1 <= right_bars <= 20:
        raise LineError("invalid_pivot_window", "left_bars 和 right_bars 必须是1至20的整数。")
    # The pivot helper validates window parameters and does not use incomplete
    # right-hand windows. Its 50-candidate cap bounds pair enumeration.
    try:
        candles = validate_rows(rows, min_len=max(min_span_bars + 1, left_bars + right_bars + 1))
    except RowsValidationError:
        raise LineError("insufficient_channel_candidate_history", "当前已加载K线不足以计算通道候选；未补取行情。") from None
    selected = candles[-lookback_bars:]
    if any(row["low"] <= 0 or row["high"] < max(row["open"], row["close"], row["low"])
           or row["low"] > min(row["open"], row["close"]) for row in selected):
        raise LineError("invalid_channel_candidate_data", "通道候选需要高低价为正且 OHLC 一致的K线；未忽略异常柱。")
    pivot_result = confirmed_pivots(selected, left_bars=left_bars, right_bars=right_bars, limit=50)
    index_by_time = {row["time"]: index for index, row in enumerate(selected)}
    pivots = {side: [] for side in ("high", "low")}
    for pivot in pivot_result["candidates"]:
        pivots[pivot["side"]].append((index_by_time[int(pivot["time"])], pivot["price"]))

    candidates = []
    rejection_counts = Counter()
    considered_anchor_pairs = 0
    for trend in (("ascending", "low", "high"), ("descending", "high", "low")):
        name, base_side, opposite_side = trend
        if direction not in {"both", name}:
            continue
        base_pivots = pivots[base_side]
        for first_pos, (first, start_price) in enumerate(base_pivots):
            for last, end_price in base_pivots[first_pos + 1:]:
                span = last - first
                if span < min_span_bars:
                    continue
                considered_anchor_pairs += 1
                slope = (end_price - start_price) / span
                move_fraction = abs(end_price - start_price) / start_price
                if (name == "ascending" and slope <= 0) or (name == "descending" and slope >= 0):
                    rejection_counts["wrong_direction"] += 1
                    continue
                if move_fraction < MIN_TOTAL_MOVE_FRACTION:
                    rejection_counts["weak_base_move"] += 1
                    continue
                opposite = []
                for index, price in pivots[opposite_side]:
                    if first < index < last:
                        base_at_pivot = start_price + slope * (index - first)
                        width = (price - base_at_pivot) * (1 if name == "ascending" else -1)
                        if math.isfinite(width) and width > 0:
                            opposite.append((width, index, price))
                if not opposite:
                    rejection_counts["no_interior_opposite_pivot"] += 1
                    continue
                # The widest confirmed opposite pivot makes the parallel edge;
                # stable tie-breaking favors the earlier pivot.
                width, parallel_index, parallel_price = max(opposite, key=lambda value: (value[0], -value[1]))
                median_close = median(row["close"] for row in selected[first:last + 1])
                width_fraction = width / median_close
                width_to_base_move = width / abs(end_price - start_price)
                if not math.isfinite(width_fraction) or width_fraction > MAX_WIDTH_FRACTION:
                    rejection_counts["too_wide_vs_price"] += 1
                    continue
                if not math.isfinite(width_to_base_move) or width_to_base_move > MAX_WIDTH_TO_BASE_MOVE:
                    rejection_counts["too_wide_vs_base_move"] += 1
                    continue
                anchor_measurement = _measure_region(selected, first=first, start_price=start_price,
                    slope=slope, width=width, direction=name, start=first, stop=last + 1)
                if (anchor_measurement is None or
                        anchor_measurement["max_wick_excess_to_width"] > MAX_EXCESS_TO_WIDTH):
                    rejection_counts["anchor_interval_boundary_breach"] += 1
                    continue
                if anchor_measurement["outside_bar_fraction"] > MAX_OUTSIDE_BAR_FRACTION:
                    rejection_counts["too_many_anchor_interval_breaches"] += 1
                    continue
                age = len(selected) - 1 - last
                if scope == "current" and age > MAX_CURRENT_END_AGE_BARS:
                    rejection_counts["end_anchor_too_old"] += 1
                    continue
                post_end = {"evaluated": False, "reason": "historical_scope_no_current_inference"}
                if scope == "current":
                    measured = _measure_region(selected, first=first, start_price=start_price,
                        slope=slope, width=width, direction=name, start=last + 1, stop=len(selected))
                    if measured is None:
                        rejection_counts["invalid_post_end_projection"] += 1
                        continue
                    if (measured["max_wick_excess_to_width"] > MAX_EXCESS_TO_WIDTH
                            or measured["latest_close_position"] != "inside"):
                        rejection_counts["post_end_boundary_breach"] += 1
                        continue
                    post_end = {"evaluated": True, "basis": "arithmetic_extension_not_pattern_confirmation",
                                **measured}
                anchors = {
                    "from": {"time": selected[first]["time"], "price": start_price, "ohlc_field": base_side},
                    "to": {"time": selected[last]["time"], "price": end_price, "ohlc_field": base_side},
                    "parallel": {"time": selected[parallel_index]["time"], "price": parallel_price,
                                 "ohlc_field": opposite_side},
                }
                candidates.append({
                    "direction": name,
                    "anchors": anchors,
                    "span_bars": span + 1,
                    "bars_since_end": age,
                    "slope_per_bar": slope,
                    "width": width,
                    "width_fraction_of_median_close": width_fraction,
                    "width_to_base_move": width_to_base_move,
                    "base_move_fraction": move_fraction,
                    "max_wick_excess_price": anchor_measurement["max_wick_excess_price"],
                    "max_wick_excess_to_width": anchor_measurement["max_wick_excess_to_width"],
                    "outside_bar_count": anchor_measurement["outside_bar_count"],
                    "outside_bar_fraction": anchor_measurement["outside_bar_fraction"],
                    "post_end": post_end,
                    "scope": scope,
                    "anchor_rule": "two_confirmed_same_side_pivots_plus_widest_interior_opposite_pivot",
                    "measurement_range": "anchor_interval_inclusive_post_end_separate",
                    "_end_index": last,
                })
    # Newer, more compact, less-violated candidates first. No opaque score.
    candidates.sort(key=lambda item: (-item["_end_index"], item["max_wick_excess_to_width"],
                                      item["width_to_base_move"], -item["span_bars"],
                                      item["direction"], item["anchors"]["from"]["time"]))
    qualified_before_dedup = len(candidates)
    distinct = []
    seen_families = set()
    for candidate in candidates:
        del candidate["_end_index"]
        family = (candidate["direction"], candidate["anchors"]["to"]["time"],
                  candidate["anchors"]["parallel"]["time"])
        if family in seen_families or any(_same_geometric_family(candidate, kept) for kept in distinct):
            continue
        seen_families.add(family)
        distinct.append(candidate)
    return {
        "rule_version": RULE_VERSION,
        "direction": direction,
        "scope": scope,
        "lookback_bars": lookback_bars,
        "left_bars": left_bars,
        "right_bars": right_bars,
        "min_span_bars": min_span_bars,
        "considered_anchor_pairs": considered_anchor_pairs,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "qualified_before_dedup": qualified_before_dedup,
        "deduplicated_count": qualified_before_dedup - len(distinct),
        "candidate_count": len(distinct),
        "returned": min(limit, len(distinct)),
        "truncated": len(distinct) > limit,
        "no_candidate_reason": "no_anchor_triple_passed_rules" if not distinct else None,
        "no_candidate_explanation": ("没有三锚点组合同时满足全部筛选规则；不能据此推断近期没有已确认拐点，或真实走势不存在通道。"
                                     if not distinct else None),
        "pivot_scan": {"considered": pivot_result["candidate_count"],
                       "total": pivot_result["total_candidates"], "truncated": pivot_result["truncated"],
                       "recent_confirmed_high_count": sum(len(selected) - 1 - index <= MAX_CURRENT_END_AGE_BARS
                           for index, _ in pivots["high"]),
                       "recent_confirmed_low_count": sum(len(selected) - 1 - index <= MAX_CURRENT_END_AGE_BARS
                           for index, _ in pivots["low"])},
        "candidates": distinct[:limit],
        "thresholds": {"min_total_move_fraction": MIN_TOTAL_MOVE_FRACTION,
                       "max_wick_excess_to_width": MAX_EXCESS_TO_WIDTH,
                       "max_outside_bar_fraction": MAX_OUTSIDE_BAR_FRACTION,
                       "max_width_fraction_of_median_close": MAX_WIDTH_FRACTION,
                       "max_width_to_base_move": MAX_WIDTH_TO_BASE_MOVE,
                       "max_current_end_age_bars": MAX_CURRENT_END_AGE_BARS,
                       "same_family_slope_tolerance": SAME_FAMILY_SLOPE_TOLERANCE,
                       "same_family_width_tolerance": SAME_FAMILY_WIDTH_TOLERANCE},
        "limitations": ["geometry_only_requires_human_review", "confirmed_pivots_lag_right_bars",
                        "arithmetic_extension_not_breakout_confirmation", "no_drawing_created"],
        "drawing_created": False,
    }
