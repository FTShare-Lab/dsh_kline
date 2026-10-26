"""Read live browser observations by capability reference; never infer a current view."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
import re
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import chart_service
from core.rows import validate_rows, RowsValidationError
from tools.lines import LineError
from tools.drawing_feedback import sanitize_drawing_feedback
from tools.drawing_interaction import drawing_capabilities
from tools.trend_lines import CN_TZ
from tools.chart_measurements import measure_chart_region
from tools.channel_preview import preview_channel
from tools.chart_source_status import sanitize_source_status


def sanitize_data_provenance(state: dict[str, Any]) -> dict[str, Any]:
    """Whitelist the additive observation metadata, including old-client unknowns."""
    ready = state.get("state") == "ready"
    intervals = ("minute", "day", "week", "month", "quarter", "year")
    source = state.get("source_interval") if ready and state.get("source_interval") in intervals else None
    display = state.get("interval") if ready and state.get("interval") in intervals else None
    raw = state.get("data_provenance") if ready else None
    raw = raw if isinstance(raw, dict) else {}
    provider = raw.get("provider")
    if provider not in ("ftshare", "eastmoney_free", "tencent_free", "builtin_free", "external"):
        provider = "unknown"
    transformation, aggregation = "unknown", None
    if source and source == display and raw.get("transformation") == "none":
        transformation = "none"
    if source == "day" and display in ("week", "month", "quarter", "year") and raw.get("transformation") == "local_aggregation":
        details = raw.get("aggregation")
        zone = details.get("timezone") if isinstance(details, dict) else None
        if isinstance(zone, str) and len(zone) <= 64 and re.fullmatch(r"[A-Za-z_+-]+(?:/[A-Za-z0-9_+-]+){0,2}", zone):
            try:
                ZoneInfo(zone)
                transformation = "local_aggregation"
                aggregation = {"timezone": zone, "bucket": "calendar_week_monday" if display == "week" else "calendar_" + display,
                    "ohlcv": "first_open_max_high_min_low_last_close_sum_volume", "timestamp": "last_source_bar",
                    "order": "aggregate_before_range_crop", "completeness": "not_verified"}
            except (ZoneInfoNotFoundError, ValueError):
                pass
    return {"scope": "browser_input_to_display", "provider": provider, "source_interval": source,
            "display_interval": display, "transformation": transformation, "aggregation": aggregation}


def _time_label(value: int | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        instant = datetime.fromtimestamp(value, CN_TZ)
        return {"time": value, "date": instant.date().isoformat(), "iso": instant.isoformat(timespec="seconds")}
    except (ValueError, OverflowError, OSError):
        return {"time": value, "date": None, "iso": None}


def read_chart_context(context_ref: str, *, candle_scope: str = "visible", limit: int = 200,
                       region_start_time: str | None = None, region_end_time: str | None = None,
                       channel_candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(context_ref, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", context_ref):
        raise LineError("context_ref_required", "请使用当前对话运行时上下文提供的 context_ref，不要使用 chart_session 或猜测其他对话。")
    if candle_scope not in {"visible", "loaded", "none"} or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4000:
        raise LineError("invalid_context_arguments", "candle_scope 请选择 visible、loaded 或 none；limit 为1至4000整数。")
    if (region_start_time is None) != (region_end_time is None):
        raise LineError("invalid_measurement_range", "测量需同时指定起止已有K线时间；不自动猜测另一个端点。")
    path = chart_service.RUNTIME_DIR / "views" / str(chart_service.HOST_PROCESS_ID) / f"{context_ref}.json"
    try:
        if path.stat().st_size > chart_service.MAX_REQUEST_BYTES: raise ValueError("too large")
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise LineError("chart_context_unavailable", "当前图表上下文不可用；请打开该对话的图表。未使用旧快照或其他对话代替。") from None
    if not isinstance(saved, dict) or saved.get("ok") is not True or saved.get("context_ref") != context_ref or saved.get("host_process_id") != chart_service.HOST_PROCESS_ID:
        raise LineError("chart_context_unavailable", "上下文不属于当前 DSH 实例。")
    if (not isinstance(saved.get("revision"), int) or isinstance(saved["revision"], bool) or saved["revision"] <= 0
        or not isinstance(saved.get("conversation_id"), str) or not saved["conversation_id"]
        or not isinstance(saved.get("view_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", saved["view_id"])):
        raise LineError("invalid_chart_context", "图表视图身份或观察版本无效。")
    observed = saved.get("observed_at_ms")
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed):
        raise LineError("invalid_chart_context", "图表观察时间无效。")
    age = time.time() * 1000 - observed
    if age > 30_000 or age < -5000:
        raise LineError("chart_context_stale", "图表上下文已过期或时钟异常，请等待网页重新上报；未回退到旧行情快照。")
    if saved.get("active") is not True: raise LineError("chart_view_inactive", "该图表视图已关闭或未活动。")
    if saved.get("ambiguous") is not False: raise LineError("ambiguous_chart_views", "该对话存在多个活动视图，不能确定当前图；请保留一个活动图表视图。")
    state = saved.get("state")
    if not isinstance(state, dict) or state.get("schema_version") != 1 or state.get("state") not in {"ready", "empty", "not_chart", "loading", "error"}:
        raise LineError("invalid_chart_context", "图表上下文格式无效。")
    try:
        raw = state.get("candles", [])
        if not isinstance(raw, list) or len(raw) > 12000: raise ValueError("rows")
        if state["state"] == "ready":
            if any(any(isinstance(r.get(k), bool) or not isinstance(r.get(k), (int, float)) or not math.isfinite(r[k])
                       for k in ("time", "open", "high", "low", "close", "volume"))
                   or not isinstance(r["time"], int) or r["time"] <= 0 for r in raw): raise ValueError("row types")
            rows = validate_rows([{k: r[k] for k in ("time", "open", "high", "low", "close", "volume")} for r in raw], min_len=1)
        else: rows = []
        # The browser's clock/order must already be canonical. Do not repair a stale/malformed report.
        if rows and [r["time"] for r in rows] != [r.get("time") for r in raw]: raise ValueError("clock")
        if len(rows) != len(raw) and state["state"] == "ready": raise ValueError("rows")
        viewport = state.get("visible_range", {})
        visible: list[dict] = []
        if state["state"] == "ready" and viewport.get("available") is True:
            start, end = viewport["index_from"], viewport["index_to_exclusive"]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end)) or not 0 <= start <= end <= len(rows): raise ValueError("viewport")
            visible = rows[start:end]
            view_range = {"available": True, "index_from": start, "index_to_exclusive": end,
                          "count": len(visible), "start_time": visible[0]["time"] if visible else None,
                          "end_time": visible[-1]["time"] if visible else None}
        else: view_range = {"available": False, "reason": "not_reported"}
        objects = state.get("drawings", []) if state["state"] == "ready" else []
        if not isinstance(objects, list) or len(objects) > 512: raise ValueError("drawings")
        drawing_keys = {"id", "kind", "origin", "name", "color", "interval", "price", "time", "text", "value", "icon", "start_time", "end_time", "lower_price", "upper_price", "show_fill", "show_midline", "series_hash", "band_hash", "sticks_hash", "bar_count"}
        drawings = []
        for obj in objects:
            item = {k: deepcopy(obj[k]) for k in drawing_keys if k in obj}
            if obj.get("kind") == "labeled_polyline":
                from tools.polylines import validate_stored_points
                item["points"] = validate_stored_points(obj["points"])
            elif obj.get("kind") in {"text_annotation", "number_annotation", "icon_annotation"}:
                from tools.annotations import validate_annotation
                annotation = validate_annotation({"type": "DRAW_AGENT_ANNOTATION", "kind": obj["kind"], "id": obj.get("id"),
                    "interval": obj.get("interval"), "label": obj.get("name", ""), "color": obj.get("color", "info"),
                    "time": obj.get("time"), "price": obj.get("price"), "text": obj.get("text"), "value": obj.get("value"),
                    "icon": obj.get("icon")})
                item.update(time=annotation["time"], price=annotation["price"])
                if obj["kind"] == "text_annotation": item["text"] = annotation["text"]
                elif obj["kind"] == "number_annotation": item["value"] = annotation["value"]
                else: item["icon"] = annotation["icon"]
            elif "points" in obj: item["points"] = [{k: p[k] for k in ("time", "price")} for p in obj["points"][:8]]
            if obj.get("kind") == "fibonacci_retracement":
                from tools.fibonacci import validate_ratios
                item["ratios"] = validate_ratios(obj["ratios"])
                item["levels"] = [{"ratio": p["ratio"], "price": p["price"]} for p in obj["levels"][:16]]
            item.update(context_editable=False, edit_capability="source_snapshot_only" if obj.get("origin") == "ai" else "read_only")
            drawings.append(item)
        selection = state.get("selection")
        if selection:
            keys = ("kind", "time") if selection.get("kind") == "candle" else ("kind", "start_time", "end_time")
            selection = {k: selection[k] for k in keys}
    except (ValueError, TypeError, KeyError, AttributeError, RowsValidationError):
        raise LineError("invalid_chart_context", "图表数据或可见范围无效，未把已加载范围冒充为屏幕可见范围。") from None
    selected = visible if candle_scope == "visible" else rows if candle_scope == "loaded" else []
    result = {k: deepcopy(state.get(k)) for k in ("symbol", "name", "interval", "interval_value", "interval_value_status", "source_interval",
                                                "ui_interval", "display_volume_unit", "range_key", "adjust", "active_page", "indicators", "data_status")}
    source = state.get("source_chart_session")
    result["data_provenance"] = sanitize_data_provenance(state)
    result.update(ok=True, context_ref=context_ref, conversation_id=saved.get("conversation_id"), view_id=saved.get("view_id"),
                  guarded_apply_supported=saved.get("guarded_apply_supported") is True,
                  drawing_workflow="prepare_then_apply" if saved.get("guarded_apply_supported") is True else "observation_only",
                  revision=saved.get("revision"), observed_at_ms=observed, age_ms=max(0, int(age)), state=state["state"],
                  observation_source="live_browser_report", time_unit="unix_seconds", render_verified=False, live_view_editable=False,
                  source_chart_session=source if isinstance(source, str) and re.fullmatch(r"[A-Za-z0-9_-]{32}", source) else None,
                  source_snapshot_alignment="not_verified", loaded_range={"count":len(rows), "start_time": rows[0]["time"] if rows else None,
                    "end_time":rows[-1]["time"] if rows else None}, visible_range=view_range,
                  drawings=drawings, drawings_scope="stored_objects_for_active_instrument", selection=selection,
                  drawing_feedback=sanitize_drawing_feedback(saved.get("drawing_feedback"), [d for d in drawings if d.get("origin") == "ai"]),
                  selection_status=state.get("selection_status", "none"), selected_drawing_id=None, selected_drawing_status="not_supported",
                  drawing_capabilities=drawing_capabilities(),
                  candles=selected[-limit:], candle_selection={"scope":candle_scope,"total":len(selected),"returned":min(limit,len(selected)),
                    "truncated":len(selected)>limit,"order":"ascending","sample":"last_limit"})
    result["source_status"] = sanitize_source_status(saved.get("source_status"))
    # Keep raw candles untouched for strict source-alignment checks. Supply a
    # separate deterministic display map so the host need not guess dates.
    result["time_display"] = {"timezone": "UTC+08:00", "basis": "same_as_anchor_date_resolution",
                              "loaded_start": _time_label(rows[0]["time"] if rows else None),
                              "loaded_end": _time_label(rows[-1]["time"] if rows else None),
                              "visible_start": _time_label(visible[0]["time"] if visible else None),
                              "visible_end": _time_label(visible[-1]["time"] if visible else None),
                              "sample_labels": [_time_label(row["time"]) for row in selected[-limit:]]}
    if region_start_time is not None:
        if state["state"] != "ready":
            raise LineError("chart_measurement_not_ready", "当前图未就绪，不能使用旧K线测量区域。")
        result["region_measurements"] = measure_chart_region(rows, result["interval"], region_start_time, region_end_time)
    if channel_candidate is not None:
        if state["state"] != "ready":
            raise LineError("chart_measurement_not_ready", "当前图未就绪，不能使用旧K线预览通道。")
        result["channel_preview"] = preview_channel(rows, result["interval"], **channel_candidate)
    return result
