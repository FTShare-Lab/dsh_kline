"""Read-only arithmetic for a host-chosen channel, not fitting or recognition."""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from tools.channels import channel_geometry
from tools.lines import LineError, validate_line_fields
from tools.trend_lines import CN_TZ, resolve_anchor_time


def preview_channel(rows: list[dict], interval: str, *, start_time: str, start_price: float,
                    end_time: str, end_price: float, parallel_time: str, parallel_price: float,
                    bar_limit: int = 200) -> dict[str, Any]:
    """Rows have already passed live-observation validation; never fetch or publish."""
    if isinstance(bar_limit, bool) or not isinstance(bar_limit, int) or not 1 <= bar_limit <= 4000:
        raise LineError("invalid_preview_limit", "bar_limit 为1至4000整数；汇总始终核对完整起止区间。")
    source = {"interval": interval, "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
    anchors = []
    for timestamp, price in ((start_time, start_price), (end_time, end_price), (parallel_time, parallel_price)):
        price, _, _ = validate_line_fields(price=price)
        if price is None:
            raise LineError("invalid_price", "三个锚点都需要明确的有限正价格。")
        anchors.append({"time": resolve_anchor_time(source, timestamp), "price": price})
    start, end, parallel = anchors
    geometry = channel_geometry(source, start, end, parallel)
    region = [row for row in rows if start["time"] <= row["time"] <= end["time"]]
    if len(region) > 4000:
        raise LineError("measurement_capacity", "通道核对区间超过4000根；未使用截断样本代替全区间。")
    # Only numerical roundoff, not a subjective touch/fitting tolerance. Keep
    # signed raw distances unrounded and expose the allowance used by counts.
    scale = max(*(a["price"] for edge in ("upper", "lower") for a in geometry[edge].values()),
                *(row[field] for row in region for field in ("low", "high")))
    epsilon = scale * 1e-12
    measured = []
    for index, row in enumerate(region):
        upper = geometry["upper"]["from"]["price"] + geometry["slope_per_bar"] * index
        lower = geometry["lower"]["from"]["price"] + geometry["slope_per_bar"] * index
        values = {"high_minus_upper": row["high"] - upper, "low_minus_lower": row["low"] - lower,
                  "body_high_minus_upper": max(row["open"], row["close"]) - upper,
                  "body_low_minus_lower": min(row["open"], row["close"]) - lower}
        if not all(math.isfinite(v) for v in (upper, lower, *values.values())):
            raise LineError("nonfinite_channel_measurement", "通道偏差计算超出有限数值范围，未输出部分核对结果。")
        try:
            instant = datetime.fromtimestamp(row["time"], CN_TZ)
            date, iso = instant.date().isoformat(), instant.isoformat(timespec="seconds")
        except (ValueError, OverflowError, OSError):
            date, iso = None, None
        measured.append({"time": row["time"], "date": date, "iso": iso,
                         "bar_offset": index, "upper_price": upper, "lower_price": lower,
                         "ohlc": {k: row[k] for k in ("open", "high", "low", "close")}, **values})
    summary = {}
    for key, field, sign in (("wick_above", "high_minus_upper", 1), ("wick_below", "low_minus_lower", -1),
                             ("body_above", "body_high_minus_upper", 1), ("body_below", "body_low_minus_lower", -1)):
        distances = [bar[field] * sign for bar in measured]
        maximum = max(distances)
        witness = measured[distances.index(maximum)]
        summary[key] = {"bar_count": sum(d > epsilon for d in distances),
                        "max_price_excess": max(0, maximum),
                        "max_excess_witness": {k: witness[k] for k in ("time", "date", "iso", "bar_offset")}
                        if maximum > epsilon else None}
    provenance = []
    by_time = {r["time"]: r for r in region}
    for anchor in anchors:
        row = by_time[anchor["time"]]
        provenance.append({**anchor, "exact_matching_ohlc_fields": [k for k in ("open", "high", "low", "close")
                                                                     if row[k] == anchor["price"]],
                           "price_origin": "caller_supplied_not_selected_by_plugin"})
    return {"schema_version": 1, "evidence_scope": "loaded_browser_candles",
            "range_policy": "inclusive_start_end_only_no_extension", "bar_count": len(region),
            "anchors": dict(zip(("from", "to", "parallel"), provenance)), "geometry": geometry,
            "numeric_policy": {"arithmetic": "float64_unrounded_signed_distances",
                               "count_roundoff_allowance": epsilon, "allowance_basis": "max_boundary_and_region_wick_price_times_1e-12",
                               "meaning": "numerical_roundoff_only_not_market_touch_tolerance"},
            "distance_convention": "positive high_minus_upper is above; negative low_minus_lower is below; body fields use open/close extrema",
            "summary": summary, "bars": measured[:bar_limit],
            "bar_selection": {"total": len(measured), "returned": min(bar_limit, len(measured)),
                              "truncated": len(measured) > bar_limit, "order": "ascending", "sample": "first_limit",
                              "summary_scope": "full_inclusive_region"},
            "pattern_classification": "not_provided", "touch_count": "not_provided",
            "quality_score": "not_provided", "drawing_created": False, "render_verified": False}
