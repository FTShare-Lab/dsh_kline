"""Finite price-domain retracements. No pivot discovery or pixel interpolation."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import secrets

from tools.lines import LineError, validate_line_fields
from tools.trend_lines import resolve_anchor_time

FIBONACCI_COMMAND = "DRAW_AGENT_FIBONACCI"
DEFAULT_RATIOS = [0, .236, .382, .5, .618, .786, 1]


def validate_ratios(ratios):
    if (not isinstance(ratios, list) or not 1 <= len(ratios) <= 16
        or any(type(r) not in (int, float) or not math.isfinite(r) or not 0 <= r <= 1 for r in ratios)
        or any(a >= b for a, b in zip(ratios, ratios[1:]))):
        raise LineError("invalid_fibonacci_ratios", "回撤比例需为1至16个递增、不重复的0至1有限数值；未自动排序。")
    return [float(r) for r in ratios]


def fibonacci_levels(start_price, end_price, ratios):
    start, _, _ = validate_line_fields(price=start_price)
    end, _, _ = validate_line_fields(price=end_price)
    if start == end:
        raise LineError("zero_fibonacci_range", "两个锚点价格不能相同。")
    levels = [{"ratio": r, "price": end - r * (end - start)} for r in validate_ratios(ratios)]
    if any(not math.isfinite(p["price"]) or p["price"] <= 0 for p in levels):
        raise LineError("invalid_fibonacci_price", "回撤价位必须为大于零的有限数值。")
    return levels


def edit_fibonacci(payload, action, *, fibonacci_id=None, start_time=None, start_price=None,
                   end_time=None, end_price=None, ratios=None, name=None, color=None, request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    previous = next((c for c in commands if c.get("type") == FIBONACCI_COMMAND and c.get("id") == fibonacci_id), None)
    if action in {"update", "delete"} and previous is None:
        raise LineError("fibonacci_not_found", "当前快照不存在该 AI 斐波那契对象，请先读取对象 ID。")
    if action == "delete":
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的斐波那契操作。")
    values = (start_time, start_price, end_time, end_price)
    if action == "create" and any(v is None for v in values):
        raise LineError("missing_anchor", "需要明确的两个时间和价格锚点，不自动选择最近高低点。")
    if action == "update" and all(v is None for v in (*values, ratios, name, color)):
        raise LineError("empty_update", "请至少修改锚点、比例、名称或颜色。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    anchors = []
    for key, time, price in (("from", start_time, start_price), ("to", end_time, end_price)):
        old = previous[key] if previous else {}
        value, _, _ = validate_line_fields(price=price if price is not None else old.get("price"))
        anchors.append({"time": resolve_anchor_time(payload, time) if time is not None else old["time"], "price": value})
    start, end = anchors
    if start["time"] >= end["time"]:
        raise LineError("invalid_anchor_order", "斐波那契起点必须早于终点；未自动交换锚点。")
    ratios = validate_ratios(ratios if ratios is not None else previous["ratios"] if previous else DEFAULT_RATIOS)
    obj = {"type": FIBONACCI_COMMAND, "id": previous["id"] if previous else "fib_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "from": start, "to": end, "ratios": ratios,
           "levels": fibonacci_levels(start["price"], end["price"], ratios), "geometry_basis": "linear_price_retracement",
           "label": name if name is not None else previous["label"] if previous else "",
           "color": color if color is not None else previous["color"] if previous else "info"}
    if previous and previous.get("create_request_id"):
        obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "fib_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == FIBONACCI_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != obj[k] for k in ("from", "to", "ratios", "label", "color")):
                    raise LineError("request_conflict", "同一 request_id 的斐波那契参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == FIBONACCI_COMMAND for c in commands) >= 30:
            raise LineError("too_many_fibonacci", "当前图表最多保存30组 AI 斐波那契对象。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
