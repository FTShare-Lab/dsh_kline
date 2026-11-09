"""Atomic snapshot objects for reviewed price patterns and nine counts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from tools.lines import LineError, validate_line_fields

PATTERN_COMMAND = "DRAW_AGENT_PRICE_PATTERN"
NINE_COMMAND = "DRAW_AGENT_NINE_COUNT"
MAX_PATTERNS = 20


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _valid_time(value, times):
    return type(value) is int and value in times


def edit_pattern_group(payload, action, *, kind, group_id=None, pattern=None, marks=None,
                       events=None, rule_version=None, as_of=None, name=None, color=None, request_id=None):
    if kind not in {"price_pattern", "nine_count"}:
        raise LineError("invalid_pattern_group", "未知形态组类型。")
    command = PATTERN_COMMAND if kind == "price_pattern" else NINE_COMMAND
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    rows = next((c.get("rows", []) for c in commands if c.get("type") == "SET_CANDLES"), [])
    times = {r["time"] for r in rows}
    matches = [c for c in commands if c.get("type") == command and c.get("id") == group_id]
    if len(matches) > 1:
        raise LineError("ambiguous_drawing_id", "该组对象 ID 不唯一。")
    previous = matches[0] if matches else None
    if action != "create" and previous is None:
        raise LineError("pattern_group_not_found", "当前图没有该组对象。")
    if action == "delete":
        if any(v is not None for v in (pattern, marks, events, rule_version, as_of, name, color)):
            raise LineError("invalid_edit_fields", "删除组对象只能提供对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的组对象操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    supplied = pattern is not None if kind == "price_pattern" else marks is not None
    if action == "create" and not supplied:
        raise LineError("analysis_result_required", "保存分析结果必须提供当前有效引用。")
    if not supplied and any(v is not None for v in (events, rule_version, as_of)):
        raise LineError("analysis_result_required", "更新几何必须重新分析并提供完整结果引用。")
    if action == "update" and not supplied and name is None and color is None:
        raise LineError("empty_update", "请提供名称、颜色或新分析结果。")
    if supplied:
        if not isinstance(rule_version, str) or rule_version not in {"price_patterns_v1", "nine_count_v1"}:
            raise LineError("invalid_pattern_version", "规则版本无效。")
        if not _valid_time(as_of, times):
            raise LineError("analysis_result_stale", "分析截止日已不在当前加载范围，请重新分析。")
        if kind == "price_pattern":
            if not isinstance(pattern, dict) or pattern.get("type") not in {"double_top", "double_bottom", "head_shoulders_top", "head_shoulders_bottom", "platform"}:
                raise LineError("invalid_pattern_geometry", "价格形态结构无效。")
            anchors = pattern.get("anchors")
            if not isinstance(anchors, list) or any(not isinstance(a, dict) or not _valid_time(a.get("time"), times) for a in anchors):
                raise LineError("analysis_result_stale", "形态锚点已不在当前加载范围，请重新分析。")
            if pattern["type"] == "platform" and pattern.get("box", {}).get("start_time") not in times:
                raise LineError("analysis_result_stale", "平台形成区间已不在当前加载范围，请重新分析。")
            geometry = {"pattern": deepcopy(pattern)}
        else:
            if not isinstance(marks, list) or not 1 <= len(marks) <= 240 or not isinstance(events, list):
                raise LineError("invalid_nine_geometry", "九转标注序列无效。")
            if any(not isinstance(m, dict) or not _valid_time(m.get("time"), times)
                   or m.get("direction") not in {"up", "down"} or type(m.get("count")) is not int
                   or not 1 <= m["count"] <= 9 for m in marks):
                raise LineError("invalid_nine_geometry", "九转标注与当前日线不一致。")
            geometry = {"marks": deepcopy(marks), "events": deepcopy(events)}
    else:
        geometry = {"pattern": deepcopy(previous["pattern"])} if kind == "price_pattern" else {
            "marks": deepcopy(previous["marks"]), "events": deepcopy(previous["events"])}
        rule_version, as_of = previous["rule_version"], previous["as_of"]
    obj = {"type": command, "id": previous["id"] if previous else ("pattern_" if kind == "price_pattern" else "nine_") + _hash(request_id or "")[:24],
           "interval": payload.get("interval"), "rule_version": rule_version, "as_of": as_of,
           "geometry_hash": _hash({"rule_version": rule_version, "as_of": as_of, **geometry}),
           "bar_count": len(geometry["marks"]) if kind == "nine_count" else len(geometry["pattern"].get("anchors", [])),
           "label": name if name is not None else previous.get("label", "") if previous else "",
           "color": color if color is not None else previous.get("color", "info") if previous else "info", **geometry}
    if previous and previous.get("create_request_id"):
        obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if not request_id:
            raise LineError("request_id_required", "组对象创建需要稳定请求 ID。")
        obj["create_request_id"] = request_id
        retry = next((c for c in commands if c.get("type") == command and c.get("create_request_id") == request_id), None)
        if retry:
            if retry != obj:
                raise LineError("request_conflict", "同一请求 ID 的组对象参数不同。")
            return result, deepcopy(retry)
        limit = MAX_PATTERNS if kind == "price_pattern" else 1
        if sum(c.get("type") == command and c.get("interval") == payload.get("interval") for c in commands) >= limit:
            raise LineError("too_many_pattern_groups", "当前图的形态或九转组对象已达上限。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
