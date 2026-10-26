"""Bounded, candle-aligned fill between two deterministic price sources."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.lines import LineError, validate_line_fields
from tools.price_series import PriceCondition, PriceSource, calculate_price_series, candle_sequence_hash, MAX_SERIES_BARS

BAND_COMMAND = "DRAW_AGENT_PRICE_BAND"
MAX_PRICE_BANDS = 4


class BollBandSource(BaseModel):
    """Metadata for one selected TA-Lib BBANDS group, not host-supplied prices."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bbands"]
    output: Literal["upperband", "lowerband"]
    period: int = Field(strict=True, ge=2, le=200)
    deviation_up: float = Field(gt=0, le=5, allow_inf_nan=False)
    deviation_down: float = Field(gt=0, le=5, allow_inf_nan=False)
    matype: Literal[0] = 0


def _band_source(value, output):
    if isinstance(value, dict) and value.get("kind") == "bbands":
        source = BollBandSource.model_validate(value).model_dump()
        if source["output"] != output:
            raise LineError("invalid_boll_source", "BOLL 上下轨来源不匹配。")
        return source
    return PriceSource.model_validate(value).model_dump(exclude_none=True)


def _middle_values(values, lower, upper):
    if not isinstance(values, list) or len(values) != len(lower):
        raise LineError("invalid_boll_middle", "BOLL 中轨长度与当前K线不一致。")
    for middle, low, high in zip(values, lower, upper):
        if low is None:
            if middle is None: continue
            raise LineError("invalid_boll_middle", "BOLL 中轨空值须与上下轨同步。")
        if (type(middle) not in (int, float) or not math.isfinite(middle)
                or not low < middle < high):
            raise LineError("invalid_boll_middle", "BOLL 中轨必须在有效上下轨之间，空值须同步。")
    return list(values)


def calculate_price_band(rows, upper_source: PriceSource, lower_source: PriceSource,
                         condition: PriceCondition | None = None):
    upper = calculate_price_series(rows, upper_source, condition)["values"]
    lower = calculate_price_series(rows, lower_source, condition)["values"]
    upper_values, lower_values = [], []
    for high, low in zip(upper, lower):
        if high is None or low is None:
            upper_values.append(None); lower_values.append(None)
        elif high <= low:
            raise LineError("invalid_price_band_order", "条件命中的上下边界必须严格保持上方高于下方；未交换或忽略交叉K线。")
        else:
            upper_values.append(high); lower_values.append(low)
    matches = sum(value is not None for value in upper_values)
    segments = sum(value is not None and (index == 0 or upper_values[index - 1] is None)
                   for index, value in enumerate(upper_values))
    return {"upper_values": upper_values, "lower_values": lower_values,
            "summary": {"loaded_bars": len(rows), "matched_bars": matches,
                        "segment_count": segments, "empty": matches == 0,
                        "warmup_or_condition_gaps": len(rows) - matches, "drawing_created": False}}


def validate_band_values(upper_values, lower_values, count):
    if (type(count) is not int or not 1 <= count <= MAX_SERIES_BARS
            or not isinstance(upper_values, list) or not isinstance(lower_values, list)
            or len(upper_values) != count or len(lower_values) != count):
        raise LineError("invalid_price_band_values", "带状序列长度与当前K线不一致。")
    for high, low in zip(upper_values, lower_values):
        if high is None and low is None: continue
        if (type(high) not in (int, float) or type(low) not in (int, float)
                or not math.isfinite(high) or not math.isfinite(low) or low <= 0 or high <= low):
            raise LineError("invalid_price_band_values", "带状边界无效或空值未成对出现。")
    if not any(value is not None for value in upper_values):
        raise LineError("empty_price_band", "条件没有命中可填充K线，未创建空带。")
    return list(upper_values), list(lower_values)


