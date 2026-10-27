"""Versioned deterministic functions on an explicitly aligned live-chart snapshot.

Results are host/view scoped, immutable, bounded, and never apply a drawing.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from time import perf_counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import chart_service
from core.adjustment import normalize_adjustment
from tools.chart_context import read_chart_context
from tools.channels import CHANNEL_COMMAND, edit_channel
from tools.fibonacci import DEFAULT_RATIOS, FIBONACCI_COMMAND, edit_fibonacci
from tools.lines import LineError
from tools.rectangles import RECTANGLE_COMMAND, edit_rectangle
from tools.polylines import LabeledPoint, POLYLINE_COMMAND, edit_polyline
from tools.pivots import confirmed_pivots
from tools.channel_candidates import channel_candidates
from tools.range_candidates import DEFAULT_WINDOW_SIZES, range_candidates
from tools.regression_channels import regression_channel
from tools.price_series import PriceCondition, PriceSource, SERIES_COMMAND, calculate_price_series, edit_price_series
from tools.annotations import edit_annotation, _validate_content
from tools.price_bands import BAND_COMMAND, calculate_price_band, edit_price_band
from tools.price_sticks import STICKS_COMMAND, calculate_price_sticks, edit_price_sticks
from tools.trend_lines import resolve_anchor_time

FunctionName = Literal["fibonacci_retracement", "parallel_channel", "range_box", "labeled_polyline", "pivot_candidates", "regression_channel", "channel_candidates", "range_candidates", "price_series_line", "conditional_annotation", "price_band", "price_sticks"]
VERSION = "1"
ANALYSIS_ONLY = {"pivot_candidates", "regression_channel", "channel_candidates", "range_candidates"}


def _version(function):
    return "3" if function == "channel_candidates" else VERSION


FUNCTIONS = {
    "fibonacci_retracement": ("fibonacci_retracement", edit_fibonacci,
        ("start_time", "start_price", "end_time", "end_price"), ("ratios",)),
    "parallel_channel": ("channel", edit_channel,
        ("start_time", "start_price", "end_time", "end_price", "parallel_time", "parallel_price"), ()),
    "range_box": ("rectangle", edit_rectangle,
        ("start_time", "end_time", "lower_price", "upper_price"), ()),
    "labeled_polyline": ("labeled_polyline", edit_polyline, ("points",), ()),
    "pivot_candidates": ("pivot_candidates", None, (), ("left_bars", "right_bars", "mode", "limit")),
    "regression_channel": ("regression_channel", None, ("start_time", "end_time"), ("multiplier",)),
    "channel_candidates": ("channel_candidates", None, (),
        ("direction", "scope", "lookback_bars", "left_bars", "right_bars", "min_span_bars", "max_candidates")),
    "range_candidates": ("range_candidates", None, (), ("window_sizes", "max_candidates")),
    "price_series_line": ("series_line", edit_price_series, ("value_source",), ("condition",)),
    "conditional_annotation": ("annotation_kind_parameter", edit_annotation,
        ("annotation_kind", "anchor_source", "condition"), ("annotation_text", "annotation_value", "annotation_icon")),
    "price_band": ("price_band", edit_price_band, ("upper_source", "lower_source"), ("condition",)),
    "price_sticks": ("price_sticks", edit_price_sticks, ("start_source", "end_source"), ("condition",)),
}


class ChartFunctionParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str | None = None
    end_time: str | None = None
    start_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    end_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    parallel_time: str | None = None
    parallel_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    lower_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    upper_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    ratios: list[Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]] | None = Field(default=None, min_length=1, max_length=16)
    price_scale: Literal["linear"] = "linear"
    points: list[LabeledPoint] | None = Field(default=None, min_length=2, max_length=8,
                                           description="时间递增、组内标签唯一的2至8个明确锚点；不是自动识浪")
    left_bars: int | None = Field(default=None, strict=True, ge=1, le=20, description="左侧比较K线数；默认2")
    right_bars: int | None = Field(default=None, strict=True, ge=1, le=20, description="右侧确认K线数；默认2")
    mode: Literal["high", "low", "both"] | None = Field(default=None, description="返回局部高点、低点或两者；默认both")
    limit: int | None = Field(default=None, strict=True, ge=1, le=50, description="最多返回最新候选数；默认20")
    multiplier: float | None = Field(default=None, strict=True, ge=0.5, le=5, allow_inf_nan=False,
                                     description="回归上下轨距离倍数；默认2，乘以回归残差总体RMS")
    direction: Literal["ascending", "descending", "both"] | None = Field(default=None, description="通道候选方向；默认both")
    scope: Literal["current", "historical"] | None = Field(default=None, description="通道候选范围；默认current，仅历史回看时选historical")
    lookback_bars: int | None = Field(default=None, strict=True, ge=30, le=300, description="最近已加载K线根数；默认120")
    min_span_bars: int | None = Field(default=None, strict=True, ge=10, le=100, description="两基准锚点最小间隔；默认12")
    max_candidates: int | None = Field(default=None, strict=True, ge=1, le=5, description="最多返回候选数；默认3")
    window_sizes: list[Annotated[int, Field(strict=True, ge=16, le=120)]] | None = Field(
        default=None, min_length=1, max_length=8, description="平台候选窗口根数；默认20、30、40、60；不得重复")
    value_source: PriceSource | None = Field(default=None, description="序列线取值：OHLC、SMA 或 EMA(close, 2至200根)")
    condition: PriceCondition | None = Field(default=None, description="可选价格条件；不接受宿主传入行情数组或代码")
    anchor_source: PriceSource | None = Field(default=None, description="条件标注所用价格锚点，取最新一根满足条件的已加载K线")
    annotation_kind: Literal["text_annotation", "number_annotation", "icon_annotation"] | None = None
    annotation_text: str | None = Field(default=None, min_length=1, max_length=120)
    annotation_value: float | None = Field(default=None, strict=True, allow_inf_nan=False)
    annotation_icon: Literal["arrow_up", "arrow_down", "diamond"] | None = None
    upper_source: PriceSource | None = Field(default=None, description="带状填充上边界价格来源")
    lower_source: PriceSource | None = Field(default=None, description="带状填充下边界价格来源")
    start_source: PriceSource | None = Field(default=None, description="逐K线柱线起点价格来源")
    end_source: PriceSource | None = Field(default=None, description="逐K线柱线终点价格来源")


def list_functions():
    schema = ChartFunctionParameters.model_json_schema()
    properties = schema["properties"]
    return {"schema_version": 1, "functions": [
        {"name": name, "version": _version(name), "drawing_kind": None if name in ANALYSIS_ONLY else kind, "required_parameters": list(required),
         "result_usage": "analysis_only" if name in ANALYSIS_ONLY else "guarded_drawing",
         "optional_parameters": list(optional) + ([] if name in ANALYSIS_ONLY else ["price_scale"]),
         "defaults": ({"left_bars": 2, "right_bars": 2, "mode": "both", "limit": 20}
                      if name == "pivot_candidates" else
                      {"multiplier": 2.0} if name == "regression_channel" else
                      {"direction": "both", "scope": "current", "lookback_bars": 120, "left_bars": 2, "right_bars": 2,
                       "min_span_bars": 12, "max_candidates": 3} if name == "channel_candidates" else
                      {"window_sizes": list(DEFAULT_WINDOW_SIZES), "max_candidates": 3} if name == "range_candidates" else
                      {"condition": None, "price_scale": "linear"} if name == "price_series_line" else
                      {"selection": "latest_match", "price_scale": "linear"} if name == "conditional_annotation" else
                      {"condition": None, "price_scale": "linear"} if name in {"price_band", "price_sticks"} else
                      {"price_scale": "linear", **({"ratios": list(DEFAULT_RATIOS)} if name == "fibonacci_retracement" else {})}),
         "limits": {"loaded_bars": 4000, "automatic_anchor_selection": False,
                    "price_scale": "linear", "time": "exact_loaded_bar", "applies_chart": False,
                    **({"window_bars": [1, 20], "candidate_limit": [1, 50],
                        "rule": "strict_local_extremum", "ties": "equal_neighbor_is_not_a_pivot",
                        "requires_complete_right_window": True} if name == "pivot_candidates" else
                       {"minimum_range_bars": 10, "maximum_range_bars": 4000,
                        "price_source": "close", "x_axis": "loaded_candle_index",
                        "boundary_rule": "ols_close_plus_minus_multiplier_times_population_rms_residual",
                        "automatic_anchor_selection": False} if name == "regression_channel" else
                       {"lookback_bars": [30, 300], "pivot_window_bars": [1, 20],
                        "minimum_anchor_span_bars": [10, 100], "candidate_limit": [1, 5],
                        "anchor_rule": "two_confirmed_same_side_pivots_plus_widest_interior_opposite_pivot",
                        "automatic_anchor_selection": "candidates_only_not_drawing",
                        "current_end_age_bars": 8, "max_width_fraction_of_median_close": 0.12,
                        "max_width_to_base_move": 2.0,
                        "max_outside_bar_fraction": 0.20,
                        "same_family_slope_tolerance": 0.10,
                        "same_family_width_tolerance": 0.10,
                        "current_post_end_check": "arithmetic_extension_to_latest_not_breakout_confirmation",
                        "requires_human_review": True} if name == "channel_candidates" else
                       {"window_size_bars": [16, 120], "candidate_limit": [1, 5],
                        "end_policy": "latest_loaded_bar_only",
                        "boundary_rule": "full_window_max_high_min_low",
                        "requires_separated_touches_on_both_edges": True,
                        "checks_full_and_recent_close_drift": True,
                        "automatic_anchor_selection": "candidates_only_not_drawing",
                        "requires_human_review": True} if name == "range_candidates" else
                       {"maximum_series_objects": 8, "value_sources": ["open", "high", "low", "close", "sma_close", "ema_close"],
                        "sma_period": [2, 200], "ema_period": [2, 200], "conditions": ["gt", "gte", "lt", "lte"],
                        "zero_matches": "do_not_draw", "pane": "candle"} if name == "price_series_line" else
                       {"selection": "latest_matched_loaded_bar_only", "maximum_annotations": 80,
                        "value_sources": ["open", "high", "low", "close", "sma_close", "ema_close"],
                        "conditions": ["gt", "gte", "lt", "lte"], "zero_matches": "do_not_draw",
                        "content_rule": "exactly_one_matching_annotation_text_value_or_icon"}
                        if name == "conditional_annotation" else
                       {"maximum_band_objects": 4, "boundary_rule": "upper_strictly_above_lower_on_every_matched_bar",
                        "zero_matches": "do_not_draw", "pane": "candle", "conditions": ["gt", "gte", "lt", "lte"]}
                        if name == "price_band" else
                       {"maximum_stick_objects": 4, "zero_length": "omitted", "pane": "candle",
                        "value_sources": ["open", "high", "low", "close", "sma_close", "ema_close"],
                        "conditions": ["gt", "gte", "lt", "lte"]} if name == "price_sticks" else {})},
         "parameter_schema": {"type": "object", "additionalProperties": False, "required": list(required),
                              "properties": {key: properties[key] for key in
                                             (*required, *optional, *(() if name in ANALYSIS_ONLY else ("price_scale",)))},
                              **({"$defs": schema["$defs"]} if name in {"labeled_polyline", "price_series_line", "conditional_annotation", "price_band", "price_sticks"} else {})}}
        for name, (kind, _, required, optional) in FUNCTIONS.items()],
        "workflow": "get_chart_context -> run_chart_function -> prepare_chart_edit(result_ref) -> apply_chart_edit -> get_chart_edit_status",
        "analysis_only_workflow": "get_chart_context -> run_chart_function(pivot_candidates, regression_channel, channel_candidates or range_candidates); inspect analysis. Only after explicit user selection, channel/range candidates may use prepare_chart_edit(candidate_result_ref, candidate_number, user_confirmed_candidate=true); historical anchors do not prove a current breakout",
        "pattern_quality_verified": False}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _data_identity(context):
    return {key: context.get(key) for key in ("symbol", "interval", "interval_value", "data_provenance")} | {
        "adjust": normalize_adjustment(context.get("adjust")), "candles": context["candles"]}


def _binding(context):
    return {"host_process_id": chart_service.HOST_PROCESS_ID,
            **{k: context[k] for k in ("context_ref", "conversation_id", "view_id")},
            "data_fingerprint": _hash(_data_identity(context))}


def _directory(context):
    return chart_service.RUNTIME_DIR / "functions" / str(chart_service.HOST_PROCESS_ID) / context["context_ref"]


def _calculate(payload, function, parameters, *, candles=None):
    if function not in FUNCTIONS:
        raise LineError("unknown_chart_function", "未知函数，请查询 list_chart_functions；不执行任意公式或代码。")
    kind, editor, required, optional = FUNCTIONS[function]
    values = parameters.model_dump(exclude_none=True)
    values.pop("price_scale")
    if values.keys() - set(required + optional):
        raise LineError("invalid_function_parameters", "参数不适用于该函数。")
    if any(k not in values for k in required):
        raise LineError("missing_anchor", "缺少明确锚点或边界；请向用户澄清，不自动选择。")
    if function == "pivot_candidates":
        rows = candles
        if not isinstance(rows, list):
            raise LineError("pivot_data_unavailable", "当前图没有可读取的已加载K线，未补取行情。")
        result = confirmed_pivots(rows, left_bars=values.get("left_bars", 2),
                                  right_bars=values.get("right_bars", 2), mode=values.get("mode", "both"),
                                  limit=values.get("limit", 20))
        normalized = {"left_bars": result["left_bars"], "right_bars": result["right_bars"],
                      "mode": result["mode"], "limit": result["limit"]}
        return {"function": function, "function_version": VERSION, "kind": kind,
                "result_usage": "analysis_only", "parameters": normalized, "price_scale": "linear",
                "summary": {k: deepcopy(v) for k, v in result.items() if k not in normalized}}
    if function == "regression_channel":
        start = resolve_anchor_time(payload, values["start_time"])
        end = resolve_anchor_time(payload, values["end_time"])
        result = regression_channel(candles, start_time=start, end_time=end,
                                    multiplier=values.get("multiplier", 2.0))
        normalized = {"start_time": str(start), "end_time": str(end), "multiplier": result["multiplier"]}
        return {"function": function, "function_version": VERSION, "kind": kind,
                "result_usage": "analysis_only", "parameters": normalized, "price_scale": "linear",
                "summary": result}
    if function == "channel_candidates":
        if not isinstance(candles, list):
            raise LineError("channel_candidate_data_unavailable", "当前图没有可读取的已加载K线，未补取行情。")
        result = channel_candidates(candles, direction=values.get("direction", "both"),
                                    scope=values.get("scope", "current"),
                                    lookback_bars=values.get("lookback_bars", 120),
                                    left_bars=values.get("left_bars", 2),
                                    right_bars=values.get("right_bars", 2),
                                    min_span_bars=values.get("min_span_bars", 12),
                                    limit=values.get("max_candidates", 3))
        normalized = {"direction": result["direction"], "scope": result["scope"],
                      "lookback_bars": result["lookback_bars"],
                      "left_bars": result["left_bars"], "right_bars": result["right_bars"],
                      "min_span_bars": result["min_span_bars"], "max_candidates": values.get("max_candidates", 3)}
        return {"function": function, "function_version": _version(function), "kind": kind,
                "result_usage": "analysis_only", "parameters": normalized, "price_scale": "linear",
                "summary": result}
    if function == "range_candidates":
        if not isinstance(candles, list):
            raise LineError("range_candidate_data_unavailable", "当前图没有可读取的已加载K线，未补取行情。")
        result = range_candidates(candles, window_sizes=values.get("window_sizes", DEFAULT_WINDOW_SIZES),
                                  limit=values.get("max_candidates", 3))
        normalized = {"window_sizes": result["window_sizes"],
                      "max_candidates": values.get("max_candidates", 3)}
        return {"function": function, "function_version": _version(function), "kind": kind,
                "result_usage": "analysis_only", "parameters": normalized, "price_scale": "linear",
                "summary": result}
    if function == "price_series_line":
        if not isinstance(candles, list) or values.get("value_source") is None:
            raise LineError("price_series_data_unavailable", "当前图没有可读取的已加载K线，未补取行情。")
        source = PriceSource.model_validate(values["value_source"])
        condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculation = calculate_price_series(candles, source, condition)
        return {"function": function, "function_version": _version(function), "kind": kind,
                "result_usage": "guarded_drawing", "parameters": {"value_source": source.model_dump(exclude_none=True),
                    "condition": condition.model_dump(exclude_none=True) if condition else None},
                "price_scale": "linear", "summary": calculation["summary"],
                "render_values": calculation["values"]}
    if function == "conditional_annotation":
        annotation_kind = values["annotation_kind"]
        source = PriceSource.model_validate(values["anchor_source"])
        condition = PriceCondition.model_validate(values["condition"])
        content_key = {"text_annotation": "annotation_text", "number_annotation": "annotation_value",
                       "icon_annotation": "annotation_icon"}[annotation_kind]
        if content_key not in values or set(values) & {"annotation_text", "annotation_value", "annotation_icon"} != {content_key}:
            raise LineError("invalid_conditional_annotation_content", "请只填写对应标注类型的一项文字、数值或图标内容。")
        content_text, content_value = _validate_content(annotation_kind, values.get("annotation_text"),
                                                         values.get("annotation_value"), values.get("annotation_icon"))
        if annotation_kind == "text_annotation": values[content_key] = content_text
        elif annotation_kind == "number_annotation": values[content_key] = content_value
        calculation = calculate_price_series(candles, source, condition)
        matches = [index for index, value in enumerate(calculation["values"]) if value is not None]
        drawing_parameters = None
        if matches:
            index = matches[-1]
            drawing_parameters = {"anchor_time": str(candles[index]["time"]),
                                  "anchor_price": calculation["values"][index], content_key: values[content_key]}
            # Reuse the existing annotation editor for content and exact-bar validation.
            editor_arguments = {"kind": annotation_kind, "anchor_time": drawing_parameters["anchor_time"],
                                "anchor_price": drawing_parameters["anchor_price"],
                                {"annotation_text": "text", "annotation_value": "value",
                                 "annotation_icon": "icon"}[content_key]: values[content_key]}
            _, annotation = edit_annotation(payload, "create", **editor_arguments)
            drawing_parameters["anchor_price"] = annotation["price"]
        return {"function": function, "function_version": VERSION, "kind": annotation_kind,
                "result_usage": "guarded_drawing", "parameters": {"annotation_kind": annotation_kind,
                    "anchor_source": source.model_dump(exclude_none=True),
                    "condition": condition.model_dump(exclude_none=True), content_key: values[content_key]},
                "drawing_parameters": drawing_parameters, "price_scale": "linear",
                "summary": {**calculation["summary"], "selection_rule": "latest_matched_loaded_bar_only",
                    "selected_time": drawing_parameters["anchor_time"] if drawing_parameters else None,
                    "selected_price": drawing_parameters["anchor_price"] if drawing_parameters else None,
                    "bars_ago": len(candles) - 1 - matches[-1] if matches else None}}
    if function == "price_band":
        upper_source = PriceSource.model_validate(values["upper_source"])
        lower_source = PriceSource.model_validate(values["lower_source"])
        condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculated = calculate_price_band(candles, upper_source, lower_source, condition)
        return {"function": function, "function_version": VERSION, "kind": kind,
                "result_usage": "guarded_drawing", "parameters": {
                    "upper_source": upper_source.model_dump(exclude_none=True),
                    "lower_source": lower_source.model_dump(exclude_none=True),
                    "condition": condition.model_dump(exclude_none=True) if condition else None},
                "price_scale": "linear", "summary": calculated["summary"],
                "render_upper_values": calculated["upper_values"],
                "render_lower_values": calculated["lower_values"]}
    if function == "price_sticks":
        start_source = PriceSource.model_validate(values["start_source"])
        end_source = PriceSource.model_validate(values["end_source"])
        condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculated = calculate_price_sticks(candles, start_source, end_source, condition)
        return {"function": function, "function_version": VERSION, "kind": kind,
                "result_usage": "guarded_drawing", "parameters": {
                    "start_source": start_source.model_dump(exclude_none=True),
                    "end_source": end_source.model_dump(exclude_none=True),
                    "condition": condition.model_dump(exclude_none=True) if condition else None},
                "price_scale": "linear", "summary": calculated["summary"],
                "render_start_values": calculated["start_values"],
                "render_end_values": calculated["end_values"]}
    # Editors already implement all geometry/anchor validation. Work only on a
    # temporary copy; never publish their temporary IDs or duplicate the math.
    command = {"channel": CHANNEL_COMMAND, "rectangle": RECTANGLE_COMMAND, "fibonacci_retracement": FIBONACCI_COMMAND,
               "labeled_polyline": POLYLINE_COMMAND}[kind]
    calculation_input = {**payload, "chartCommands": [c for c in payload["chartCommands"] if c.get("type") != command]}
    _, obj = editor(calculation_input, "create", **values)
    normalized = {}
    if kind == "labeled_polyline":
        normalized = {"points": [{**p, "time": str(p["time"])} for p in obj["points"]]}
        summary = {"points": deepcopy(obj["points"]), "point_count": len(obj["points"]), "automatic_wave_recognition": False}
    elif kind == "rectangle":
        normalized = {k: str(obj[k]) if k.endswith("_time") else obj[k] for k in required}
        summary = {k: obj[k] for k in required}
    else:
        for prefix, key in (("start", "from"), ("end", "to"), ("parallel", "parallel")):
            if key in obj:
                normalized.update({prefix + "_time": str(obj[key]["time"]), prefix + "_price": obj[key]["price"]})
        summary = {k: deepcopy(obj[k]) for k in ("from", "to", "parallel", "levels", "upper", "lower", "width", "direction") if k in obj}
        if kind == "fibonacci_retracement": normalized["ratios"] = obj["ratios"]
    return {"function": function, "function_version": VERSION, "kind": kind,
            "result_usage": "guarded_drawing",
            "parameters": normalized, "price_scale": "linear", "summary": summary}


def run_function(context_ref, expected_revision, chart_session, symbol, function, parameters):
    from tools.chart_edits import require_alignment
    started = perf_counter()
    # MCP validates this model before dispatch, but the browser workbench sends
    # JSON directly through the local chart service. Both entrances must use
    # the same parameter contract before any calculation or result is stored.
    if not isinstance(parameters, ChartFunctionParameters):
        try:
            parameters = ChartFunctionParameters.model_validate(parameters)
        except ValidationError:
            raise LineError("invalid_function_parameters", "绘图函数参数无效，请核对函数目录中的参数类型与范围。") from None
    context = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
    if type(expected_revision) is not int or context["revision"] != expected_revision:
        raise LineError("chart_context_revision_conflict", "当前观察版本已改变，请重新读取当前图。")
    payload = chart_service.read_chart_snapshot(chart_session)
    if payload is None: raise LineError("chart_session_not_found", "当前命名来源不存在。")
    require_alignment(context, payload, chart_session, symbol)
    calculation = _calculate(payload, function, parameters, candles=context["candles"])
    record = {"schema_version": 1, "binding": _binding(context), **calculation}
    if len(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()) > (262144 if function in {"price_series_line", "price_band", "price_sticks"} else 32768):
        raise LineError("chart_function_result_too_large", "函数结果超出本阶段容量限制，未保存或绘图。")
    result_ref = _hash(record)
    refreshed = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
    if refreshed["revision"] != expected_revision or _binding(refreshed) != record["binding"]:
        raise LineError("chart_context_revision_conflict", "计算期间当前图已变化，未保存结果。")
    directory = _directory(context)
    path = directory / (result_ref + ".json")
    if not path.exists():
        if directory.exists() and sum(1 for _ in directory.glob("*.json")) >= 64:
            raise LineError("chart_function_capacity", "当前视图已保存64个函数结果，不自动丢弃旧引用。")
        chart_service._atomic_runtime_json(path, record)
    else:
        try:
            if json.loads(path.read_text(encoding="utf-8")) != record: raise ValueError("conflict")
        except (OSError, ValueError):
            raise LineError("chart_function_result_invalid", "已保存结果无效，未覆盖旧引用。") from None
    return {"ok": True, "result_ref": result_ref, "function": function,
            "function_version": calculation["function_version"],
            "result_usage": calculation["result_usage"],
            "kind": calculation["kind"], "parameters": calculation["parameters"], "summary": calculation["summary"],
            "data_fingerprint": record["binding"]["data_fingerprint"],
            "data_scope": {k: context.get(k) for k in ("symbol", "interval", "interval_value", "adjust", "loaded_range")},
            "calculation_ms": round((perf_counter() - started) * 1000, 3),
            "chart_modified": False, "render_verified": False, "pattern_quality_verified": False}


def _read_result_record(result_ref, context, kind):
    if not isinstance(result_ref, str) or not re.fullmatch(r"[a-f0-9]{64}", result_ref):
        raise LineError("invalid_function_result_ref", "请使用 run_chart_function 返回的完整结果引用。")
    path = _directory(context) / (result_ref + ".json")
    try:
        if path.stat().st_size > 262144: raise ValueError("size")
        record = json.loads(path.read_text(encoding="utf-8"))
        if _hash(record) != result_ref or record["schema_version"] != 1: raise ValueError("hash")
        if record.get("function") not in {"price_series_line", "price_band", "price_sticks"} and path.stat().st_size > 32768: raise ValueError("size")
    except (OSError, ValueError, TypeError, KeyError):
        raise LineError("chart_function_result_unavailable", "结果引用不存在或已失效；不能借用其他视图或宿主的结果。") from None
    if (record["binding"] != _binding(context) or record.get("function_version") != _version(record.get("function"))
        or record.get("function") not in FUNCTIONS or record.get("kind") != kind):
        raise LineError("chart_function_result_mismatch", "结果的行情、归属、版本或图形类型已不匹配，请重新计算。")
    return record


def resolve_result(result_ref, context, kind):
    record = _read_result_record(result_ref, context, kind)
    if record.get("result_usage") != "guarded_drawing":
        raise LineError("chart_function_result_not_drawable", "该函数结果仅供分析，不能作为绘图几何引用。")
    if kind == "series_line":
        if not isinstance(record.get("render_values"), list) or not any(v is not None for v in record["render_values"]):
            raise LineError("empty_price_series", "条件没有命中可绘制K线，未创建空图形。")
        return {"source": deepcopy(record["parameters"]["value_source"]),
                "condition": deepcopy(record["parameters"]["condition"]),
                "values": deepcopy(record["render_values"])}
    if record["function"] == "conditional_annotation":
        if not isinstance(record.get("drawing_parameters"), dict):
            raise LineError("no_conditional_match", "条件未命中已加载K线，未创建标注。")
        return deepcopy(record["drawing_parameters"])
    if kind == "price_band":
        upper, lower = record.get("render_upper_values"), record.get("render_lower_values")
        if not isinstance(upper, list) or not isinstance(lower, list) or not any(v is not None for v in upper):
            raise LineError("empty_price_band", "条件没有命中可填充K线，未创建空带。")
        return {"upper_source": deepcopy(record["parameters"]["upper_source"]),
                "lower_source": deepcopy(record["parameters"]["lower_source"]),
                "condition": deepcopy(record["parameters"]["condition"]),
                "upper_values": deepcopy(upper), "lower_values": deepcopy(lower)}
    if kind == "price_sticks":
        start, end = record.get("render_start_values"), record.get("render_end_values")
        if not isinstance(start, list) or not isinstance(end, list) or not any(v is not None for v in start):
            raise LineError("empty_price_sticks", "条件没有命中可绘制柱线，未创建空对象。")
        return {"start_source": deepcopy(record["parameters"]["start_source"]),
                "end_source": deepcopy(record["parameters"]["end_source"]),
                "condition": deepcopy(record["parameters"]["condition"]),
                "start_values": deepcopy(start), "end_values": deepcopy(end)}
    return deepcopy(record["parameters"])


def resolve_selected_candidate(result_ref, context, kind, number):
    """Resolve one reviewed 1-based candidate; never alters a chart by itself."""
    if type(number) is not int or not 1 <= number <= 5 or kind not in {"channel", "rectangle"}:
        raise LineError("invalid_candidate_selection", "请指定通道或平台结果中的第1至5个候选。")
    function = "channel_candidates" if kind == "channel" else "range_candidates"
    record = _read_result_record(result_ref, context, function)
    if record.get("result_usage") != "analysis_only":
        raise LineError("candidate_result_not_analysis", "该引用不是只读候选结果。")
    candidates = record.get("summary", {}).get("candidates")
    if not isinstance(candidates, list) or number > len(candidates):
        raise LineError("candidate_not_found", "所选候选不存在；请重新核对结果序号。")
    selected = candidates[number - 1]
    if kind == "channel":
        anchors = selected.get("anchors", {})
        try:
            return {prefix + "_time": str(anchors[key]["time"])
                    for prefix, key in (("start", "from"), ("end", "to"), ("parallel", "parallel"))} | {
                    prefix + "_price": anchors[key]["price"]
                    for prefix, key in (("start", "from"), ("end", "to"), ("parallel", "parallel"))}
        except (TypeError, KeyError):
            raise LineError("candidate_result_invalid", "候选锚点不完整，未准备绘图。") from None
    try:
        return {"start_time": str(selected["start_time"]), "end_time": str(selected["end_time"]),
                "lower_price": selected["lower_price"], "upper_price": selected["upper_price"]}
    except (TypeError, KeyError):
        raise LineError("candidate_result_invalid", "候选边界不完整，未准备绘图。") from None
