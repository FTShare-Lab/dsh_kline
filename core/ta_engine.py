"""Pinned TA-Lib engine shared by public analysis and built-in indicators."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import talib
from talib import abstract


ENGINE_VERSION = "0.8.2"
FUNCTION_COUNT = 201
if talib.__version__ != ENGINE_VERSION or len(talib.get_functions()) != FUNCTION_COUNT:
    raise RuntimeError("TA-Lib version/catalog mismatch; legacy formulas are not a fallback")

NATIVE_VERSION = getattr(talib, "__ta_version__", b"unknown")
if isinstance(NATIVE_VERSION, bytes):
    NATIVE_VERSION = NATIVE_VERSION.decode("utf-8", errors="replace")


def arrays(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    return {key: np.asarray([float(row[key]) for row in rows], dtype=np.float64)
            for key in ("open", "high", "low", "close", "volume")}


def finite_map(rows: list[dict[str, Any]], values: Any, digits: int = 6) -> dict[int, float]:
    result: dict[int, float] = {}
    for row, value in zip(rows, values):
        number = float(value)
        if math.isfinite(number):
            result[int(row["time"])] = round(number, digits)
    return result


def catalog() -> list[dict[str, Any]]:
    return [{"name": name, **abstract.Function(name).info} for name in talib.get_functions()]


def calculate(name: str, rows: list[dict[str, Any]], *, parameters: dict[str, int | float] | None = None,
              price_sources: dict[str, str] | None = None, periods_constant: int = 14) -> tuple[dict[str, Any], dict[str, list[int | float | None]]]:
    if name not in talib.get_functions():
        raise ValueError("unknown TA-Lib function")
    if not 1 <= len(rows) <= 4000:
        raise ValueError("TA-Lib requires 1..4000 loaded candles")
    function = abstract.Function(name)
    info = function.info
    defaults = info["parameters"]
    selected = dict(parameters or {})
    if set(selected) - set(defaults):
        raise ValueError("unsupported TA-Lib parameter")
    for key, value in selected.items():
        default = defaults[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("TA-Lib parameters must be finite numbers")
        if type(default) is int and (type(value) is not int or abs(value) > 4000):
            raise ValueError("TA-Lib integer parameter out of bounds")
        if type(default) is float:
            if abs(value) > 1_000_000:
                raise ValueError("TA-Lib numeric parameter out of bounds")
            # JSON callers naturally send 2 for a deviation of 2.0. The
            # TA-Lib abstract wrapper requires an actual Python float.
            selected[key] = float(value)
    function.parameters = selected
    sources = dict(price_sources or {})
    allowed_roles = set(info["input_names"]) & {"price", "price0", "price1"}
    if set(sources) - allowed_roles:
        raise ValueError(f"{name} price_sources keys must be {sorted(allowed_roles)}; "
                         "see list_ta_functions input_names, not low-level TA-Lib names")
    if any(value not in {"open", "high", "low", "close"} for value in sources.values()):
        raise ValueError("price_sources values must be open, high, low, or close")
    if sources:
        function.input_names = sources
    data = arrays(rows)
    if name == "MAVP":
        if type(periods_constant) is not int or not 2 <= periods_constant <= 4000:
            raise ValueError("MAVP periods_constant must be an integer from 2 to 4000")
        minperiod = selected.get("minperiod", defaults["minperiod"])
        maxperiod = selected.get("maxperiod", defaults["maxperiod"])
        if not minperiod <= periods_constant <= maxperiod:
            raise ValueError("MAVP periods_constant must be within minperiod and maxperiod")
        data["periods"] = np.full(len(rows), float(periods_constant), dtype=np.float64)
    elif periods_constant != 14:
        raise ValueError("periods_constant applies only to MAVP")
    function.set_input_arrays(data)
    raw = function()
    outputs = raw if isinstance(raw, (list, tuple)) else [raw]
    names = list(info["output_names"])
    if len(outputs) != len(names):
        raise RuntimeError("TA-Lib output metadata mismatch")
    values: dict[str, list[int | float | None]] = {}
    for output_name, output in zip(names, outputs):
        vector = np.asarray(output)
        if len(vector) != len(rows):
            raise RuntimeError("TA-Lib output length mismatch")
        integer_output = np.issubdtype(vector.dtype, np.integer)
        values[output_name] = [int(x) if integer_output else float(x) if math.isfinite(float(x)) else None for x in vector]
    return info, values
