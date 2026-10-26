"""Deterministic, bounded per-candle sticks on the current price pane."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import secrets

from tools.lines import LineError, validate_line_fields
from tools.price_series import (PriceCondition, PriceSource, MAX_SERIES_BARS,
                                calculate_price_series, candle_sequence_hash)

STICKS_COMMAND = "DRAW_AGENT_PRICE_STICKS"
MAX_PRICE_STICKS = 4


def calculate_price_sticks(rows, first_source: PriceSource, second_source: PriceSource,
                           condition: PriceCondition | None = None):
    first = calculate_price_series(rows, first_source, condition)["values"]
    second = calculate_price_series(rows, second_source, condition)["values"]
    start, end = [], []
    equal_endpoints = 0
    for one, two in zip(first, second):
        if one is None or two is None or one == two:
            start.append(None)
            end.append(None)
            if one is not None and two is not None: equal_endpoints += 1
        else:
            start.append(one)
            end.append(two)
    matches = sum(value is not None for value in start)
    return {"start_values": start, "end_values": end,
            "summary": {"loaded_bars": len(rows), "matched_bars": matches,
                        "empty": matches == 0, "warmup_or_condition_gaps": len(rows) - matches,
                        "equal_endpoints_skipped": equal_endpoints, "drawing_created": False}}


def validate_stick_values(start_values, end_values, count):
    if (type(count) is not int or not 1 <= count <= MAX_SERIES_BARS
            or not isinstance(start_values, list) or not isinstance(end_values, list)
            or len(start_values) != count or len(end_values) != count):
        raise LineError("invalid_price_stick_values", "柱线序列长度与当前K线不一致。")
    for start, end in zip(start_values, end_values):
        if start is None and end is None: continue
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start <= 0 or end <= 0 or start == end):
            raise LineError("invalid_price_stick_values", "柱线端点无效、等价或空值未成对出现。")
    if not any(value is not None for value in start_values):
        raise LineError("empty_price_sticks", "条件没有命中可绘制柱线，未创建空对象。")
    return list(start_values), list(end_values)


def edit_price_sticks(payload, action, *, sticks_id=None, start_source=None, end_source=None,
                      condition=None, start_values=None, end_values=None, name=None, color=None,
                      request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    rows = next((c.get("rows", []) for c in commands if c.get("type") == "SET_CANDLES"), [])
    matches = [c for c in commands if c.get("type") == STICKS_COMMAND and c.get("id") == sticks_id]
    if len(matches) > 1: raise LineError("ambiguous_drawing_id", "同一柱线对象 ID 不唯一。")
    previous = matches[0] if matches else None
    if action in {"update", "delete"} and previous is None:
        raise LineError("price_sticks_not_found", "当前图不存在该 AI 柱线对象。")
    if action == "delete":
        if any(value is not None for value in (start_source, end_source, condition, start_values,
                                                end_values, name, color)):
            raise LineError("invalid_edit_fields", "删除柱线对象只需对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}: raise LineError("invalid_action", "不支持的柱线对象操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    supplied = [start_source, end_source, start_values, end_values]
    if action == "create" and any(value is None for value in supplied):
        raise LineError("sticks_result_required", "创建柱线对象必须使用完整函数结果引用。")
    if any(value is None for value in supplied) and any(value is not None for value in supplied):
        raise LineError("sticks_result_required", "修改端点或条件时须重新运行函数并使用完整结果引用。")
    if action == "update" and all(value is None for value in supplied) and name is None and color is None:
        raise LineError("empty_update", "请指定新函数结果、名称或颜色。")
    if all(value is not None for value in supplied):
        start_values, end_values = validate_stick_values(start_values, end_values, len(rows))
        start_source = PriceSource.model_validate(start_source).model_dump(exclude_none=True)
        end_source = PriceSource.model_validate(end_source).model_dump(exclude_none=True)
        condition = PriceCondition.model_validate(condition).model_dump(exclude_none=True) if condition is not None else None
    else:
        start_values, end_values = validate_stick_values(previous["start_values"], previous["end_values"], len(rows))
        start_source, end_source, condition = previous["start_source"], previous["end_source"], previous.get("condition")
    obj = {"type": STICKS_COMMAND, "id": previous["id"] if previous else "sticks_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "bar_count": len(rows), "row_hash": candle_sequence_hash(rows),
           "start_source": start_source, "end_source": end_source, "condition": condition,
           "start_values": start_values, "end_values": end_values,
           "label": name if name is not None else previous.get("label", "") if previous else "",
           "color": color if color is not None else previous.get("color", "info") if previous else "info"}
    obj["sticks_hash"] = hashlib.sha256(json.dumps({"start_source": start_source, "end_source": end_source,
        "condition": condition, "start_values": start_values, "end_values": end_values},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if previous and previous.get("create_request_id"): obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "sticks_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == STICKS_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(key) != obj[key] for key in ("interval", "bar_count", "start_source", "end_source",
                    "condition", "start_values", "end_values", "label", "color")):
                    raise LineError("request_conflict", "同一 request_id 的柱线参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == STICKS_COMMAND for c in commands) >= MAX_PRICE_STICKS:
            raise LineError("too_many_price_sticks", "当前图最多保存4组 AI 柱线。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
