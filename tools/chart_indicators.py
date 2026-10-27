"""Internal browser bridge for TA-Lib chart indicators on already loaded rows.

This is not an MCP analysis tool. It never fetches or publishes a chart.
"""

from __future__ import annotations

import math
from typing import Any

from core.rows import validate_rows
from core.ta_engine import ENGINE_VERSION, NATIVE_VERSION
from tools.draw import SUPPORTED_INDICATORS, build_chart_commands
from tools.price_series import candle_sequence_hash


def _period(value: Any, name: str, maximum: int = 200) -> int:
    if type(value) is not int or not 2 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 2 to {maximum}")
    return value


def calculate_chart_indicators(
    *, rows: Any, expected_hash: str, indicators: list[str],
    ma_periods: list[int], volume_ma: int, boll_period: int,
    boll_std: float, rsi_period: int, atr_period: int,
) -> dict[str, Any]:
    if not isinstance(rows, list) or not 2 <= len(rows) <= 4000:
        raise ValueError("indicator rows must contain 2..4000 loaded candles")
    normalized = validate_rows(rows, min_len=2)
    if len(normalized) != len(rows):
        raise ValueError("indicator rows must not be normalized, dropped or deduplicated")
    actual_hash = candle_sequence_hash(normalized)
    if not isinstance(expected_hash, str) or expected_hash != actual_hash:
        raise ValueError("indicator source hash does not match current loaded candles")
    if (not isinstance(indicators, list) or len(indicators) > len(SUPPORTED_INDICATORS)
        or any(not isinstance(name, str) or name not in SUPPORTED_INDICATORS for name in indicators)
        or len(set(indicators)) != len(indicators)):
        raise ValueError("unsupported or duplicate indicator name")
    if (not isinstance(ma_periods, list) or not 1 <= len(ma_periods) <= 8
        or len(set(ma_periods)) != len(ma_periods)):
        raise ValueError("ma_periods must contain 1..8 distinct periods")
    periods = [_period(value, "ma_period", 400) for value in ma_periods]
    volume_ma = _period(volume_ma, "volume_ma")
    boll_period = _period(boll_period, "boll_period")
    rsi_period = _period(rsi_period, "rsi_period")
    atr_period = _period(atr_period, "atr_period")
    if type(boll_std) not in (int, float) or not math.isfinite(boll_std) or not 0.5 <= boll_std <= 5:
        raise ValueError("boll_std must be a finite number from 0.5 to 5")
    commands = build_chart_commands(
        normalized, indicators=indicators, ma_periods=periods,
        volume_ma=volume_ma, boll_period=boll_period, boll_std=boll_std,
        rsi_period=rsi_period, atr_period=atr_period,
    )
    return {
        "ok": True,
        "calculation_engine": {"name": "TA-Lib", "wrapper_version": ENGINE_VERSION,
                               "native_version": NATIVE_VERSION},
        "source_hash": actual_hash,
        "loaded_bars": len(normalized),
        "chartCommands": [command for command in commands if command["type"] == "SET_INDICATOR_SERIES"],
        "chart_modified": False,
    }
