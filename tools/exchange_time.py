"""Presentation dates and date-only anchors share one exchange-local clock."""
from datetime import datetime
from zoneinfo import ZoneInfo


def exchange_clock(symbol):
    from tools.closed_daily import market_for_symbol, MARKETS
    normalized = str(symbol or "").strip().upper()
    market = market_for_symbol(normalized)
    if normalized.endswith((".NASDAQ", ".NYSE")) or normalized in {"100.NDX", "100.SPX", "100.DJIA"}:
        market = "US"
    elif normalized.endswith(".HKG") or normalized.startswith("100.HSI"):
        market = "HK"
    return (MARKETS[market][0], "exchange_local") if market else (ZoneInfo("Asia/Shanghai"), "legacy_timezone_fallback")


def time_label(value, zone):
    if value is None:
        return None
    try:
        instant = datetime.fromtimestamp(value, zone)
        return {"time": value, "date": instant.date().isoformat(), "iso": instant.isoformat(timespec="seconds")}
    except (TypeError, ValueError, OverflowError, OSError):
        return {"time": value, "date": None, "iso": None}


def time_display(symbol, rows, drawings, *, sample=None, visible=None):
    zone, basis = exchange_clock(symbol)
    label = lambda value: time_label(value, zone)
    result = {"timezone": zone.key, "basis": basis,
              "loaded_start": label(rows[0]["time"] if rows else None),
              "loaded_end": label(rows[-1]["time"] if rows else None),
              "visible_start": label(visible[0]["time"] if visible else None),
              "visible_end": label(visible[-1]["time"] if visible else None),
              "sample_labels": [label(row["time"]) for row in (sample or [])], "drawing_anchors": []}
    for drawing in drawings:
        points = drawing.get("points") or ([{"time": drawing["time"]}] if drawing.get("time") else [])
        if not points:
            points = [{"label": name, "time": drawing[key]} for name, key in (("start", "start_time"), ("end", "end_time")) if drawing.get(key)]
        result["drawing_anchors"].append({"id": drawing["id"], "points": [
            {**label(point["time"]), **({"label": point["label"]} if "label" in point else {})} for point in points]})
    return result
