"""Explicit, time/price anchored text, numeric and icon chart annotations."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import secrets

from tools.lines import LineError, validate_line_fields
from tools.trend_lines import resolve_anchor_time

ANNOTATION_COMMAND = "DRAW_AGENT_ANNOTATION"
ANNOTATION_KINDS = {"text_annotation", "number_annotation", "icon_annotation"}
ANNOTATION_ICONS = {"arrow_up", "arrow_down", "diamond"}
MAX_ANNOTATIONS = 80


def _validate_content(kind, text, value, icon=None):
    if kind == "text_annotation":
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 120 or any(ord(c) < 32 for c in text):
            raise LineError("invalid_annotation_text", "文字标注需为1至120个字符，且不能包含控制字符。")
        if value is not None or icon is not None: raise LineError("invalid_edit_fields", "文字标注不能设置数值或图标字段。")
        return text.strip(), None
    if kind == "number_annotation":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise LineError("invalid_annotation_value", "数值标注必须是有限数字。")
        if text is not None or icon is not None: raise LineError("invalid_edit_fields", "数值标注不能设置文字或图标字段。")
        return None, float(value)
    if kind == "icon_annotation":
        if icon not in ANNOTATION_ICONS:
            raise LineError("invalid_annotation_icon", "图标标注仅支持 arrow_up、arrow_down 或 diamond。")
        if text is not None or value is not None: raise LineError("invalid_edit_fields", "图标标注不能设置文字或数值字段。")
        return None, None
    raise LineError("invalid_annotation_kind", "不支持的标注类型。")


def validate_annotation(command):
    if not isinstance(command, dict) or command.get("type") != ANNOTATION_COMMAND:
        raise LineError("invalid_annotation", "标注对象格式无效。")
    kind = command.get("kind")
    text, value = _validate_content(kind, command.get("text"), command.get("value"), command.get("icon"))
    time, price = command.get("time"), command.get("price")
    if type(time) is not int or time <= 0 or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise LineError("invalid_annotation_anchor", "标注锚点必须包含有效 K 线时间和大于零的价格。")
    return {"type": ANNOTATION_COMMAND, "kind": kind, "id": command["id"], "interval": command.get("interval"),
            "label": command.get("label", ""), "color": command.get("color", "info"), "time": time,
            "price": float(price), **({"text": text} if kind == "text_annotation" else
                                      {"value": value} if kind == "number_annotation" else {"icon": command["icon"]})}


def edit_annotation(payload, action, *, kind, annotation_id=None, anchor_time=None, anchor_price=None,
                    text=None, value=None, icon=None, name=None, color=None, request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    matches = [c for c in commands if c.get("type") == ANNOTATION_COMMAND and c.get("id") == annotation_id]
    if len(matches) > 1: raise LineError("ambiguous_drawing_id", "同一标注 ID 不唯一，不能安全修改。")
    previous = matches[0] if matches else None
    if action in {"update", "delete"} and previous is None:
        raise LineError("annotation_not_found", "当前快照不存在该 AI 标注，请先读取完整对象 ID。")
    if previous and previous.get("kind") != kind:
        raise LineError("drawing_kind_mismatch", "标注 ID 与指定类型不一致。")
    if action == "delete":
        if any(v is not None for v in (anchor_time, anchor_price, text, value, icon, name, color)):
            raise LineError("invalid_edit_fields", "删除标注只需对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"} or kind not in ANNOTATION_KINDS:
        raise LineError("invalid_annotation_kind", "不支持的标注类型或操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    if action == "create":
        if anchor_time is None or anchor_price is None:
            raise LineError("annotation_anchor_required", "创建标注必须明确指定已加载 K 线时间和价格。")
        text, value = _validate_content(kind, text, value, icon)
        timestamp = resolve_anchor_time(payload, anchor_time)
        price, _, _ = validate_line_fields(price=anchor_price)
        if price is None: raise LineError("invalid_annotation_anchor", "标注价格无效。")
    else:
        if anchor_time is None and anchor_price is None and text is None and value is None and icon is None and name is None and color is None:
            raise LineError("empty_update", "请指定标注的新位置、内容、名称或颜色。")
        old = validate_annotation(previous)
        timestamp = resolve_anchor_time(payload, anchor_time) if anchor_time is not None else old["time"]
        price = validate_line_fields(price=anchor_price)[0] if anchor_price is not None else old["price"]
        if kind == "text_annotation":
            if value is not None: raise LineError("invalid_edit_fields", "文字标注不能设置数值字段。")
            content, number = _validate_content(kind, text if text is not None else old.get("text"), None)
            icon = None
        elif kind == "number_annotation":
            if text is not None: raise LineError("invalid_edit_fields", "数值标注不能设置文字字段。")
            content, number = _validate_content(kind, None, value if value is not None else old.get("value"))
            icon = None
        else:
            if text is not None or value is not None: raise LineError("invalid_edit_fields", "图标标注不能设置文字或数值字段。")
            content, number = _validate_content(kind, None, None, icon if icon is not None else old.get("icon"))
            icon = icon if icon is not None else old.get("icon")
        text, value = content, number
    obj = {"type": ANNOTATION_COMMAND, "kind": kind,
           "id": previous["id"] if previous else "ann_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "label": name if name is not None else previous.get("label", "") if previous else "",
           "color": color if color is not None else previous.get("color", "info") if previous else "info",
           "time": timestamp, "price": float(price)}
    if kind == "text_annotation": obj["text"] = text
    elif kind == "number_annotation": obj["value"] = value
    else: obj["icon"] = icon
    if previous and previous.get("create_request_id"): obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "ann_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == ANNOTATION_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != obj[k] for k in ("kind", "label", "color", "time", "price", "text", "value", "icon")):
                    raise LineError("request_conflict", "同一 request_id 的标注参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == ANNOTATION_COMMAND for c in commands) >= MAX_ANNOTATIONS:
            raise LineError("too_many_annotations", "当前图表最多保存80个 AI 标注。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
