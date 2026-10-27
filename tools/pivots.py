"""Deterministic, confirmed local-extremum candidates on loaded candles."""
from __future__ import annotations

import math

from core.rows import RowsValidationError, validate_rows
from tools.lines import LineError


def confirmed_pivots(rows, *, left_bars=2, right_bars=2, mode="both", limit=20):
    """Return strict local highs/lows with complete left and right windows.

    Equal highs/lows are deliberately not pivots. Only bars with all right-side
    confirmation bars present are considered. Results are chronological, limited
    to the newest ``limit`` candidates, with no alternation or trend inference.
    """
    if type(left_bars) is not int or not 1 <= left_bars <= 20:
        raise LineError("invalid_pivot_window", "left_bars 必须是1至20的整数。")
    if type(right_bars) is not int or not 1 <= right_bars <= 20:
        raise LineError("invalid_pivot_window", "right_bars 必须是1至20的整数。")
    if mode not in {"high", "low", "both"}:
        raise LineError("invalid_pivot_mode", "mode 只能是 high、low 或 both。")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise LineError("invalid_pivot_limit", "limit 必须是1至50的整数。")
    try:
        candles = validate_rows(rows, min_len=left_bars + right_bars + 1)
    except RowsValidationError:
        raise LineError("insufficient_pivot_history", "已加载K线不足以提供完整左右确认窗口；未补取行情。") from None

    candidates = []
    for index in range(left_bars, len(candles) - right_bars):
        row = candles[index]
        left = candles[index - left_bars:index]
        right = candles[index + 1:index + right_bars + 1]
        high = float(row["high"])
        low = float(row["low"])
        if not math.isfinite(high) or not math.isfinite(low):
            raise LineError("invalid_pivot_data", "K线高低价必须是有限数值。")
        neighbors = left + right
        if mode in {"high", "both"} and all(high > float(item["high"]) for item in neighbors):
            candidates.append({"side": "high", "time": str(row["time"]), "price": high,
                               "bars_ago": len(candles) - 1 - index})
        if mode in {"low", "both"} and all(low < float(item["low"]) for item in neighbors):
            candidates.append({"side": "low", "time": str(row["time"]), "price": low,
                               "bars_ago": len(candles) - 1 - index})

    selected = candidates[-limit:]
    return {
        "left_bars": left_bars,
        "right_bars": right_bars,
        "mode": mode,
        "limit": limit,
        "candidates": selected,
        "candidate_count": len(selected),
        "total_candidates": len(candidates),
        "truncated": len(selected) < len(candidates),
        "rule": "strict_local_extremum",
        "tie_policy": "equal_neighbor_is_not_a_pivot",
        "confirmation": "complete_right_window_only",
    }
