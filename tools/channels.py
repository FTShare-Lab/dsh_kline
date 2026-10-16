"""Three-anchor, finite parallel price channels on the chart's candle-index axis."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import secrets
from typing import Any

from tools.lines import LineError, validate_line_fields
from tools.trend_lines import resolve_anchor_time

CHANNEL_COMMAND = "DRAW_AGENT_CHANNEL"
MAX_CHANNELS = 30


def channels(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy([c for c in payload.get("chartCommands", []) if c.get("type") == CHANNEL_COMMAND])


def channel_geometry(payload: dict[str, Any], start: dict, end: dict, parallel: dict) -> dict[str, Any]:
    rows = next((c.get("rows", []) for c in payload.get("chartCommands", []) if c.get("type") == "SET_CANDLES"), [])
    times = [r["time"] for r in rows]
    if any(times.count(a["time"]) != 1 for a in (start, end, parallel)) or any(a >= b for a, b in zip(times, times[1:])):
        raise LineError("invalid_channel_rows", "通道需要唯一、按时间递增的 K 线锚点。")
    if start["time"] >= end["time"]:
        raise LineError("invalid_anchor_order", "通道起点必须早于终点，未自动交换锚点。")
    if not start["time"] <= parallel["time"] <= end["time"]:
        raise LineError("parallel_anchor_outside", "第三点必须位于起止时间范围内；请明确指定，不自动挪动。")
    i, j, k = (times.index(a["time"]) for a in (start, end, parallel))
    # Candles are equally spaced on screen, even across weekends/holidays.
    slope = (end["price"] - start["price"]) / (j - i)
    offset = parallel["price"] - (start["price"] + slope * (k - i))
    tolerance = max(start["price"], end["price"], parallel["price"]) * 1e-12
    if not math.isfinite(offset) or abs(offset) <= tolerance:
        raise LineError("zero_channel_width", "第三点落在基准线上，不能形成有宽度的通道。")
    other = {"from": {"time": start["time"], "price": start["price"] + offset},
             "to": {"time": end["time"], "price": end["price"] + offset}}
    if any(not math.isfinite(a["price"]) or a["price"] <= 0 for a in other.values()):
        raise LineError("invalid_channel_boundary", "推导后的平行边界价格必须大于零且有限，请调整第三点。")
    base = {"from": deepcopy(start), "to": deepcopy(end)}
    upper, lower = (other, base) if offset > 0 else (base, other)
    return {"upper": upper, "lower": lower, "width": abs(offset), "signed_offset": offset,
            "slope_per_bar": slope, "direction": "ascending" if slope > 0 else "descending" if slope < 0 else "horizontal",
            "geometry_basis": "candle_index_linear_price"}


def edit_channel(
    payload: dict[str, Any], action: str, *, channel_id: str | None = None,
    start_time: str | None = None, start_price: float | None = None,
    end_time: str | None = None, end_price: float | None = None,
    parallel_time: str | None = None, parallel_price: float | None = None,
    name: str | None = None, color: str | None = None,
    show_midline: bool | None = None, request_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    previous = next((c for c in commands if c.get("type") == CHANNEL_COMMAND and c.get("id") == channel_id), None)
    if action in {"update", "delete"} and previous is None:
        raise LineError("channel_not_found", "当前快照不存在该 AI 通道，请先读取通道 ID。")
    if action == "delete":
        commands.remove(previous); result["chartCommands"] = commands
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的通道操作。")
    values = (start_time, start_price, end_time, end_price, parallel_time, parallel_price)
    if action == "create" and any(v is None for v in values):
        raise LineError("missing_anchor", "创建通道需要基准线两点及第三个平行边界锚点，每点明确时间和价格。")
    if action == "update" and all(v is None for v in (*values, name, color, show_midline)):
        raise LineError("empty_update", "请至少修改一个锚点、名称、颜色或中线开关。")
    if show_midline is not None and not isinstance(show_midline, bool):
        raise LineError("invalid_midline", "show_midline 必须是布尔值。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    anchors = []
    for key, time, price in (("from", start_time, start_price), ("to", end_time, end_price), ("parallel", parallel_time, parallel_price)):
        old = previous.get(key, {}) if previous else {}
        value, _, _ = validate_line_fields(price=price if price is not None else old.get("price"))
        anchors.append({"time": resolve_anchor_time(payload, time) if time is not None else old["time"], "price": value})
    start, end, parallel = anchors
    geometry = channel_geometry(payload, start, end, parallel)
    channel = {"type": CHANNEL_COMMAND, "id": previous["id"] if previous else "channel_" + secrets.token_hex(12),
               "interval": payload.get("interval"), "from": start, "to": end, "parallel": parallel,
               "label": name if name is not None else previous["label"] if previous else "",
               "color": color if color is not None else previous["color"] if previous else "info",
               "show_midline": show_midline if show_midline is not None else previous["show_midline"] if previous else True,
               **geometry}
    if previous and previous.get("create_request_id"):
        channel["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            channel["create_request_id"] = request_id
            channel["id"] = "channel_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == CHANNEL_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != channel[k] for k in ("from", "to", "parallel", "label", "color", "show_midline")):
                    raise LineError("request_conflict", "同一 request_id 的通道参数不同，请使用新的 request_id。")
                return result, deepcopy(retry)
        if len(channels(result)) >= MAX_CHANNELS:
            raise LineError("too_many_channels", "当前图表最多保存 30 个 AI 通道。")
        commands.append(channel)
    else:
        commands[commands.index(previous)] = channel
    result["chartCommands"] = commands
    return result, deepcopy(channel)
