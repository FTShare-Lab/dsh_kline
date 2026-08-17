from __future__ import annotations

from tools.draw import SUPPORTED_INDICATORS, draw_kline


def _rows(count: int = 90) -> list[dict[str, float | int]]:
    return [
        {
            "time": 1_700_000_000 + index * 86_400,
            "open": 50 + index * 0.2,
            "high": 51 + index * 0.2,
            "low": 49 + index * 0.2,
            "close": 50.5 + index * 0.2,
            "volume": 500_000 + index * 1_000,
        }
        for index in range(count)
    ]


def test_draw_payload_contains_all_required_indicator_series() -> None:
    required = ["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"]
    payload = draw_kline(_rows(), symbol="600519.XSHG", indicators=required)
    commands = payload["chartCommands"]
    series_names = {
        command["name"]
        for command in commands
        if command["type"] == "SET_INDICATOR_SERIES"
    }

    assert set(required).issubset(SUPPORTED_INDICATORS)
    assert set(required) == series_names
    assert commands[0]["type"] == "SET_CANDLES"
    assert payload["symbol"] == "600519.XSHG"
    assert "view_uri" not in payload


def test_default_and_empty_indicator_layouts_are_stable() -> None:
    default_payload = draw_kline(_rows())
    empty_payload = draw_kline(_rows(), indicators=[])

    assert default_payload["indicators"] == ["ma", "vol"]
    assert {
        command["name"]
        for command in default_payload["chartCommands"]
        if command["type"] == "SET_INDICATOR_SERIES"
    } == {"ma", "vol"}
    assert empty_payload["indicators"] == []
    assert not any(command["type"] == "SET_INDICATOR_SERIES" for command in empty_payload["chartCommands"])


def test_analysis_mark_and_line_ids_are_stable_or_preserved() -> None:
    rows = _rows(2)
    generated = draw_kline(
        rows,
        indicators=[],
        marks=[{"time": rows[0]["time"], "text": "support"}],
        lines=[
            {
                "from": {"time": rows[0]["time"], "price": rows[0]["close"]},
                "to": {"time": rows[1]["time"], "price": rows[1]["close"]},
            }
        ],
    )
    explicit = draw_kline(
        rows,
        indicators=[],
        marks=[{"id": "peak", "time": rows[0]["time"], "text": "peak"}],
        lines=[
            {
                "id": "trend",
                "from": {"time": rows[0]["time"], "price": rows[0]["close"]},
                "to": {"time": rows[1]["time"], "price": rows[1]["close"]},
            }
        ],
    )

    assert next(command for command in generated["chartCommands"] if command["type"] == "TEXT_MARKER")["id"] == "marker:1700000000:0"
    assert next(command for command in generated["chartCommands"] if command["type"] == "DRAW_TREND_LINE")["id"] == "line:1700000000:1700086400:0"
    assert next(command for command in explicit["chartCommands"] if command["type"] == "TEXT_MARKER")["id"] == "peak"
    assert next(command for command in explicit["chartCommands"] if command["type"] == "DRAW_TREND_LINE")["id"] == "trend"


def test_configured_rsi_atr_and_vwap_metadata_is_preserved() -> None:
    payload = draw_kline(_rows(), indicators=["rsi", "atr", "vwap"], rsi_period=6, atr_period=7)
    commands = {
        command["name"]: command
        for command in payload["chartCommands"]
        if command["type"] == "SET_INDICATOR_SERIES"
    }

    assert commands["rsi"]["params"] == {"period": 6}
    assert commands["atr"]["params"] == {"period": 7}
    assert commands["vwap"]["params"] == {"anchor": "loaded_context"}
    assert commands["rsi"]["data"]["rsi"]
    assert commands["atr"]["data"]["atr"]
    assert len(commands["vwap"]["data"]["vwap"]) == len(_rows())


def test_data_source_url_requires_https() -> None:
    safe = draw_kline(
        _rows(2),
        indicators=[],
        data_source="customer-market",
        data_source_url="https://data.example.test/provider",
    )
    unsafe = draw_kline(
        _rows(2),
        indicators=[],
        data_source="local",
        data_source_url="javascript:alert(1)",
    )

    assert safe["data_meta"] == {
        "source": "customer-market",
        "source_url": "https://data.example.test/provider",
    }
    assert unsafe["data_meta"] == {"source": "local"}


def test_comparison_series_and_security_workspace_are_embedded() -> None:
    rows = _rows(4)
    workspace = {"symbol": "600519.XSHG", "news": [{"title": "source"}], "overview": {}}
    payload = draw_kline(
        rows,
        indicators=[],
        comparisons=[{"symbol": "000001.XSHG", "name": "SSE", "rows": rows}],
        security_workspace=workspace,
    )

    command = next(item for item in payload["chartCommands"] if item["type"] == "SET_COMPARISON_SERIES")
    assert command["series"][0]["symbol"] == "000001.XSHG"
    assert command["series"][0]["rows"] == rows
    assert payload["security_workspace"] == workspace
