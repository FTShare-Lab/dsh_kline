"""Version-guarded drawing preparation. Never applies a candidate to the live UI."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

import chart_service
from core.adjustment import normalize_adjustment
from tools.chart_context import read_chart_context
from tools.lines import ColorInput, LINE_COMMAND, LineError, edit_horizontal_line, validate_line_fields
from tools.trend_lines import TREND_COMMAND, edit_trend_line
from tools.channels import CHANNEL_COMMAND, edit_channel
from tools.rectangles import RECTANGLE_COMMAND, edit_rectangle
from tools.fibonacci import FIBONACCI_COMMAND, edit_fibonacci
from tools.polylines import LabeledPoint, POLYLINE_COMMAND, edit_polyline, normalize_point_label
from tools.annotations import ANNOTATION_COMMAND, ANNOTATION_KINDS, edit_annotation
from tools.price_series import SERIES_COMMAND, edit_price_series
from tools.price_bands import BAND_COMMAND, edit_price_band
from tools.price_sticks import STICKS_COMMAND, edit_price_sticks

KINDS = {LINE_COMMAND: "horizontal_line", TREND_COMMAND: "trend_line",
         CHANNEL_COMMAND: "channel", RECTANGLE_COMMAND: "rectangle", FIBONACCI_COMMAND: "fibonacci_retracement",
         POLYLINE_COMMAND: "labeled_polyline", ANNOTATION_COMMAND: "annotation", SERIES_COMMAND: "series_line",
         BAND_COMMAND: "price_band", STICKS_COMMAND: "price_sticks"}


class ChartEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["horizontal_line", "trend_line", "channel", "rectangle", "fibonacci_retracement", "labeled_polyline", "text_annotation", "number_annotation", "icon_annotation", "series_line", "price_band", "price_sticks", "all_drawings"]
    action: Literal["create", "update", "delete"]
    object_id: str | None = Field(default=None, min_length=1, max_length=128,
                                 description="修改/删除使用当前观察中的 AI 稳定 ID；创建不填")
    name: str | None = Field(default=None, max_length=48)
    color: ColorInput | None = None
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    start_time: str | None = None
    end_time: str | None = None
    start_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    end_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    parallel_time: str | None = None
    parallel_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    lower_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    upper_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    show_midline: bool | None = Field(default=None, strict=True)
    show_fill: bool | None = Field(default=None, strict=True)
    points: list[LabeledPoint] | None = Field(default=None, min_length=2, max_length=8, description="仅用于创建标注折线，续改用单点字段")
    point_label: str | None = Field(default=None, min_length=1, max_length=16, description="更新该对象内的唯一点名，不按索引猜点")
    point_time: str | None = None
    point_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    anchor_time: str | None = Field(default=None, description="标注锚定的已加载K线日期/时间")
    anchor_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    annotation_text: str | None = Field(default=None, max_length=120, description="文字标注内容")
    annotation_value: float | None = Field(default=None, allow_inf_nan=False, strict=True, description="数值标注内容，可为负数或零")
    annotation_icon: Literal["arrow_up", "arrow_down", "diamond"] | None = Field(default=None, description="图标标注：向上箭头、向下箭头或菱形")
    ratios: list[Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]] | None = Field(default=None, min_length=1, max_length=16)
    result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$",
                                   description="run_chart_function 返回的结果引用；不能同时指定锚点、边界或比例。名称、颜色可另填。")
    ta_result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$",
                                      description="明确选择同一当前图的 SMA/EMA(close) 到 series_line，或 BBANDS(close) 三线到 price_band；不自动绘图。")
    candidate_result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$",
        description="通道/平台候选函数返回的只读引用；只有用户明确选定候选后才能用来创建图形")
    candidate_number: int | None = Field(default=None, strict=True, ge=1, le=5,
        description="用户选择的候选序号，从1开始；必须与 candidate_result_ref 同时提供")
    user_confirmed_candidate: bool | None = Field(default=None, strict=True,
        description="仅当用户明确确认该候选才填 true；候选函数不会自动绘图")


def edit_parameters(edit: ChartEdit) -> dict[str, Any]:
    fields = edit.model_dump(exclude_none=True)
    for key in ("kind", "action", "object_id"): fields.pop(key, None)
    supported = {"name", "color", "result_ref", "ta_result_ref", "candidate_result_ref", "candidate_number", "user_confirmed_candidate"} | {
        "horizontal_line": {"price"},
        "trend_line": {"start_time", "end_time", "start_price", "end_price"},
        "channel": {"start_time", "end_time", "start_price", "end_price", "parallel_time", "parallel_price", "show_midline"},
        "rectangle": {"start_time", "end_time", "lower_price", "upper_price", "show_fill"},
        "fibonacci_retracement": {"start_time", "end_time", "start_price", "end_price", "ratios"},
        "labeled_polyline": {"points", "point_label", "point_time", "point_price"},
        "text_annotation": {"anchor_time", "anchor_price", "annotation_text"},
        "number_annotation": {"anchor_time", "anchor_price", "annotation_value"},
        "icon_annotation": {"anchor_time", "anchor_price", "annotation_icon"},
        "series_line": set(),
        "price_band": set(),
        "price_sticks": set(),
        "all_drawings": set(),
    }[edit.kind]
    if fields.keys() - supported or edit.action == "delete" and fields:
        raise LineError("invalid_edit_fields", "参数不适用于该图形；删除只填类型、action，单对象删除另填 object_id。")
    if edit.kind == "labeled_polyline" and edit.action != "create" and (edit.result_ref is not None or edit.points is not None):
        raise LineError("polyline_replacement_not_supported", "标注折线续改使用 point_label 和 point_time / point_price；名称 / 颜色可另填，不重写整组。")
    if edit.result_ref is not None and (edit.kind not in {"fibonacci_retracement", "channel", "rectangle", "labeled_polyline", "series_line", "price_band", "price_sticks", *ANNOTATION_KINDS}
        or fields.keys() - {"result_ref", "name", "color", "show_midline", "show_fill"}):
        raise LineError("conflicting_function_parameters", "结果引用与直接锚点、边界或比例互斥；请修改参数后重新运行函数。")
    if edit.ta_result_ref is not None and (edit.kind not in {"series_line", "price_band"} or edit.action not in {"create", "update"}
        or fields.keys() - {"ta_result_ref", "name", "color"}):
        raise LineError("ta_result_not_drawable", "仅允许把明确选定的 SMA/EMA 单线或 BBANDS 三线结果创建或更新为对应图形。")
    candidate_fields = {"candidate_result_ref", "candidate_number", "user_confirmed_candidate"}
    if fields.keys() & candidate_fields and (edit.action != "create" or edit.kind not in {"channel", "rectangle"}
        or not candidate_fields <= fields.keys() or edit.user_confirmed_candidate is not True
        or fields.keys() - candidate_fields - {"name", "color", "show_midline", "show_fill"}):
        raise LineError("candidate_confirmation_required", "只有用户明确选定通道/平台候选及序号后才能创建；不能混用直接锚点或其他结果引用。")
    if edit.kind == "all_drawings" and (edit.action != "delete" or edit.object_id is not None):
        raise LineError("invalid_object_identity", "清空当前图只使用 all_drawings/delete，不指定单个对象 ID。")
    if edit.kind != "all_drawings" and (edit.action == "create" and edit.object_id is not None or edit.action != "create" and edit.object_id is None):
        raise LineError("invalid_object_identity", "创建不指定 object_id；修改/删除必须使用当前观察中的完整 AI ID。")
    _, name, color = validate_line_fields(name=edit.name, color=edit.color)
    if "name" in fields: fields["name"] = name
    if "color" in fields: fields["color"] = color
    if "point_label" in fields: fields["point_label"] = normalize_point_label(fields["point_label"])
    return fields


def snapshot_inventory(payload: dict) -> list[dict]:
    """Same canonical AI fields exposed by the browser collector; no manual objects."""
    inventory = []
    for cmd in payload.get("chartCommands", []):
        kind = cmd.get("kind") if cmd.get("type") == ANNOTATION_COMMAND and cmd.get("kind") in ANNOTATION_KINDS else KINDS.get(cmd.get("type"))
        if not kind: continue
        item = {"id": cmd.get("id"), "kind": kind, "origin": "ai", "name": cmd.get("label", ""),
                "color": cmd.get("color", "info"), "interval": cmd.get("interval", payload.get("interval"))}
        if kind == "horizontal_line": item["price"] = cmd["price"]
        elif kind == "rectangle":
            item.update({k: cmd[k] for k in ("start_time", "end_time", "lower_price", "upper_price", "show_fill")})
        elif kind == "labeled_polyline": item["points"] = deepcopy(cmd["points"])
        elif kind == "series_line": item.update(series_hash=cmd["series_hash"], bar_count=cmd["bar_count"])
        elif kind == "price_band": item.update(band_hash=cmd["band_hash"], bar_count=cmd["bar_count"])
        elif kind == "price_sticks": item.update(sticks_hash=cmd["sticks_hash"], bar_count=cmd["bar_count"])
        elif kind in ANNOTATION_KINDS:
            item.update(time=cmd["time"], price=cmd["price"])
            if kind == "text_annotation": item["text"] = cmd["text"]
            elif kind == "number_annotation": item["value"] = cmd["value"]
            else: item["icon"] = cmd["icon"]
        else:
            item["points"] = [cmd["from"], cmd["to"]] + ([cmd["parallel"]] if kind == "channel" else [])
            if kind == "channel": item["show_midline"] = cmd["show_midline"]
            if kind == "fibonacci_retracement":
                item.update(ratios=deepcopy(cmd["ratios"]), levels=deepcopy(cmd["levels"]))
        inventory.append(item)
    return inventory


def _unique_inventory(items: list[dict]) -> list[dict]:
    ids = [obj.get("id") for obj in items]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise LineError("ambiguous_drawing_id", "当前 AI 图形 ID 缺失或重复，不能安全准备修改。")
    return sorted(items, key=lambda obj: obj["id"])


def require_alignment(context: dict, payload: dict, token: str, symbol: str) -> None:
    from tools.chart_applications import confirmed_source
    from tools.chart_sources import require_confirmed_view_source
    require_confirmed_view_source(payload, context, token)
    if payload.get("drawing_guard") and not confirmed_source(payload, context, token):
        raise LineError("prepared_chart_not_applied", "来源仍是未应用的准备结果，不能把它当作已确认的当前图继续修改。")
    if context["state"] != "ready" or context["candle_selection"]["truncated"]:
        raise LineError("chart_edit_context_not_ready", "当前图未就绪或加载数据超过本阶段核对上限，未准备修改。")
    if (context.get("source_chart_session") != token or context["symbol"].casefold() != symbol.strip().casefold()
        or payload.get("symbol", "").casefold() != context["symbol"].casefold()
        or payload.get("interval") != context["interval"]
        or normalize_adjustment(context.get("adjust")) is None
        or normalize_adjustment(payload.get("adjust")) != normalize_adjustment(context.get("adjust"))):
        raise LineError("chart_snapshot_not_aligned", "来源快照与当前图的标的、周期、复权方式或引用不一致/未知，未使用旧图替代。")
    if context["interval"] == "minute" and (context.get("interval_value") is None
        or payload.get("interval_value") != context["interval_value"]):
        raise LineError("chart_snapshot_not_aligned", "分钟粒度未知或与来源快照不一致，未准备修改。")
    rows = next((c.get("rows", []) for c in payload["chartCommands"] if c.get("type") == "SET_CANDLES"), [])
    projected = [{k: r[k] for k in ("time", "open", "high", "low", "close", "volume")} for r in rows]
    observed = [{k: v for k, v in obj.items() if k not in {"context_editable", "edit_capability"}}
                for obj in context["drawings"] if obj.get("origin") == "ai"]
    if projected != context["candles"] or _unique_inventory(snapshot_inventory(payload)) != _unique_inventory(observed):
        raise LineError("chart_snapshot_not_aligned", "当前图的行情或 AI 图形已偏离来源快照，不能用旧快照覆盖当前状态。")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _public_edit_object(kind: str, obj: dict) -> dict:
    if kind not in {"series_line", "price_band", "price_sticks"}:
        return obj
    # Sequence values stay in the candidate snapshot. The host only needs a
    # stable identity, provenance and a checkable count/hash.
    fields = {
        "series_line": ("series_hash", "values"),
        "price_band": ("band_hash", "upper_values"),
        "price_sticks": ("sticks_hash", "start_values"),
    }
    digest_field, count_field = fields[kind]
    visible = ("type", "id", "interval", "bar_count", "row_hash", digest_field,
               "source", "upper_source", "lower_source", "start_source", "end_source",
               "condition", "label", "color")
    return {key: deepcopy(obj[key]) for key in visible if key in obj} | {
        "valid_bars": sum(value is not None for value in obj[count_field])}


def prepare_chart_edit(context_ref: str, expected_revision: int, chart_session: str, symbol: str,
                       request_id: str, edit: ChartEdit, *, publish=None) -> dict:
    """Prepare at most one candidate per observed revision; durable fail-closed retry journal.

    Publication is not live mutation. A browser may change after the last observation;
    candidate snapshots are blocked from ordinary rendering; the separate apply protocol performs live checks.
    """
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision <= 0:
        raise LineError("invalid_context_revision", "expected_revision 必须是读回的正整数观察版本。")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 or any(ord(c) < 32 for c in request_id):
        raise LineError("invalid_request_id", "request_id 必须为1至128字符，同一次请求重试保持不变。")
    params = edit_parameters(edit)
    context = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
    if context["revision"] != expected_revision:
        raise LineError("chart_context_revision_conflict", "当前图观察版本已变化，请重新读取并核对用户意图；未准备修改。")
    if edit.result_ref is not None:
        from tools.chart_functions import resolve_result
        params.update(resolve_result(edit.result_ref, context, edit.kind))
    if edit.ta_result_ref is not None:
        from tools.ta_functions import resolve_ta_drawing
        params.update(resolve_ta_drawing(edit.ta_result_ref, context, edit.kind))
    if edit.candidate_result_ref is not None:
        from tools.chart_functions import resolve_selected_candidate
        params.update(resolve_selected_candidate(edit.candidate_result_ref, context, edit.kind, edit.candidate_number))
    # A sequence's full values belong only in the candidate snapshot. The
    # journal/guard bind them by digest so preparation does not echo thousands
    # of prices back into the host conversation.
    guarded_params = {"digest_sha256": _hash(params)} if edit.kind in {
        "series_line", "price_band", "price_sticks"} else params
    identity = {"context_ref": context_ref, "expected_revision": expected_revision, "chart_session": chart_session,
                "symbol": symbol.strip().casefold(), "kind": edit.kind, "action": edit.action,
                "object_id": edit.object_id, "parameters": guarded_params}
    fingerprint = _hash(identity)
    directory = chart_service.RUNTIME_DIR / "edits" / str(chart_service.HOST_PROCESS_ID) / context_ref
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = directory / "prepare.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise LineError("chart_edit_busy", "该视图正在准备修改或存在未确认的中断锁，未并行发布；不要自动删除锁。") from None
    os.close(descriptor)
    try:
        journal = directory / "journal.json"
        try:
            saved = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else {"entries": []}
            entries = saved["entries"]
            if not isinstance(entries, list) or len(entries) > 64: raise ValueError("invalid journal")
            if any(not isinstance(e, dict) or not isinstance(e.get("request_id"), str)
                   or not isinstance(e.get("revision"), int) or isinstance(e["revision"], bool)
                   or e.get("status") not in {"preparing", "prepared", "outcome_unknown"}
                   or not isinstance(e.get("fingerprint"), str)
                   or e["status"] == "prepared" and not isinstance(e.get("result"), dict)
                   for e in entries): raise ValueError("invalid entries")
        except (OSError, ValueError, TypeError, KeyError):
            raise LineError("chart_edit_journal_invalid", "修改日志不可用，停止发布，未自动清空或重建历史。") from None
        previous = next((e for e in entries if e["request_id"] == request_id), None)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise LineError("request_conflict", "同一 request_id 的版本、对象或参数不同，请核对原请求。")
            if previous["status"] != "prepared":
                raise LineError("chart_edit_outcome_unknown", "该请求可能已发布但结果未确认，停止自动重试，避免重复图形。")
            return {**deepcopy(previous["result"]), "replayed": True}
        if any(e["revision"] == expected_revision for e in entries):
            raise LineError("chart_edit_revision_consumed", "该观察版本已有准备结果或未确认请求；不能从同一版本并行创建分支。")
        if len(entries) >= 64:
            raise LineError("chart_edit_capacity", "该视图修改日志已达本阶段上限，停止发布，未自动丢弃重试记录。")
        payload = chart_service.read_chart_snapshot(chart_session)
        if payload is None: raise LineError("chart_session_not_found", "来源快照不属于当前 DSH 实例或不存在。")
        try:
            require_alignment(context, payload, chart_session, symbol)
        except (KeyError, TypeError, AttributeError):
            raise LineError("chart_snapshot_not_aligned", "来源快照字段无法安全核对，未准备修改。") from None
        if edit.object_id is not None and not any(obj.get("origin") == "ai" and obj["kind"] == edit.kind
            and obj["id"] == edit.object_id for obj in context["drawings"]):
            raise LineError("drawing_not_editable", "目标不是当前观察中的该类型 AI 图形，手动/自动对象不允许修改。")
        if edit.object_id is not None and edit.kind in {"channel", "rectangle", "fibonacci_retracement", "labeled_polyline", "series_line", "price_band", "price_sticks", *ANNOTATION_KINDS}:
            target = next(obj for obj in context["drawings"] if obj.get("origin") == "ai" and obj["id"] == edit.object_id)
            if target.get("interval") != context["interval"]:
                raise LineError("drawing_interval_mismatch", "目标属于其他周期，当前周期不能改写或删除该对象；请明确切回其适用周期，不自动搬锚点。")
        editors = {"horizontal_line": (edit_horizontal_line, "line_id"), "trend_line": (edit_trend_line, "line_id"),
                          "channel": (edit_channel, "channel_id"), "rectangle": (edit_rectangle, "rectangle_id"),
                          "fibonacci_retracement": (edit_fibonacci, "fibonacci_id"),
                          "labeled_polyline": (edit_polyline, "polyline_id"),
                          "series_line": (edit_price_series, "series_id"),
                          "price_band": (edit_price_band, "band_id"),
                          "price_sticks": (edit_price_sticks, "sticks_id"),
                          "text_annotation": (edit_annotation, "annotation_id"),
                          "number_annotation": (edit_annotation, "annotation_id"),
                          "icon_annotation": (edit_annotation, "annotation_id")}
        if edit.kind == "all_drawings":
            targets = {item["id"] for item in context["drawings"] if item.get("origin") == "ai"
                       and item.get("interval") == context["interval"]}
            if not targets:
                raise LineError("drawing_not_found", "当前周期没有可清空的 AI 图形。")
            edited = deepcopy(payload)
            edited["chartCommands"] = [command for command in payload["chartCommands"]
                                       if not (command.get("type") in KINDS and command.get("id") in targets)]
            obj = {"kind": "all_drawings", "deleted_count": len(targets)}
        else:
            editor, id_key = editors[edit.kind]
            arguments = dict(params)
            if edit.kind in ANNOTATION_KINDS:
                arguments["kind"] = edit.kind
                arguments = {({"annotation_text": "text", "annotation_value": "value", "annotation_icon": "icon"}.get(k, k)): v
                             for k, v in arguments.items()}
            arguments.pop("result_ref", None)
            arguments.pop("ta_result_ref", None)
            for key in ("candidate_result_ref", "candidate_number", "user_confirmed_candidate"):
                arguments.pop(key, None)
            if edit.action == "create": arguments["request_id"] = context_ref + ":" + hashlib.sha256(request_id.encode()).hexdigest()
            else: arguments[id_key] = edit.object_id
            edited, obj = editor(payload, edit.action, **arguments)
        # The new drawing candidate has its own guarded application proof.
        # Do not misidentify it as the unchanged root browser-source token.
        edited.pop("view_source_guard", None)
        refreshed = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
        # Includes viewport/selection/settings, not only instrument and candle range.
        if refreshed["revision"] != expected_revision or any(refreshed[k] != context[k] for k in
            ("symbol", "interval", "interval_value", "adjust", "range_key", "candles", "visible_range", "drawings", "selection", "indicators")):
            raise LineError("chart_context_revision_conflict", "准备期间当前图发生变化，未发布修改。")
        guard = {"protocol": "prepared-only-v1", **identity, "conversation_id": context["conversation_id"],
                 "view_id": context["view_id"], "request_id": request_id, "requires_live_apply": True}
        edited.update(drawing_only=True, drawing_parent_session=chart_session, drawing_guard=guard)
        entry = {"request_id": request_id, "revision": expected_revision, "fingerprint": fingerprint, "status": "preparing"}
        entries.append(entry)
        chart_service._atomic_runtime_json(journal, {"entries": entries})
        try:
            token, _ = (publish or chart_service.publish_chart)(edited)
            result = {"ok": True, "scope": "guarded_preparation", "operation_status": "prepared",
                      "apply_status": "not_requested", "render_verified": False, "replayed": False,
                      "context_ref": context_ref, "expected_revision": expected_revision,
                      "conversation_id": context["conversation_id"], "view_id": context["view_id"],
                      "chart_session": token, "parent_chart_session": chart_session, "symbol": payload["symbol"],
                      "interval": payload["interval"], "request_id": request_id, "edit": {"kind": edit.kind, "action": edit.action},
                      "object": _public_edit_object(edit.kind, obj), "drawing_guard": guard,
                      "source_snapshot_alignment": "verified_for_preparation"}
            entry.update(status="prepared", result=result)
            chart_service._atomic_runtime_json(journal, {"entries": entries})
        except Exception:
            entry.pop("result", None); entry["status"] = "outcome_unknown"
            try: chart_service._atomic_runtime_json(journal, {"entries": entries})
            except Exception: pass  # Durable preparing entry already prevents a duplicate retry.
            raise LineError("chart_edit_outcome_unknown", "准备发布或记录失败，当前网页未修改；发布结果可能不确定，停止自动重试。") from None
        return result
    finally:
        lock.unlink()
