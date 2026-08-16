from __future__ import annotations

import asyncio
import json

import server


def _rows(count: int = 80) -> list[dict[str, float | int]]:
    result: list[dict[str, float | int]] = []
    for index in range(count):
        close = 100.0 + index * 0.4 + (index % 5 - 2) * 0.2
        result.append(
            {
                "time": 1_700_000_000 + index * 86_400,
                "open": close - 0.3,
                "high": close + 0.8,
                "low": close - 0.9,
                "close": close,
                "volume": 1_000_000 + index * 1_000,
            }
        )
    return result


def test_server_exposes_only_the_standalone_tool_surface() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "health",
        "fetch_candles",
        "calc_metrics",
        "analyze_kline",
    }


def test_health_reports_installed_sdk(monkeypatch) -> None:
    monkeypatch.setattr(server, "ftshare_status", lambda: {"available": True, "distribution_version": "test"})
    result = asyncio.run(server.health())

    assert result.isError is False
    assert result.structuredContent["server"] == "dsh_kline"
    assert "ftshare=available" in result.content[0].text


def test_analyze_kline_uses_one_ftshare_row_set(monkeypatch) -> None:
    source_rows = _rows()
    observed: dict[str, object] = {}

    def fake_fetch(symbol: str, **kwargs):
        observed.update({"symbol": symbol, **kwargs})
        return {
            "ok": True,
            "symbol": symbol,
            "name": "Test Security",
            "interval": "day",
            "adjust": "none",
            "count": len(source_rows),
            "rows": source_rows,
            "source": "ftshare",
            "status": "fresh",
            "as_of": source_rows[-1]["time"],
            "freshness": "current_session",
        }

    monkeypatch.setattr(server, "fetch_candles", fake_fetch)
    result = asyncio.run(
        server.analyze_kline(
            "TEST.HK",
            limit=60,
            indicators=["ma", "vol", "macd", "rsi"],
            metrics=["rsi"],
        )
    )

    assert observed == {
        "symbol": "TEST.HK",
        "interval": "day",
        "interval_value": 1,
        "session_count": None,
        "limit": 108,
        "adjust": "none",
    }
    assert result.isError is False
    data = result.structuredContent
    assert data["source"] == "ftshare"
    assert data["count"] == 60
    assert data["fetched_count"] == 80
    assert data["chart"]["rows"] == source_rows[-60:]
    assert data["metrics"]["rsi"]["last"]["value"] == data["indicator_last"]["rsi"]
    assert set(data["indicator_last"]["macd"]) == {"dif", "dea", "hist"}

    summary = json.loads(result.content[0].text.split(" · ", 1)[1])
    assert summary["source"] == "ftshare"
    assert summary["count"] == 60
    assert "chart" not in summary


def test_analyze_kline_propagates_provider_error(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "fetch_candles",
        lambda *_args, **_kwargs: {
            "ok": False,
            "error": "fetch_failed",
            "message": "upstream unavailable",
        },
    )

    result = asyncio.run(server.analyze_kline("TEST.HK"))

    assert result.isError is True
    assert result.structuredContent["error"] == "fetch_failed"
    assert result.content[0].text == "upstream unavailable"
