"""Explicit price/time platform rectangles; no automatic range identification."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import secrets
from typing import Any

from tools.lines import LineError, validate_line_fields
from tools.trend_lines import resolve_anchor_time

RECTANGLE_COMMAND = "DRAW_AGENT_RECTANGLE"
MAX_RECTANGLES = 30


def rectangles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy([c for c in payload.get("chartCommands", []) if c.get("type") == RECTANGLE_COMMAND])


def edit_rectangle(
    payload: dict[str, Any], action: str, *, rectangle_id: str | None = None,
    start_time: str | None = None, end_time: str | None = None,
    lower_price: float | None = None, upper_price: float | None = None,
    name: str | None = None, color: str | None = None,
    show_fill: bool | None = None, request_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a new snapshot; invalid partial edits never modify the old rectangle."""
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    previous = next((c for c in commands if c.get("type") == RECTANGLE_COMMAND and c.get("id") == rectangle_id), None)
    if action in {"update", "delete"} and previous is None:
        raise LineError("rectangle_not_found", "当前快照不存在该 AI 平台框，请先读取平台框 ID。")
    if action == "delete":
        commands.remove(previous); result["chartCommands"] = commands
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的平台框操作。")
    if action == "create" and any(v is None for v in (start_time, end_time, lower_price, upper_price)):
        raise LineError("missing_bounds", "创建平台框需要明确起止时间、下沿和上沿价格。")
    if action == "update" and all(v is None for v in (start_time, end_time, lower_price, upper_price, name, color, show_fill)):
        raise LineError("empty_update", "请至少修改时间范围、价格边界、名称、颜色或填充开关。")
    if show_fill is not None and not isinstance(show_fill, bool):
        raise LineError("invalid_fill", "show_fill 必须是布尔值。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    lower, _, _ = validate_line_fields(price=lower_price if lower_price is not None else previous["lower_price"])
    upper, _, _ = validate_line_fields(price=upper_price if upper_price is not None else previous["upper_price"])
    start = resolve_anchor_time(payload, start_time) if start_time is not None else previous["start_time"]
    end = resolve_anchor_time(payload, end_time) if end_time is not None else previous["end_time"]
    if start >= end:
        raise LineError("invalid_anchor_order", "平台框起点必须早于终点；未自动交换时间。")
    if lower >= upper:
        raise LineError("invalid_price_bounds", "平台框下沿必须低于上沿；不接受零高度，也不自动交换价格。")
    rectangle = {"type": RECTANGLE_COMMAND, "id": previous["id"] if previous else "rect_" + secrets.token_hex(12),
                 "interval": payload.get("interval"), "start_time": start, "end_time": end,
                 "lower_price": lower, "upper_price": upper,
                 "label": name if name is not None else previous["label"] if previous else "",
                 "color": color if color is not None else previous["color"] if previous else "info",
                 "show_fill": show_fill if show_fill is not None else previous["show_fill"] if previous else True}
    if previous and previous.get("create_request_id"):
        rectangle["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            rectangle["create_request_id"] = request_id
            rectangle["id"] = "rect_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == RECTANGLE_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != rectangle[k] for k in ("start_time", "end_time", "lower_price", "upper_price", "label", "color", "show_fill")):
                    raise LineError("request_conflict", "同一 request_id 的平台框参数不同，请使用新的 request_id。")
                return result, deepcopy(retry)
        if len(rectangles(result)) >= MAX_RECTANGLES:
            raise LineError("too_many_rectangles", "当前图表最多保存 30 个 AI 平台框。")
        commands.append(rectangle)
    else:
        commands[commands.index(previous)] = rectangle
    result["chartCommands"] = commands
    return result, deepcopy(rectangle)
