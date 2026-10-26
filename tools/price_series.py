"""Deterministic price-series lines on the currently loaded candles only."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import secrets
import struct
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.calc import series_ma
from core.ta_engine import calculate
from tools.lines import LineError, validate_line_fields

SERIES_COMMAND = "DRAW_AGENT_SERIES_LINE"
MAX_SERIES_LINES = 8
MAX_SERIES_BARS = 4000


def candle_sequence_hash(rows):
    """Stable browser-compatible identity for candle-index-aligned drawings."""
    value = 0xcbf29ce484222325
    for row in rows:
        for key in ("time", "open", "high", "low", "close", "volume"):
            for byte in struct.pack(">d", float(row[key])):
                value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f"{value:016x}"


class PriceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["open", "high", "low", "close", "sma", "ema"]
    period: int | None = Field(default=None, strict=True, ge=2, le=200)

    @model_validator(mode="after")
    def valid_period(self):
        if (self.kind in {"sma", "ema"}) != (self.period is not None):
            raise ValueError("period is required only for sma or ema")
        return self


class PriceOperand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: PriceSource | None = None
    constant: float | None = Field(default=None, strict=True, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def one_value(self):
        if (self.source is None) == (self.constant is None):
            raise ValueError("exactly one of source or constant is required")
        return self


class PriceCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: PriceSource
    op: Literal["gt", "gte", "lt", "lte"]
    right: PriceOperand


def _source_values(rows, source: PriceSource):
    if source.kind not in {"sma", "ema"}:
        return [row[source.kind] for row in rows]
    if source.kind == "sma":
        ma = series_ma(rows, [source.period])[f"ma{source.period}"]
        return [ma.get(row["time"]) for row in rows]
    return calculate("EMA", rows, parameters={"timeperiod": source.period})[1]["real"]


def calculate_price_series(rows, source: PriceSource, condition: PriceCondition | None = None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SERIES_BARS:
        raise LineError("invalid_price_series_history", "仅支持当前图1至4000根已加载K线，不补取行情。")
    values = _source_values(rows, source)
    left = _source_values(rows, condition.left) if condition else None
    right = (_source_values(rows, condition.right.source) if condition and condition.right.source else
             [condition.right.constant] * len(rows) if condition else None)
    operations = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b,
                  "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}
    output = []
    for index, value in enumerate(values):
        allowed = (condition is None or left[index] is not None and right[index] is not None
                   and operations[condition.op](left[index], right[index]))
        output.append(float(value) if value is not None and allowed else None)
    matches = sum(value is not None for value in output)
    segments = sum(value is not None and (index == 0 or output[index - 1] is None)
                   for index, value in enumerate(output))
    return {"values": output, "summary": {"loaded_bars": len(rows), "matched_bars": matches,
            "segment_count": segments, "empty": matches == 0,
            "warmup_or_condition_gaps": len(rows) - matches, "drawing_created": False}}


def validate_series_values(values, count):
    if (not isinstance(values, list) or len(values) != count or not 1 <= count <= MAX_SERIES_BARS
            or any(value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0)
                   for value in values)):
        raise LineError("invalid_price_series_values", "序列长度、价格或当前K线对齐关系无效。")
    if not any(value is not None for value in values):
        raise LineError("empty_price_series", "条件没有命中可绘制K线，未创建空图形。")
    return list(values)


def edit_price_series(payload, action, *, series_id=None, source=None, condition=None, values=None,
                      name=None, color=None, request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    rows = next((c["rows"] for c in commands if c.get("type") == "SET_CANDLES"), [])
    matches = [c for c in commands if c.get("type") == SERIES_COMMAND and c.get("id") == series_id]
    if len(matches) > 1:
        raise LineError("ambiguous_drawing_id", "同一序列对象 ID 不唯一，不能安全修改。")
    previous = matches[0] if matches else None
    if action in {"update", "delete"} and previous is None:
        raise LineError("series_line_not_found", "当前快照不存在该 AI 序列线，请先读回对象 ID。")
    if action == "delete":
        if any(item is not None for item in (source, condition, values, name, color)):
            raise LineError("invalid_edit_fields", "删除序列线只需对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的序列线操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    if action == "create" and (source is None or values is None):
        raise LineError("series_result_required", "创建序列线必须使用函数结果引用。")
    if (source is None) != (values is None):
        raise LineError("series_result_required", "修改计算条件时须重新运行函数并传完整结果引用。")
    if action == "update" and source is None and name is None and color is None:
        raise LineError("empty_update", "请指定新函数结果、名称或颜色。")
    if values is not None:
        clean = validate_series_values(values, len(rows))
        normalized_source = PriceSource.model_validate(source).model_dump(exclude_none=True)
        normalized_condition = (PriceCondition.model_validate(condition).model_dump(exclude_none=True)
                                if condition is not None else None)
    else:
        clean = validate_series_values(previous["values"], len(rows))
        normalized_source, normalized_condition = previous["source"], previous.get("condition")
    obj = {"type": SERIES_COMMAND, "id": previous["id"] if previous else "series_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "bar_count": len(rows),
           "row_hash": candle_sequence_hash(rows),
           "source": normalized_source, "condition": normalized_condition, "values": clean,
           "label": name if name is not None else previous.get("label", "") if previous else "",
           "color": color if color is not None else previous.get("color", "info") if previous else "info"}
    obj["series_hash"] = hashlib.sha256(json.dumps({"source": normalized_source, "condition": normalized_condition,
        "values": clean}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if previous and previous.get("create_request_id"):
        obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "series_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == SERIES_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(key) != obj[key] for key in ("bar_count", "source", "condition", "values", "label", "color", "interval")):
                    raise LineError("request_conflict", "同一 request_id 的序列线参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == SERIES_COMMAND for c in commands) >= MAX_SERIES_LINES:
            raise LineError("too_many_series_lines", "当前图表最多保存8条 AI 序列线。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
