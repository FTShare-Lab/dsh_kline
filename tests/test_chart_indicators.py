"""The browser's local chart must use the same TA-Lib series as MCP summaries."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import chart_service
from core.calc import series_atr, series_macd, series_rsi
from tools.chart_indicators import calculate_chart_indicators
from tools.price_series import candle_sequence_hash


ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.loads((ROOT / "benchmarks/2026-10-12/frozen-charts/B05-2.json").read_text())
ROWS = next(command["rows"] for command in FROZEN["chartCommands"] if command["type"] == "SET_CANDLES")


def args(rows=ROWS):
    return {
        "rows": rows, "expected_hash": candle_sequence_hash(rows),
        "indicators": ["ma", "vol", "macd", "kdj", "boll", "rsi", "atr", "vwap"],
        "ma_periods": [5, 20], "volume_ma": 5, "boll_period": 20,
        "boll_std": 2.0, "rsi_period": 14, "atr_period": 14,
    }


def test_browser_bridge_returns_talib_series_without_mutating_chart():
    with patch("chart_service.publish_chart", side_effect=AssertionError("must not publish")):
        result = calculate_chart_indicators(**args())
    assert result["calculation_engine"]["wrapper_version"] == "0.8.2"
    assert result["source_hash"] == candle_sequence_hash(ROWS)
    assert result["loaded_bars"] == len(ROWS)
    assert result["chart_modified"] is False
    commands = {item["name"]: item for item in result["chartCommands"]}
    assert set(commands) == set(args()["indicators"])
    assert all(item["type"] == "SET_INDICATOR_SERIES" for item in commands.values())
    last_time = str(ROWS[-1]["time"])
    assert commands["macd"]["data"]["hist"][last_time] == series_macd(ROWS)["hist"][ROWS[-1]["time"]]
    assert commands["rsi"]["data"]["rsi"][last_time] == series_rsi(ROWS)[ROWS[-1]["time"]]
    assert commands["atr"]["data"]["atr"][last_time] == series_atr(ROWS)[ROWS[-1]["time"]]
    assert str(ROWS[13]["time"]) not in commands["atr"]["data"]["atr"]
    assert str(ROWS[14]["time"]) in commands["atr"]["data"]["atr"]


def test_browser_bridge_rejects_changed_or_invalid_source_and_options():
    valid = args()
    for change in (
        {"expected_hash": "0" * 16},
        {"rows": ROWS[:-1]},
        {"indicators": ["macd", "macd"]},
        {"ma_periods": [0]},
        {"boll_std": float("nan")},
        {"volume_ma": True},
    ):
        with pytest.raises((TypeError, ValueError)):
            calculate_chart_indicators(**{**valid, **change})
    with pytest.raises(ValueError):
        calculate_chart_indicators(**args(ROWS * 17))
    dispatched = chart_service._tool_dispatch("calculate_chart_indicators", {**valid, "expected_hash": "bad"})
    assert dispatched["ok"] is False
    assert dispatched["error"] == "invalid_indicator_request"


def test_browser_bridge_empty_indicator_selection_is_valid_and_read_only():
    result = calculate_chart_indicators(**{**args(), "indicators": []})
    assert result["chartCommands"] == []
    assert result["chart_modified"] is False
