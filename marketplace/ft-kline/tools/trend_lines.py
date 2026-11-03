"""Explicit two-anchor AI segments, separate from automatic trend annotations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Any

from tools.lines import LineError, MAX_LINES, validate_line_fields

TREND_COMMAND = "DRAW_AGENT_TREND_LINE"
CN_TZ = timezone(timedelta(hours=8))


def trend_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy([c for c in payload.get("chartCommands", []) if c.get("type") == TREND_COMMAND])


def resolve_anchor_time(payload: dict[str, Any], value: str) -> int:
    """Resolve exactly one existing bar; never silently snap to a nearby candle."""
    rows = next((c.get("rows", []) for c in payload.get("chartCommands", []) if c.get("type") == "SET_CANDLES"), [])
    if not isinstance(value, str) or not value.strip():
        raise LineError("invalid_anchor_time", "锚点时间需要 YYYY-MM-DD、带时区的 ISO 时间或 Unix 秒字符串。")
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date = datetime.strptime(value, "%Y-%m-%d").date()
            if payload.get("interval") not in {"day", "week", "month", "quarter", "year"}:
                raise LineError("ambiguous_anchor_time", "分钟周期请指定带时区的 K 线收盘时间或 Unix 秒，不能只写日期。")
            matches = [int(r["time"]) for r in rows
                       if datetime.fromtimestamp(r["time"], CN_TZ).date() == date]
        else:
            if re.fullmatch(r"\d{1,10}", value):
                timestamp = int(value)
            else:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if instant.tzinfo is None or instant.microsecond:
                    raise ValueError("explicit timezone and whole seconds required")
                timestamp = int(instant.timestamp())
            matches = [int(r["time"]) for r in rows if r["time"] == timestamp]
    except (ValueError, OverflowError, OSError) as exc:
        if isinstance(exc, LineError):
            raise
        raise LineError("invalid_anchor_time", "时间格式无效；请使用有效日期、带时区的 ISO 时间或 Unix 秒（不是毫秒）。") from exc
    if not matches:
        raise LineError("anchor_not_found", "该锚点时间不在当前快照的 K 线中，未改线；请核对交易日和图表范围，不要擅自换日期。")
    if len(matches) != 1:
        raise LineError("ambiguous_anchor_time", "该日期对应多根 K 线，请指定精确的带时区时间或 Unix 秒。")
    return matches[0]


def edit_trend_line(
    payload: dict[str, Any], action: str, *, line_id: str | None = None,
    start_time: str | None = None, start_price: float | None = None,
    end_time: str | None = None, end_price: float | None = None,
    name: str | None = None, color: str | None = None, request_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    previous = next((c for c in commands if c.get("type") == TREND_COMMAND and c.get("id") == line_id), None)
    if action in {"update", "delete"} and previous is None:
        raise LineError("line_not_found", "当前快照不存在该 AI 趋势线，请先读回趋势线 ID。")
    if action == "delete":
        commands.remove(previous)
        result["chartCommands"] = commands
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的趋势线操作。")
    if action == "update" and all(v is None for v in (start_time, start_price, end_time, end_price, name, color)):
        raise LineError("empty_update", "请至少修改一个锚点、名称或颜色。")
    if action == "create" and any(v is None for v in (start_time, start_price, end_time, end_price)):
        raise LineError("missing_anchor", "创建趋势线需要两个明确的时间和价格锚点。")
    start_price, name, color = validate_line_fields(
        price=start_price if start_price is not None else previous["from"]["price"],
        name=name, color=color, request_id=request_id)
    end_price, _, _ = validate_line_fields(price=end_price if end_price is not None else previous["to"]["price"])
    start = {"time": resolve_anchor_time(payload, start_time) if start_time is not None else previous["from"]["time"],
             "price": start_price}
    end = {"time": resolve_anchor_time(payload, end_time) if end_time is not None else previous["to"]["time"],
           "price": end_price}
    if start["time"] >= end["time"]:
        raise LineError("invalid_anchor_order", "起点时间必须早于终点时间；未自动交换锚点。")
    line = {"type": TREND_COMMAND, "id": previous["id"] if previous else "trend_" + secrets.token_hex(12),
            "from": start, "to": end,
            "label": name if name is not None else previous["label"] if previous else "",
            "color": color if color is not None else previous["color"] if previous else "info"}
    if previous and previous.get("create_request_id"):
        line["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            line["create_request_id"] = request_id
            line["id"] = "trend_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == TREND_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != line[k] for k in ("from", "to", "label", "color")):
                    raise LineError("request_conflict", "同一 request_id 的绘图参数不同，请使用新的 request_id。")
                return result, deepcopy(retry)
        if len(trend_lines(result)) >= MAX_LINES:
            raise LineError("too_many_lines", "当前图表最多保存 60 条 AI 趋势线。")
        commands.append(line)
    else:
        commands[commands.index(previous)] = line
    result["chartCommands"] = commands
    return result, deepcopy(line)
