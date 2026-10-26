"""Read-only, current-chart-bound access to the complete pinned TA-Lib catalog."""

from __future__ import annotations

import json
import math
from time import perf_counter

import chart_service
from core.ta_engine import ENGINE_VERSION, NATIVE_VERSION, calculate, catalog
from tools.chart_context import read_chart_context
from tools.chart_edits import require_alignment
from tools.chart_functions import _binding, _hash
from tools.lines import LineError


CATALOG = catalog()
CATALOG_BY_NAME = {item["name"]: item for item in CATALOG}
MAX_RESULT_BYTES = 1024 * 1024
MAX_RESULTS_PER_VIEW = 16


def list_ta_catalog(*, group: str | None = None, query: str | None = None,
                    offset: int = 0, limit: int = 25) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise LineError("invalid_ta_pagination", "TA-Lib 目录分页参数无效。")
    if group is not None and (not isinstance(group, str) or len(group) > 64):
        raise LineError("invalid_ta_group", "TA-Lib 函数组别无效。")
    if query is not None and (not isinstance(query, str) or len(query) > 64):
        raise LineError("invalid_ta_query", "TA-Lib 搜索词无效。")
    matches = [entry for entry in CATALOG
               if (not group or entry["group"].casefold() == group.casefold())
               and (not query or query.casefold() in (entry["name"] + " " + entry["display_name"]).casefold())]
    return {"ok": True, "engine": "TA-Lib", "engine_version": ENGINE_VERSION, "native_version": NATIVE_VERSION,
            "total_catalog": len(CATALOG), "total_matches": len(matches), "offset": offset, "limit": limit,
            "groups": sorted({entry["group"] for entry in CATALOG}),
            "functions": [{key: entry[key] for key in ("name", "group", "display_name", "input_names", "parameters",
                                                      "output_names", "function_flags")}
                          for entry in matches[offset:offset + limit]],
            "result_usage": "analysis_only", "chart_modified": False}


def _context(context_ref, expected_revision, chart_session, symbol):
    context = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
    if type(expected_revision) is not int or context["revision"] != expected_revision:
        raise LineError("chart_context_revision_conflict", "当前图观察版本已改变，请重新读取。")
    payload = chart_service.read_chart_snapshot(chart_session)
    if payload is None:
        raise LineError("chart_session_not_found", "当前图来源不存在。")
    require_alignment(context, payload, chart_session, symbol)
    if context["candle_selection"]["truncated"] or not context["candles"]:
        raise LineError("ta_candles_unavailable", "仅支持当前图1至4000根完整已加载K线，不截断计算。")
    return context


def _directory(context):
    return chart_service.RUNTIME_DIR / "ta_functions" / str(chart_service.HOST_PROCESS_ID) / context["context_ref"]


def _aligned_outputs(record, context, names):
    times = record.get("times")
    outputs = record.get("outputs")
    return (isinstance(times, list) and times == [row["time"] for row in context["candles"]]
            and isinstance(outputs, dict)
            and all(isinstance(outputs.get(name), list) and len(outputs[name]) == len(times) for name in names))


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _renderable_line(record, context):
    """Only a finite, positive SMA/EMA(close) series fits the current price-line contract."""
    parameters = record.get("parameters")
    period = parameters.get("timeperiod") if isinstance(parameters, dict) else None
    if not (record.get("function") in {"SMA", "EMA"} and type(period) is int and 2 <= period <= 200
            and record.get("price_sources") in ({}, {"price": "close"})
            and _aligned_outputs(record, context, ("real",))):
        return False
    values = record["outputs"]["real"]
    return any(value is not None for value in values) and all(value is None or _positive(value) for value in values)