def edit_price_band(payload, action, *, band_id=None, upper_source=None, lower_source=None,
                    condition=None, upper_values=None, lower_values=None, middle_values=None, name=None, color=None,
                    request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    rows = next((c.get("rows", []) for c in commands if c.get("type") == "SET_CANDLES"), [])
    matches = [c for c in commands if c.get("type") == BAND_COMMAND and c.get("id") == band_id]
    if len(matches) > 1: raise LineError("ambiguous_drawing_id", "同一带状对象 ID 不唯一。")
    previous = matches[0] if matches else None
    if action in {"update", "delete"} and previous is None:
        raise LineError("price_band_not_found", "当前图不存在该 AI 带状对象。")
    if action == "delete":
        if any(value is not None for value in (upper_source, lower_source, condition, upper_values,
                                                lower_values, middle_values, name, color)):
            raise LineError("invalid_edit_fields", "删除带状对象只需对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}: raise LineError("invalid_action", "不支持的带状对象操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    supplied = [upper_source, lower_source, upper_values, lower_values]
    if action == "create" and any(value is None for value in supplied):
        raise LineError("band_result_required", "创建带状对象必须使用完整函数结果引用。")
    if any(value is None for value in supplied) and any(value is not None for value in supplied):
        raise LineError("band_result_required", "修改边界或条件时须重新运行函数并使用完整结果引用。")
    if all(value is None for value in supplied) and middle_values is not None:
        raise LineError("band_result_required", "修改 BOLL 中轨必须重新运行函数并使用完整结果引用。")
    if action == "update" and all(value is None for value in supplied) and name is None and color is None:
        raise LineError("empty_update", "请指定新函数结果、名称或颜色。")
    if all(value is not None for value in supplied):
        upper_values, lower_values = validate_band_values(upper_values, lower_values, len(rows))
        upper_source = _band_source(upper_source, "upperband")
        lower_source = _band_source(lower_source, "lowerband")
        is_boll = upper_source["kind"] == "bbands"
        if is_boll != (lower_source["kind"] == "bbands"):
            raise LineError("invalid_boll_source", "BOLL 上下轨必须来自同一组计算。")
        if is_boll:
            if (condition is not None or {k: v for k, v in upper_source.items() if k != "output"}
                    != {k: v for k, v in lower_source.items() if k != "output"}):
                raise LineError("invalid_boll_source", "BOLL 上中下轨必须使用同一函数参数且不可附加条件。")
            middle_values = _middle_values(middle_values, lower_values, upper_values)
        elif middle_values is not None:
            raise LineError("invalid_boll_middle", "普通价带不能附带 BOLL 中轨。")
        condition = PriceCondition.model_validate(condition).model_dump(exclude_none=True) if condition is not None else None
    else:
        upper_values, lower_values = validate_band_values(previous["upper_values"], previous["lower_values"], len(rows))
        upper_source, lower_source, condition = previous["upper_source"], previous["lower_source"], previous.get("condition")
        middle_values = previous.get("middle_values")
    obj = {"type": BAND_COMMAND, "id": previous["id"] if previous else "band_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "bar_count": len(rows),
           "row_hash": candle_sequence_hash(rows),
           "upper_source": upper_source, "lower_source": lower_source, "condition": condition,
           "upper_values": upper_values, "lower_values": lower_values,
           "label": name if name is not None else previous.get("label", "") if previous else "",
           "color": color if color is not None else previous.get("color", "info") if previous else "info"}
    if middle_values is not None:
        obj["middle_values"] = middle_values
    obj["band_hash"] = hashlib.sha256(json.dumps({"upper_source": upper_source, "lower_source": lower_source,
        "condition": condition, "upper_values": upper_values, "lower_values": lower_values,
        **({"middle_values": middle_values} if middle_values is not None else {})},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if previous and previous.get("create_request_id"): obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "band_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == BAND_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(key) != obj.get(key) for key in ("interval", "bar_count", "upper_source", "lower_source",
                    "condition", "upper_values", "lower_values", "middle_values", "label", "color")):
                    raise LineError("request_conflict", "同一 request_id 的带状参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == BAND_COMMAND for c in commands) >= MAX_PRICE_BANDS:
            raise LineError("too_many_price_bands", "当前图最多保存4个 AI 带状对象。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
