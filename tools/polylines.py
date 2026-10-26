"""Explicit labeled time/price paths, not automatic wave recognition."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import secrets

from pydantic import BaseModel, ConfigDict, Field

from tools.lines import LineError, validate_line_fields
from tools.trend_lines import resolve_anchor_time

POLYLINE_COMMAND = "DRAW_AGENT_POLYLINE"
MAX_POINTS = 8
MAX_POLYLINES = 30


class LabeledPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=16, description="点名，组内唯一，例如 A、B、C 或 1、2；不是自动识浪结果")
    time: str = Field(min_length=1, description="已加载 K 线的日期、带时区 ISO 或 Unix 秒字符串")
    price: float = Field(gt=0, allow_inf_nan=False, strict=True)


def normalize_point_label(label):
    if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 16
        or any(ord(c) < 32 for c in label)):
        raise LineError("invalid_point_label", "点名需为1至16个字符，不能空白或包含控制字符。")
    return label.strip()


def validate_stored_points(points):
    """Whitelist canonical object fields; never sort, truncate or repair a path."""
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_POINTS:
        raise LineError("invalid_polyline_points", "折线需要2至8个明确的带标签锚点。")
    cleaned = []
    for point in points:
        if not isinstance(point, dict) or type(point.get("time")) is not int or point["time"] <= 0:
            raise LineError("invalid_polyline_points", "折线锚点时间格式无效。")
        label = normalize_point_label(point.get("label"))
        price, _, _ = validate_line_fields(price=point.get("price"))
        if price is None: raise LineError("invalid_price", "每个折线锚点都需要明确价格。")
        cleaned.append({"label": label, "time": point["time"], "price": price})
    if len({p["label"] for p in cleaned}) != len(cleaned):
        raise LineError("duplicate_point_label", "同组点名必须唯一，不能按重复标签猜点。")
    if any(a["time"] >= b["time"] for a, b in zip(cleaned, cleaned[1:])):
        raise LineError("invalid_anchor_order", "折线锚点时间必须递增；不自动排序或交换点位。")
    return cleaned


def resolve_points(payload, points):
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_POINTS:
        raise LineError("invalid_polyline_points", "折线需要2至8个明确的带标签锚点。")
    resolved = []
    for raw in points:
        point = raw.model_dump() if isinstance(raw, LabeledPoint) else raw
        if not isinstance(point, dict) or set(point) != {"label", "time", "price"}:
            raise LineError("invalid_polyline_points", "每个锚点只包含 label、time、price。")
        resolved.append({**point, "time": resolve_anchor_time(payload, point["time"])})
    return validate_stored_points(resolved)


def edit_polyline(payload, action, *, polyline_id=None, points=None, point_label=None,
                  point_time=None, point_price=None, name=None, color=None, request_id=None):
    result = deepcopy(payload)
    commands = result.get("chartCommands", [])
    matches = [c for c in commands if c.get("type") == POLYLINE_COMMAND and c.get("id") == polyline_id]
    if len(matches) > 1:
        raise LineError("ambiguous_drawing_id", "同一对象 ID 不唯一，不能安全修改。")
    previous = matches[0] if matches else None
    if action in {"update", "delete"} and previous is None:
        raise LineError("polyline_not_found", "当前快照不存在该 AI 标注折线，请先读回完整对象 ID。")
    if action == "delete":
        if any(v is not None for v in (points, point_label, point_time, point_price, name, color)):
            raise LineError("invalid_edit_fields", "删除整组只需对象 ID。")
        commands.remove(previous)
        return result, deepcopy(previous)
    if action not in {"create", "update"}:
        raise LineError("invalid_action", "不支持的标注折线操作。")
    _, name, color = validate_line_fields(name=name, color=color, request_id=request_id)
    if action == "create":
        if any(v is not None for v in (point_label, point_time, point_price)):
            raise LineError("invalid_edit_fields", "创建需完整 points，单点修改字段只用于更新。")
        path = resolve_points(payload, points)
    else:
        # Updating one point must not require the LLM to copy/reconstruct its
        # neighbours. Full replacement/point insertion/removal are out of scope.
        if points is not None:
            raise LineError("polyline_replacement_not_supported", "续改请用 point_label 及 point_time / point_price，仅改目标点；不接受整组重写。")
        path = validate_stored_points(previous["points"])
        if point_label is not None:
            label = normalize_point_label(point_label)
            if point_time is None and point_price is None:
                raise LineError("empty_point_update", "请明确目标点的新时间或价格，不能猜移动幅度。")
            target = next((p for p in path if p["label"] == label), None)
            if target is None:
                raise LineError("point_not_found", "当前组内不存在该点名；请核对点名，不按位置或近似名称猜点。")
            if point_time is not None: target["time"] = resolve_anchor_time(payload, point_time)
            if point_price is not None: target["price"] = validate_line_fields(price=point_price)[0]
        elif point_time is not None or point_price is not None:
            raise LineError("point_label_required", "修改单点必须明确组内 point_label。")
        elif name is None and color is None:
            raise LineError("empty_update", "请指定点名及新时间 / 价格，或整组名称 / 颜色。")
        path = validate_stored_points(path)
        for point in path: resolve_anchor_time(payload, str(point["time"]))
    obj = {"type": POLYLINE_COMMAND, "id": previous["id"] if previous else "poly_" + secrets.token_hex(12),
           "interval": payload.get("interval"), "points": path,
           "label": name if name is not None else previous["label"] if previous else "",
           "color": color if color is not None else previous["color"] if previous else "info"}
    if previous and previous.get("create_request_id"): obj["create_request_id"] = previous["create_request_id"]
    if action == "create":
        if request_id:
            obj["create_request_id"] = request_id
            obj["id"] = "poly_" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
            retry = next((c for c in commands if c.get("type") == POLYLINE_COMMAND and c.get("create_request_id") == request_id), None)
            if retry:
                if any(retry.get(k) != obj[k] for k in ("points", "label", "color", "interval")):
                    raise LineError("request_conflict", "同一 request_id 的标注折线参数不同。")
                return result, deepcopy(retry)
        if sum(c.get("type") == POLYLINE_COMMAND for c in commands) >= MAX_POLYLINES:
            raise LineError("too_many_polylines", "当前图表最多保存30组 AI 标注折线。")
        commands.append(obj)
    else:
        commands[commands.index(previous)] = obj
    return result, deepcopy(obj)