def _renderable_bbands(record, context):
    params = record.get("parameters")
    if not (record.get("function") == "BBANDS" and isinstance(params, dict)
            and type(params.get("timeperiod")) is int and 2 <= params["timeperiod"] <= 200
            and type(params.get("matype")) is int and params["matype"] == 0
            and all(type(params.get(key)) in (int, float) and math.isfinite(params[key])
                    and 0 < params[key] <= 5 for key in ("nbdevup", "nbdevdn"))
            and record.get("price_sources") in ({}, {"price": "close"})
            and _aligned_outputs(record, context, ("upperband", "middleband", "lowerband"))):
        return False
    outputs = record["outputs"]
    triples = zip(outputs["upperband"], outputs["middleband"], outputs["lowerband"])
    valid = 0
    for upper, middle, lower in triples:
        if upper is middle is lower is None:
            continue
        if not (_positive(upper) and _positive(middle) and _positive(lower)
                and upper > middle > lower):
            return False
        valid += 1
    return valid > 0


def _load_record(context, result_ref, expected_revision):
    if not isinstance(result_ref, str) or len(result_ref) != 64 or any(c not in "0123456789abcdef" for c in result_ref):
        raise LineError("invalid_ta_result_ref", "TA-Lib 结果引用无效。")
    path = _directory(context) / f"{result_ref}.json"
    try:
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError("size")
        record = json.loads(path.read_text(encoding="utf-8"))
        if _hash(record) != result_ref or record.get("schema_version") != 1:
            raise ValueError("hash")
    except (OSError, ValueError, TypeError):
        raise LineError("ta_result_unavailable", "结果引用不存在或已失效。") from None
    if (record.get("engine") != "TA-Lib" or record.get("engine_version") != ENGINE_VERSION
        or record.get("native_version") != NATIVE_VERSION or record.get("result_usage") != "analysis_only"
        or record.get("binding") != _binding(context)
        or record.get("observation_revision") != expected_revision):
        raise LineError("ta_result_mismatch", "结果与当前标的、周期、行情或视图不匹配，请重新计算。")
    return record


def resolve_ta_drawing(result_ref, context, kind):
    """Explicitly promote an allowlisted bound TA result into guarded price geometry."""
    record = _load_record(context, result_ref, context["revision"])
    if kind == "series_line" and _renderable_line(record, context):
        return {"source": {"kind": record["function"].lower(), "period": record["parameters"]["timeperiod"]},
                "condition": None, "values": list(record["outputs"]["real"])}
    if kind == "price_band" and _renderable_bbands(record, context):
        params = record["parameters"]
        source = {"kind": "bbands", "period": params["timeperiod"],
                  "deviation_up": params["nbdevup"], "deviation_down": params["nbdevdn"], "matype": 0}
        return {"upper_source": {**source, "output": "upperband"},
                "lower_source": {**source, "output": "lowerband"}, "condition": None,
                "upper_values": list(record["outputs"]["upperband"]),
                "middle_values": list(record["outputs"]["middleband"]),
                "lower_values": list(record["outputs"]["lowerband"])}
    raise LineError("ta_result_not_drawable", "仅支持当前图的有限 SMA/EMA(close) 单线或 BBANDS(close, SMA中轨) 三线价带；请核对函数、输入、参数与目标图形。")


