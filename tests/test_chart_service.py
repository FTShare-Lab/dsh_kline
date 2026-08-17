from __future__ import annotations

import time

import chart_service
from tools.draw import draw_kline


def _rows(count: int = 80) -> list[dict[str, float | int]]:
    return [
        {
            "time": 1_700_000_000 + index * 86_400,
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "volume": 1_000_000 + index * 2_000,
        }
        for index in range(count)
    ]


def test_render_chart_html_is_standalone_and_embeds_session() -> None:
    payload = draw_kline(
        _rows(),
        symbol="00700.HK",
        name="Tencent",
        indicators=["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"],
    )

    html = chart_service.render_chart_html(payload).decode("utf-8")

    assert "/*__KLINECHARTS_VENDOR_JS__*/" not in html
    assert "/*__FTV_VIEW_META__*/" not in html
    assert "__FTV_LOGO_DATA__" not in html
    assert "window.__DSH_CHART_SESSION__=" in html
    assert '"symbol":"00700.HK"' in html
    assert "window.klinecharts" in html
    assert "postMessage" not in html
    assert "window.openai" not in html
    assert "MCP Apps" not in html


def test_chart_session_store_expires_and_evicts() -> None:
    store = chart_service.ChartSessionStore(ttl_seconds=1, max_sessions=2)
    first = store.create({"symbol": "A"})
    second = store.create({"symbol": "B"})
    third = store.create({"symbol": "C"})

    assert store.get(first) is None
    assert store.get(second) == {"symbol": "B"}
    assert store.get(third) == {"symbol": "C"}

    store._items[second] = chart_service.ChartSession(payload={"symbol": "B"}, created_at=time.time() - 2)
    assert store.get(second) is None


def test_chart_api_dispatches_tools_and_rejects_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        chart_service,
        "fetch_candles",
        lambda symbol, **kwargs: {"ok": True, "symbol": symbol, "kwargs": kwargs},
    )

    result = chart_service._tool_dispatch("fetch_candles", {"symbol": "NVDA.US", "interval": "day"})
    unknown = chart_service._tool_dispatch("not_a_tool", {})

    assert result == {"ok": True, "symbol": "NVDA.US", "kwargs": {"interval": "day"}}
    assert unknown["error"] == "unsupported_chart_action"


def test_symbol_directory_maps_frontend_refresh_argument(monkeypatch) -> None:
    observed: list[bool] = []
    monkeypatch.setattr(
        chart_service,
        "symbol_directory",
        lambda *, force_refresh=False: observed.append(force_refresh) or {"ok": True, "items": []},
    )

    result = chart_service._tool_dispatch("symbol_directory", {"refresh": True})

    assert result["ok"] is True
    assert observed == [True]


def test_default_chart_port_falls_back_to_an_ephemeral_port(monkeypatch) -> None:
    attempts: list[tuple[str, int]] = []

    class FakeService:
        def __init__(self, host: str, port: int) -> None:
            attempts.append((host, port))
            if port == chart_service.DEFAULT_PORT:
                raise OSError("address in use")

    monkeypatch.setattr(chart_service, "ChartService", FakeService)
    monkeypatch.setattr(chart_service, "_service", None)
    monkeypatch.setenv("DSH_KLINE_CHART_HOST", "127.0.0.1")
    monkeypatch.setenv("DSH_KLINE_CHART_PORT", str(chart_service.DEFAULT_PORT))

    service = chart_service.ensure_chart_service()

    assert isinstance(service, FakeService)
    assert attempts == [("127.0.0.1", chart_service.DEFAULT_PORT), ("127.0.0.1", 0)]
