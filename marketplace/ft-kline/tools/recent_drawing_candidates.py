"""Recent, confirmed daily anchors for ordinary drawing tools.

These are geometric suggestions, not wave labels or trading signals. A direct
drawing request permits the host to choose the newest suitable result and
continue through the guarded chart edit; analysis-only requests do not.
"""
from __future__ import annotations

import math

import numpy as np
import talib

from tools.closed_daily import closed_daily
from tools.lines import LineError
from tools.pivots import confirmed_pivots

RULE_VERSION = "recent_drawing_v2"
TYPES = {"horizontal", "trend", "fibonacci", "abc"}


def recent_drawing_candidates(rows, *, symbol: str, provider: str | None,
                              interval: str = "day", source_interval: str | None = "day",
                              interval_value: int | None = 1, drawing_type: str,
                              lookback_bars: int = 120, max_candidates: int = 5, now=None):
    if drawing_type not in TYPES:
        raise LineError("unsupported_auto_drawing", "该绘图类型没有自动选点规则。")
    if type(lookback_bars) is not int or not 30 <= lookback_bars <= 300:
        raise LineError("invalid_auto_drawing_range", "自动选点观察范围须为30至300根日线。")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 5:
        raise LineError("invalid_auto_drawing_limit", "自动选点最多返回1至5个候选。")
    closed, quality = closed_daily(rows, symbol=symbol, provider=provider, interval=interval,
                                   source_interval=source_interval, interval_value=interval_value, now=now)
    if quality["market"] is None:
        raise LineError("unsupported_auto_drawing_market", "自动选点仅支持 A／港／美股日线；仍可手动绘图。")
    window = closed[-min(4000, lookback_bars):]
    if len(window) < 35:
        raise LineError("insufficient_auto_drawing_history", "自动选点需要至少35根已收盘日线；仍可手动绘图。")
    pivots = confirmed_pivots(window, left_bars=2, right_bars=2, mode="both", limit=50)["candidates"]
    # A wide bar can be both a high and a low pivot. Its ordering is unknown.
    ambiguous = {p["time"] for p in pivots if sum(q["time"] == p["time"] for q in pivots) > 1}
    pivots = [p for p in pivots if p["time"] not in ambiguous]
    index_by_time = {str(row["time"]): index for index, row in enumerate(window)}
    atr_values = talib.ATR(np.array([float(r["high"]) for r in window]),
                           np.array([float(r["low"]) for r in window]),
                           np.array([float(r["close"]) for r in window]), timeperiod=14)
    atr = float(atr_values[-1])
    if not math.isfinite(atr) or atr <= 0:
        raise LineError("auto_drawing_atr_unavailable", "近期波动数据不足，无法可靠自动选点；仍可手动绘图。")
    candidates = []
    def add(points, side):
        if any(index_by_time.get(p["time"]) is None for p in points):
            return
        indexes = [index_by_time[p["time"]] for p in points]
        if len(window) - 1 - indexes[-1] > 30:
            return
        if any(b - a < 3 for a, b in zip(indexes, indexes[1:])):
            return
        candidates.append({"side": side, "anchors": [{"time": int(p["time"]), "price": p["price"]} for p in points],
                           "latest_anchor_time": int(points[-1]["time"]),
                           "latest_anchor_bars_ago": len(window) - 1 - indexes[-1]})
    if drawing_type == "horizontal":
        for pivot in pivots:
            add([pivot], pivot["side"])
    elif drawing_type == "trend":
        for side in ("high", "low"):
            same = [p for p in pivots if p["side"] == side]
            for first, second in zip(same, same[1:]):
                add([first, second], side)
    elif drawing_type == "abc":
        # Three labelled endpoints only describe two legs. Require the prior
        # origin as well so A, B and C end three completed, alternating legs.
        for start in range(len(pivots) - 3):
            origin, a, b, c = pivots[start:start + 4]
            points = (origin, a, b, c)
            if any(left["side"] == right["side"] for left, right in zip(points, points[1:])):
                continue
            indexes = [index_by_time.get(p["time"]) for p in points]
            if any(index is None for index in indexes) or any(y - x < 3 for x, y in zip(indexes, indexes[1:])):
                continue
            if indexes[-1] - indexes[0] > 120:
                continue
            known_at = indexes[-1] + 2
            if known_at >= len(atr_values):
                continue
            reference_atr = float(atr_values[known_at])
            if not math.isfinite(reference_atr) or reference_atr <= 0:
                continue
            first_leg = abs(a["price"] - origin["price"])
            retrace = abs(b["price"] - a["price"])
            final_leg = abs(c["price"] - b["price"])
            if first_leg < 2 * reference_atr or not .3 <= retrace / first_leg <= .8:
                continue
            if not .8 <= final_leg / first_leg <= 2.5:
                continue
            if origin["side"] == "high":
                if b["price"] >= origin["price"] or c["price"] >= a["price"] - .25 * reference_atr:
                    continue
                side = "abc_down"
            else:
                if b["price"] <= origin["price"] or c["price"] <= a["price"] + .25 * reference_atr:
                    continue
                side = "abc_up"
            before = len(candidates)
            add((a, b, c), side)
            if len(candidates) > before:
                candidates[-1]["origin"] = {"time": int(origin["time"]), "price": origin["price"]}
    else:
        width = 2
        for start in range(len(pivots) - width + 1):
            points = pivots[start:start + width]
            if any(a["side"] == b["side"] for a, b in zip(points, points[1:])):
                continue
            if any(abs(a["price"] - b["price"]) < atr for a, b in zip(points, points[1:])):
                continue
            add(points, "swing")
    candidates.sort(key=lambda item: (item["latest_anchor_time"],
                                      abs(item["anchors"][-1]["price"] - item["anchors"][0]["price"])), reverse=True)
    candidates = candidates[:max_candidates]
    return {"rule_version": RULE_VERSION, "drawing_type": drawing_type, "as_of": quality["as_of"],
            "data_quality": quality, "lookback_bars": lookback_bars, "candidate_count": len(candidates),
            "candidates": candidates, "limitations": ["confirmed_pivots_only", "abc_price_geometry_not_elliott_validation"]
            if drawing_type == "abc" else ["confirmed_pivots_only"]}
