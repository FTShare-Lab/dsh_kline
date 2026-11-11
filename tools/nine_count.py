"""Transparent close-vs-four-back nine count; no retrospective erasure."""
from __future__ import annotations

from tools.closed_daily import closed_daily
from tools.lines import LineError

RULE_VERSION = "nine_count_v1"


def nine_count(rows, *, symbol: str, interval: str = "day", source_interval: str | None = "day",
               interval_value: int | None = 1, provider: str | None = None,
               display_bars: int = 120, known_gap_indexes: tuple[int, ...] = (), now=None):
    if type(display_bars) is not int or not 30 <= display_bars <= 240:
        raise LineError("invalid_nine_count_range", "九转展示范围必须为30至240根日线。")
    candles, metadata = closed_daily(rows, symbol=symbol, interval=interval,
                                     source_interval=source_interval, interval_value=interval_value,
                                     provider=provider, now=now)
    candles = candles[-4000:]
    gap_indexes = set(known_gap_indexes)
    if any(type(i) is not int or i <= 0 or i >= len(candles) for i in gap_indexes):
        raise LineError("invalid_known_gap", "已知缺失区间索引超出已加载日线范围。")
    marks = []
    events = []
    direction = None
    count = 0
    completed = False
    # The first observed run can predate the loaded prefix. Do not guess its count.
    censored = True
    encountered_censored_prefix = False
    segment_start = 0
    for i, bar in enumerate(candles):
        if i in gap_indexes:
            segment_start = i
            direction, count, completed, censored = None, 0, False, True
        if i - segment_start < 4:
            continue
        compare = bar["close"] - candles[i - 4]["close"]
        side = "up" if compare > 0 else "down" if compare < 0 else None
        if side is None:
            direction, count, completed, censored = None, 0, False, False
            continue
        if side != direction:
            direction, count, completed = side, 0, False
            # A reversal gives a known restart point, even at the loaded edge.
            if direction is not None and i > segment_start + 4:
                censored = False
        if censored or completed:
            if censored:
                encountered_censored_prefix = True
            continue
        count += 1
        mark = {"time": bar["time"], "index": i, "direction": side, "count": count,
                "label": str(count), "price": bar["high"] if side == "up" else bar["low"]}
        marks.append(mark)
        if count == 9:
            completed = True
            events.append({"time": bar["time"], "direction": side,
                           "label": "上涨九转计数完成" if side == "up" else "下跌九转计数完成"})
    first = max(0, len(candles) - display_bars)
    visible = [m for m in marks if m["index"] >= first]
    return {"rule_version": RULE_VERSION, "as_of": metadata["as_of"], "data_quality": metadata,
            "display_bars": display_bars, "loaded_bars": len(candles), "marks": visible,
            "events": [e for e in events if e["time"] >= (candles[first]["time"] if candles else 0)],
            "total_marks": len(marks), "truncated": len(visible) < len(marks),
            "limitations": (["left_boundary_run_censored_until_interruption"] if encountered_censored_prefix else [])
                           + (["known_gaps_segmented"] if gap_indexes else [])}
