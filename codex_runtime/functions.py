"""Pure, memory-scoped TA and chart-function helpers for the Codex adapter."""
from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any

from core.ta_engine import ENGINE_VERSION, NATIVE_VERSION, calculate, catalog
from tools.channel_candidates import channel_candidates
from tools.channels import edit_channel
from tools.fibonacci import edit_fibonacci
from tools.lines import LineError
from tools.polylines import edit_polyline
from tools.price_bands import calculate_price_band
from tools.price_series import PriceCondition, PriceSource, calculate_price_series
from tools.price_sticks import calculate_price_sticks
from tools.range_candidates import DEFAULT_WINDOW_SIZES, range_candidates
from tools.rectangles import edit_rectangle

from .state import CodexChartStore

CATALOG = catalog()
CATALOG_BY_NAME = {item["name"]: item for item in CATALOG}


def list_ta_catalog(*, group: str | None = None, query: str | None = None, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise LineError("invalid_ta_pagination", "TA-Lib 目录分页参数无效。")
    matches = [entry for entry in CATALOG if (not group or entry["group"].casefold() == group.casefold())
               and (not query or query.casefold() in (entry["name"] + " " + entry["display_name"]).casefold())]
    return {"ok": True, "engine": "TA-Lib", "engine_version": ENGINE_VERSION, "native_version": NATIVE_VERSION,
            "total_catalog": len(CATALOG), "total_matches": len(matches), "offset": offset, "limit": limit,
            "groups": sorted({entry["group"] for entry in CATALOG}), "result_usage": "analysis_only",
            "chart_modified": False, "functions": [{key: entry[key] for key in ("name", "group", "display_name", "input_names", "parameters", "output_names", "function_flags")} for entry in matches[offset:offset + limit]]}


def _bound(store: CodexChartStore, context_ref: str, expected_revision: int, chart_session: str, symbol: str):
    context = store.context(context_ref)
    if expected_revision != context["revision"]:
        raise LineError("chart_context_revision_conflict", "当前图已变化，请重新读取上下文。")
    if chart_session != context["source_chart_session"] or str(symbol).casefold() != str(context["symbol"]).casefold():
        raise LineError("chart_snapshot_not_aligned", "图表会话或标的不匹配。")
    return context


def _summary(rows: list[dict[str, Any]], values: dict[str, list[float | None]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, series in values.items():
        valid = [(index, value) for index, value in enumerate(series) if value is not None]
        output[name] = {"first_valid": {"index": valid[0][0], "time": rows[valid[0][0]]["time"]} if valid else None,
                        "latest": {"index": valid[-1][0], "time": rows[valid[-1][0]]["time"], "value": valid[-1][1]} if valid else None,
                        "valid_count": len(valid), "nonzero_count": sum(value != 0 for _, value in valid)}
    return output


def run_ta(store: CodexChartStore, context_ref: str, expected_revision: int, chart_session: str, symbol: str,
           name: str, parameters: dict[str, int | float] | None = None,
           price_sources: dict[str, str] | None = None, periods_constant: int = 14) -> dict[str, Any]:
    if not isinstance(name, str) or name not in CATALOG_BY_NAME:
        raise LineError("unknown_ta_function", "未知 TA-Lib 函数，请先查询目录。")
    context = _bound(store, context_ref, expected_revision, chart_session, symbol)
    started = perf_counter()
    try:
        info, values = calculate(name, context["candles"], parameters=parameters, price_sources=price_sources,
                                 periods_constant=periods_constant)
    except Exception as exc:
        raise LineError("invalid_ta_parameters", f"TA-Lib 参数或输入无效：{exc}") from exc
    record: dict[str, Any] = {"function": name, "parameters": {**info["parameters"], **(parameters or {})},
                              "price_sources": price_sources or {}, "outputs": values, "summary": _summary(context["candles"], values),
                              "result_usage": "analysis_only"}
    targets = []
    if name in {"SMA", "EMA"} and (price_sources or {}) in ({}, {"price": "close"}) and 2 <= int(record["parameters"].get("timeperiod", 0)) <= 200:
        series = values.get("real") or []
        if any(value is not None and value > 0 for value in series):
            record.update({"source": {"kind": name.lower(), "period": int(record["parameters"]["timeperiod"])}, "condition": None, "values": series})
            targets.append({"kind": "series_line"})
    if name == "BBANDS" and (price_sources or {}) in ({}, {"price": "close"}) and int(record["parameters"].get("matype", -1)) == 0:
        try:
            period = int(record["parameters"]["timeperiod"])
            high, mid, low = values["upperband"], values["middleband"], values["lowerband"]
            good = 2 <= period <= 200 and any(a is not None for a in high) and all(a is b is c is None or (a > b > c > 0) for a, b, c in zip(high, mid, low))
            if good:
                common = {"kind": "bbands", "period": period, "deviation_up": record["parameters"]["nbdevup"], "deviation_down": record["parameters"]["nbdevdn"], "matype": 0}
                record.update({"upper_source": {**common, "output": "upperband"}, "lower_source": {**common, "output": "lowerband"}, "condition": None,
                               "upper_values": high, "middle_values": mid, "lower_values": low})
                targets.append({"kind": "price_band"})
        except (KeyError, TypeError, ValueError):
            pass
    stored_kind = targets[0]["kind"] if len(targets) == 1 else "ta_analysis"
    ref = store.store_result(context_ref, revision=expected_revision, kind=stored_kind, result=record)
    return {"ok": True, "result_ref": ref, "function": name, "engine": "TA-Lib", "engine_version": ENGINE_VERSION,
            "native_version": NATIVE_VERSION, "loaded_bars": len(context["candles"]), "summary": record["summary"],
            "selectable_render_targets": targets, "result_usage": "analysis_only", "chart_modified": False,
            "calculation_ms": round((perf_counter() - started) * 1000, 3)}


def read_ta(store: CodexChartStore, context_ref: str, expected_revision: int, chart_session: str, symbol: str,
            result_ref: str, output_name: str, offset: int = 0, limit: int = 200) -> dict[str, Any]:
    _bound(store, context_ref, expected_revision, chart_session, symbol)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 250:
        raise LineError("invalid_ta_pagination", "结果分页参数无效。")
    record = store.raw_result(context_ref, result_ref, revision=expected_revision).get("result", {})
    values = record.get("outputs", {}).get(output_name)
    if not isinstance(values, list): raise LineError("unknown_ta_output", "该结果不存在指定输出。")
    context = store.context(context_ref)
    rows = context["candles"]
    return {"ok": True, "result_ref": result_ref, "output_name": output_name, "offset": offset, "limit": limit,
            "total": len(values), "items": [{"index": index, "time": rows[index]["time"], "value": values[index]}
                                               for index in range(offset, min(offset + limit, len(values)))]}


def list_chart_functions() -> dict[str, Any]:
    names = ("fibonacci_retracement", "parallel_channel", "range_box", "labeled_polyline", "channel_candidates", "range_candidates", "price_series_line", "price_band", "price_sticks")
    return {"ok": True, "schema_version": 1, "workflow": "get_chart_context -> run_chart_function -> prepare_chart_edit -> apply_chart_edit -> get_chart_edit_status",
            "functions": [{"name": name, "result_usage": "analysis_only" if name.endswith("candidates") else "guarded_drawing",
                           "applies_chart": False} for name in names], "pattern_quality_verified": False}


def _drawing_result(store: CodexChartStore, context_ref: str, expected_revision: int, kind: str, parameters: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    ref = store.store_result(context_ref, revision=expected_revision, kind=kind, result=parameters)
    return {"ok": True, "result_ref": ref, "kind": kind, "result_usage": "guarded_drawing", "parameters": deepcopy(parameters),
            "summary": summary, "chart_modified": False, "render_verified": False}


def run_chart_function(store: CodexChartStore, context_ref: str, expected_revision: int, chart_session: str,
                       symbol: str, function: str, parameters: dict[str, Any]) -> dict[str, Any]:
    context = _bound(store, context_ref, expected_revision, chart_session, symbol)
    payload = store.chart_payload(context_ref)
    values = dict(parameters or {})
    if function == "channel_candidates":
        result = channel_candidates(context["candles"], direction=values.get("direction", "both"), scope=values.get("scope", "current"),
                                    lookback_bars=values.get("lookback_bars", 120), left_bars=values.get("left_bars", 2), right_bars=values.get("right_bars", 2),
                                    min_span_bars=values.get("min_span_bars", 12), limit=values.get("max_candidates", 3))
        ref = store.store_result(context_ref, revision=expected_revision, kind="channel_candidates", result={"candidates": result.get("candidates", [])})
        return {"ok": True, "result_ref": ref, "function": function, "kind": "channel_candidates", "result_usage": "analysis_only", "summary": result, "chart_modified": False}
    if function == "range_candidates":
        result = range_candidates(context["candles"], window_sizes=values.get("window_sizes", DEFAULT_WINDOW_SIZES), limit=values.get("max_candidates", 3))
        ref = store.store_result(context_ref, revision=expected_revision, kind="range_candidates", result={"candidates": result.get("candidates", [])})
        return {"ok": True, "result_ref": ref, "function": function, "kind": "range_candidates", "result_usage": "analysis_only", "summary": result, "chart_modified": False}
    if function == "price_series_line":
        source = PriceSource.model_validate(values.get("value_source")); condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculated = calculate_price_series(context["candles"], source, condition)
        return _drawing_result(store, context_ref, expected_revision, "series_line", {"source": source.model_dump(exclude_none=True), "condition": condition.model_dump(exclude_none=True) if condition else None, "values": calculated["values"]}, calculated["summary"])
    if function == "price_band":
        upper, lower = PriceSource.model_validate(values.get("upper_source")), PriceSource.model_validate(values.get("lower_source"))
        condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculated = calculate_price_band(context["candles"], upper, lower, condition)
        return _drawing_result(store, context_ref, expected_revision, "price_band", {"upper_source": upper.model_dump(exclude_none=True), "lower_source": lower.model_dump(exclude_none=True), "condition": condition.model_dump(exclude_none=True) if condition else None, "upper_values": calculated["upper_values"], "lower_values": calculated["lower_values"]}, calculated["summary"])
    if function == "price_sticks":
        start, end = PriceSource.model_validate(values.get("start_source")), PriceSource.model_validate(values.get("end_source"))
        condition = PriceCondition.model_validate(values["condition"]) if values.get("condition") is not None else None
        calculated = calculate_price_sticks(context["candles"], start, end, condition)
        return _drawing_result(store, context_ref, expected_revision, "price_sticks", {"start_source": start.model_dump(exclude_none=True), "end_source": end.model_dump(exclude_none=True), "condition": condition.model_dump(exclude_none=True) if condition else None, "start_values": calculated["start_values"], "end_values": calculated["end_values"]}, calculated["summary"])
    editors = {"parallel_channel": ("channel", edit_channel), "range_box": ("rectangle", edit_rectangle),
               "fibonacci_retracement": ("fibonacci_retracement", edit_fibonacci), "labeled_polyline": ("labeled_polyline", edit_polyline)}
    if function not in editors: raise LineError("unknown_chart_function", "未知绘图函数。")
    kind, editor = editors[function]
    # Validate through the same pure editor used by guarded commit. The temporary
    # object is never published and its random ID is discarded.
    temp, object_value = editor(payload, "create", **values)
    if kind == "channel": params = {"start_time": str(object_value["from"]["time"]), "start_price": object_value["from"]["price"], "end_time": str(object_value["to"]["time"]), "end_price": object_value["to"]["price"], "parallel_time": str(object_value["parallel"]["time"]), "parallel_price": object_value["parallel"]["price"]}
    elif kind == "rectangle": params = {key: str(object_value[key]) if key.endswith("_time") else object_value[key] for key in ("start_time", "end_time", "lower_price", "upper_price")}
    elif kind == "fibonacci_retracement": params = {"start_time": str(object_value["from"]["time"]), "start_price": object_value["from"]["price"], "end_time": str(object_value["to"]["time"]), "end_price": object_value["to"]["price"], "ratios": object_value["ratios"]}
    else: params = {"points": [{**point, "time": str(point["time"])} for point in object_value["points"]]}
    return _drawing_result(store, context_ref, expected_revision, kind, params, {"object_preview": object_value})