def run_ta(context_ref, expected_revision, chart_session, symbol, name, parameters=None,
           price_sources=None, periods_constant=14):
    started = perf_counter()
    if not isinstance(name, str) or name not in CATALOG_BY_NAME:
        raise LineError("unknown_ta_function", "未知 TA-Lib 函数，请先查询 list_ta_functions。")
    context = _context(context_ref, expected_revision, chart_session, symbol)
    try:
        info, values = calculate(name, context["candles"], parameters=parameters,
                                 price_sources=price_sources, periods_constant=periods_constant)
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise LineError("invalid_ta_parameters", f"TA-Lib 参数或输入无效：{exc}") from None
    rows = context["candles"]
    summaries = {}
    any_finite = False
    for output_name, series in values.items():
        valid = [(index, value) for index, value in enumerate(series) if value is not None]
        any_finite |= bool(valid)
        summaries[output_name] = {
            "first_valid": {"index": valid[0][0], "time": rows[valid[0][0]]["time"]} if valid else None,
            "latest": {"index": valid[-1][0], "time": rows[valid[-1][0]]["time"],
                       "value": valid[-1][1]} if valid else None,
            "valid_count": len(valid), "nonzero_count": sum(value != 0 for _, value in valid),
        }
    record = {"schema_version": 1, "engine": "TA-Lib", "engine_version": ENGINE_VERSION,
              "native_version": NATIVE_VERSION, "binding": _binding(context),
              "observation_revision": expected_revision, "function": name,
              "parameters": {**info["parameters"], **(parameters or {})},
              "price_sources": price_sources or {}, "periods_constant": periods_constant if name == "MAVP" else None,
              "times": [row["time"] for row in rows], "outputs": values, "summary": summaries,
              "result_usage": "analysis_only"}
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        raise LineError("ta_result_too_large", "TA-Lib 结果超过本地容量限制，未保存。")
    result_ref = _hash(record)
    refreshed = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
    if refreshed["revision"] != expected_revision or _binding(refreshed) != record["binding"]:
        raise LineError("chart_context_revision_conflict", "计算期间当前图已改变，未保存结果。")
    directory = _directory(context)
    path = directory / f"{result_ref}.json"
    if not path.exists():
        existing = sorted(directory.glob("*.json"), key=lambda item: (item.stat().st_mtime_ns, item.name)) if directory.exists() else []
        if len(existing) >= MAX_RESULTS_PER_VIEW:
            try:
                for expired in existing[:len(existing) - MAX_RESULTS_PER_VIEW + 1]:
                    expired.unlink()
            except OSError:
                raise LineError("ta_result_capacity", "当前图的临时结果容量已满，无法淘汰旧结果。") from None
        chart_service._atomic_runtime_json(path, record)
    else:
        try:
            if json.loads(path.read_text(encoding="utf-8")) != record:
                raise ValueError("collision")
        except (OSError, ValueError):
            raise LineError("ta_result_invalid", "已保存 TA 结果无效，未覆盖。") from None
    return {"ok": True, "engine": "TA-Lib", "engine_version": ENGINE_VERSION,
            "native_version": NATIVE_VERSION, "result_ref": result_ref, "function": name,
            "parameters": record["parameters"], "price_sources": record["price_sources"],
            "status": "ok" if any_finite else "no_finite_output", "summary": summaries,
            "loaded_bars": len(rows), "data_fingerprint": record["binding"]["data_fingerprint"],
            "data_scope": {key: context.get(key) for key in ("symbol", "interval", "interval_value", "adjust", "loaded_range")},
            "result_usage": "analysis_only", "chart_modified": False, "render_verified": False,
            "selectable_render_targets": ([{"kind": "series_line", "output_name": "real"}]
                                          if _renderable_line(record, context) else
                                          [{"kind": "price_band", "output_names": ["upperband", "middleband", "lowerband"]}]
                                          if _renderable_bbands(record, context) else []),
            "calculation_ms": round((perf_counter() - started) * 1000, 3)}


def read_ta(context_ref, expected_revision, chart_session, symbol, result_ref, output_name,
            offset=0, limit=200):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 250:
        raise LineError("invalid_ta_pagination", "TA-Lib 结果分页参数无效。")
    context = _context(context_ref, expected_revision, chart_session, symbol)
    record = _load_record(context, result_ref, expected_revision)
    series = record.get("outputs", {}).get(output_name) if isinstance(output_name, str) else None
    times = record.get("times")
    if not isinstance(series, list) or not isinstance(times, list) or len(series) != len(times):
        raise LineError("ta_output_unknown", "结果不存在此输出名称。")
    return {"ok": True, "result_ref": result_ref, "function": record["function"],
            "output_name": output_name, "total": len(series), "offset": offset, "limit": limit,
            "items": [{"time": times[i], "value": series[i]} for i in range(offset, min(offset + limit, len(series)))],
            "result_usage": "analysis_only", "chart_modified": False}
