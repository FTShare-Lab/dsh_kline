"""Exact measurements of a host-selected loaded region; no pattern recognition."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from tools.lines import LineError
from tools.trend_lines import CN_TZ, resolve_anchor_time


def _boundary_witness(region: list[dict], values: list[float], price: float,
                      fields: tuple[str, ...]) -> dict[str, Any]:
    """One bounded arithmetic witness, not a selected drawing/pattern anchor.

    Validated rows are time-ordered. Report the first matching bar and count all
    matching bars, without implying a unique extremum or dumping thousands of ties.
    """
    index = next(i for i, value in enumerate(values) if value == price)
    row = region[index]
    try:
        instant = datetime.fromtimestamp(row["time"], CN_TZ)
        date, iso = instant.date().isoformat(), instant.isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        date, iso = None, None
    return {"price": price, "time": row["time"], "date": date, "iso": iso,
            "source_fields": [field for field in fields if row[field] == price],
            "matched_bar_count": sum(value == price for value in values)}


def measure_chart_region(rows: list[dict], interval: str, start_time: str, end_time: str) -> dict[str, Any]:
    source = {"interval": interval, "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
    start = resolve_anchor_time(source, start_time)
    end = resolve_anchor_time(source, end_time)
    if start > end:
        raise LineError("invalid_measurement_range", "测量起点必须不晚于终点；未交换日期或重新取数。")
    region = [row for row in rows if start <= row["time"] <= end]
    if len(region) > 4000:
        raise LineError("measurement_capacity", "测量区域超过4000根K线；未拿截断样本冒充完整区域。")
    body_low = [min(row["open"], row["close"]) for row in region]
    body_high = [max(row["open"], row["close"]) for row in region]
    envelope_low, envelope_high = min(body_low), max(body_high)
    overlap_low, overlap_high = max(body_low), min(body_high)
    wick_low = [row["low"] for row in region]
    wick_high = [row["high"] for row in region]
    relation = "empty" if overlap_low > overlap_high else "point" if overlap_low == overlap_high else "range"
    volumes = [row["volume"] for row in region]
    increasing = sum(right > left for left, right in zip(volumes, volumes[1:]))
    decreasing = sum(right < left for left, right in zip(volumes, volumes[1:]))
    change = (volumes[-1] / volumes[0] - 1) * 100 if volumes[0] > 0 else None
    if change is not None and not math.isfinite(change):
        change = None
    return {
        "evidence_scope": "loaded_browser_candles", "pattern_classification": "not_provided",
        "start_time": start, "end_time": end, "bar_count": len(region),
        "wick_envelope": {"lower_price": min(wick_low), "upper_price": max(wick_high)},
        "body_envelope": {"meaning": "contains_all_open_close_bodies",
                          "lower_price": envelope_low, "upper_price": envelope_high},
        "body_overlap": {"meaning": "intersection_shared_by_every_body",
                         "exists": overlap_low <= overlap_high, "has_positive_height": overlap_low < overlap_high,
                         "lower_price": overlap_low if overlap_low <= overlap_high else None,
                         "upper_price": overlap_high if overlap_low <= overlap_high else None},
        "boundary_evidence": {
            "schema_version": 1, "scope": "selected_region_only",
            "tie_policy": "first_matching_bar_with_total_count",
            "wick_envelope": {
                "lower": _boundary_witness(region, wick_low, min(wick_low), ("low",)),
                "upper": _boundary_witness(region, wick_high, max(wick_high), ("high",))},
            "body_envelope": {
                "lower": _boundary_witness(region, body_low, envelope_low, ("open", "close")),
                "upper": _boundary_witness(region, body_high, envelope_high, ("open", "close"))},
            "body_overlap": {
                "relation": relation,
                "comparison": "lower_greater_than_upper" if relation == "empty" else
                              "lower_equals_upper" if relation == "point" else "lower_less_than_upper",
                "lower_candidate": _boundary_witness(region, body_low, overlap_low, ("open", "close")),
                "upper_candidate": _boundary_witness(region, body_high, overlap_high, ("open", "close"))},
        },
        "volume_changes": {"first": volumes[0], "last": volumes[-1], "first_to_last_pct": change,
                           "increasing_steps": increasing, "decreasing_steps": decreasing,
                           "equal_steps": len(volumes) - 1 - increasing - decreasing,
                           "strictly_decreasing": decreasing == len(volumes) - 1 if len(volumes) > 1 else None,
                           "non_increasing": increasing == 0 if len(volumes) > 1 else None},
    }
