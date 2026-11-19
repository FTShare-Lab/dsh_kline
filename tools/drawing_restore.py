"""Pure drawing-only restore shared by DSH and Codex; callers verify authority."""
from copy import deepcopy
from tools.lines import LineError

DRAWING_COMMANDS = {"DRAW_HORIZONTAL_LINE", "DRAW_AGENT_TREND_LINE", "DRAW_AGENT_CHANNEL", "DRAW_AGENT_RECTANGLE",
    "DRAW_AGENT_FIBONACCI", "DRAW_AGENT_POLYLINE", "DRAW_AGENT_ANNOTATION", "DRAW_AGENT_SERIES_LINE",
    "DRAW_AGENT_PRICE_BAND", "DRAW_AGENT_PRICE_STICKS", "DRAW_AGENT_PRICE_PATTERN", "DRAW_AGENT_NINE_COUNT"}

def restore_drawing_commands(payload, before, after, interval, direction):
    def rows(value):
        return next((c.get("rows") for c in value.get("chartCommands", []) if c.get("type") == "SET_CANDLES"), None)

    # An operation from an older data/source binding must never be replayed onto
    # new candles, another instrument, adjustment or minute-bar interval.
    keys = ("symbol", "interval", "interval_value", "adjust", "provider", "volume_unit")
    def provenance(value):
        meta = value.get("data_meta") or value.get("dataMeta") or {}
        return {k: meta.get(k) for k in ("source", "provider", "volume_unit", "volume_adjustment", "price_adjustment", "timestamp_convention")}
    if (any(payload.get(k) != after.get(k) for k in keys) or rows(payload) != rows(after)
            or provenance(payload) != provenance(after)):
        raise LineError("drawing_history_binding_changed", "行情或来源已变化，不能恢复该次绘图；当前图未修改。")

    def drawings(value):
        return [c for c in value.get("chartCommands", [])
                if c.get("type") in DRAWING_COMMANDS and c.get("interval", value.get("interval")) == interval]

    expected, target = (after, before) if direction == "undo" else (before, after)
    if sorted(drawings(payload), key=lambda c: c["id"]) != sorted(drawings(expected), key=lambda c: c["id"]):
        raise LineError("drawing_history_conflict", "图形已被其他操作修改，未用历史记录覆盖当前图形。")
    restored = deepcopy(payload)
    restored["chartCommands"] = [c for c in restored["chartCommands"]
                                 if not (c.get("type") in DRAWING_COMMANDS and c.get("interval", payload.get("interval")) == interval)]
    restored["chartCommands"].extend(deepcopy(drawings(target)))
    return restored, {"kind": "drawing_history", "direction": direction, "count": len(drawings(target))}
