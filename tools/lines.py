"""Explicit, snapshot-scoped horizontal lines; no market fetches or auto levels."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import secrets
from typing import Any, Literal

LINE_COMMAND = "DRAW_HORIZONTAL_LINE"
MAX_LINES = 60
COLORS = {"info", "success", "warning", "danger"}
COLOR_ALIASES = {"blue": "info", "蓝色": "info", "green": "success", "绿色": "success",
                 "orange": "warning", "橙色": "warning", "red": "danger", "红色": "danger"}
ColorInput = Literal["info", "success", "warning", "danger", "blue", "green", "orange", "red", "蓝色", "绿色", "橙色", "红色"]


class LineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def horizontal_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy([c for c in payload.get("chartCommands", []) if c.get("type") == LINE_COMMAND])


def validate_line_fields(*, price: float | None = None, name: str | None = None,
                         color: str | None = None, request_id: str | None = None) -> tuple[float | None, str | None, str | None]:
    """Shared field validation; normalize colors without creating throwaway drawings."""
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise LineError("invalid_price", "价格必须是大于零的有限数值。")
    if name is not None:
        if not isinstance(name, str) or len(name.strip()) > 48 or any(ord(c) < 32 for c in name):
            raise LineError("invalid_name", "名称最多 48 个字符，不能包含控制字符。")
        name = name.strip()
    if color is not None:
        if not isinstance(color, str):
            raise LineError("invalid_color", "颜色必须为支持的颜色名称。")
        color = COLOR_ALIASES.get(color.strip().lower(), color.strip().lower())
        if color not in COLORS:
            raise LineError("invalid_color", "颜色请选择蓝色/info、绿色/success、橙色/warning 或红色/danger。")
    if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 128):
        raise LineError("invalid_request_id", "request_id 必须是 1 至 128 个字符。")
    return float(price) if price is not None else None, name, color


def edit_horizontal_line(
    payload: dict[str, Any], action: str, *, line_id: str | None = None,
    price: float | None = None, name: str | None = None,
    color: str | None = None, request_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a copy; failed validation never mutates the source chart."""
    price, name, color = validate_line_fields(price=price, name=name, color=color, request_id=request_id)
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    if action == "create":
        if price is None:
            raise LineError("invalid_price", "创建水平线需要指定价格。")
        line = {"type": LINE_COMMAND, "id": "line_" + secrets.token_hex(12),
                "price": float(price), "label": name or "", "color": color or "info"}
        if request_id:
            line["create_request_id"] = request_id
            # Retrying against the same snapshot also keeps a stable line ID.
            line["id"] = "line_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            previous = next((c for c in commands if c.get("type") == LINE_COMMAND
                             and c.get("create_request_id") == request_id), None)
            if previous:
                if any(previous.get(k) != line[k] for k in ("price", "label", "color")):
                    raise LineError("request_conflict", "同一 request_id 的绘图参数不同，请使用新的 request_id。")
                return result, deepcopy(previous)
        if len(horizontal_lines(result)) >= MAX_LINES:
            raise LineError("too_many_lines", "当前图表最多保存 60 条 AI 水平线。")
        commands.append(line)
    elif action in {"update", "delete"}:
        line = next((c for c in commands if c.get("type") == LINE_COMMAND and c.get("id") == line_id), None)
        if line is None:
            raise LineError("line_not_found", "当前图表不存在该水平线，请先读取当前图表中的水平线 ID。")
        if action == "delete":
            commands.remove(line)
        else:
            if price is None and name is None and color is None:
                raise LineError("empty_update", "请至少指定价格、名称或颜色中的一项。")
            if price is not None: line["price"] = float(price)
            if name is not None: line["label"] = name
            if color is not None: line["color"] = color
    else:
        raise LineError("invalid_action", "不支持的水平线操作。")
    result["chartCommands"] = commands
    return result, deepcopy(line)
