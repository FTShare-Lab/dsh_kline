from __future__ import annotations

import hashlib
import re
from pathlib import Path

from chart_service import CHART_API_ACTIONS, render_chart_html
from tools.draw import draw_kline


ROOT = Path(__file__).resolve().parents[1]
VIEW_FILE = ROOT / "view" / "kline.html"


def _rows(count: int = 100) -> list[dict[str, float | int]]:
    return [
        {
            "time": 1_700_000_000 + index * 86_400,
            "open": 100 + index * 0.2,
            "high": 102 + index * 0.2,
            "low": 99 + index * 0.2,
            "close": 101 + index * 0.2,
            "volume": 1_000_000 + index * 10_000,
        }
        for index in range(count)
    ]


def test_rendered_frontend_preserves_interactive_chart_contract() -> None:
    payload = draw_kline(
        _rows(),
        symbol="00700.HK",
        indicators=["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"],
    )
    html = render_chart_html(payload).decode("utf-8")

    for control_id in (
        "maBtn",
        "vwapBtn",
        "volBtn",
        "macdBtn",
        "bollBtn",
        "indRsi",
        "indAtr",
        "expandBtn",
        "percentAxis",
        "crosshairTimeLabel",
        "viewScrollbar",
    ):
        assert f'id="{control_id}"' in html

    assert 'kchart.subscribeAction("onCrosshairChange", onCrosshairChange)' in html
    assert 'kchart.subscribeAction("onVisibleRangeChange", scheduleChartOverlayRender)' in html
    assert 'kchart.subscribeAction("onCandleBarClick", onCandleBarClick)' in html
    assert "function fitChartToData()" in html
    assert "kchart.setBarSpace?.(barSpace)" in html
    assert "function scheduleChartResize()" in html
    assert "try { kchart.resize(); }" in html
    assert "function hasLocalRowsForRange(key)" in html
    assert '!hasLocalRowsForRange(currentRangeKey) && currentSymbol && !openingSymbol' in html
    assert 'await openSymbol(currentSymbol, currentName, { preserveOnFailure: true });' in html
    assert "@media (max-width: 640px)" in html
    assert "@media (max-width: 480px)" in html
    assert ".toolbar { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }" in html
    assert "header.bar .change { font-size: 11px; line-height: 1.2; white-space: nowrap; }" in html
    assert ".chart-wrap { position: relative; min-width: 280px; overflow: hidden;" in html
    assert 'chartEl?.addEventListener("wheel"' not in html
    assert 'expandChart: "Expand chart"' in html
    assert 'percentAxis: "Change %"' in html
    assert 'legend.style.display = "flex"' not in html
    assert 'kchart.createIndicator({ name: "MA", calcParams: maPeriods }' in html
    assert 'if (!previousSymbol || previousSymbol !== nextSymbol)' in html


def test_frontend_uses_only_supported_same_origin_chart_actions() -> None:
    html = VIEW_FILE.read_text(encoding="utf-8")
    invoked = set(re.findall(r'(?:callTool|callMarketTool)\("([a-z_]+)"', html))

    assert invoked <= CHART_API_ACTIONS
    assert {
        "calc_range",
        "fetch_candles",
        "fetch_security_workspace",
        "market_ticker",
        "search_symbols",
        "symbol_directory",
    } <= invoked
    assert '"fetch_comparison_candles"' in html
    assert "watchlist_list" not in html
    assert "watchlist_replace" not in html
    assert 'fetch(`/api/tools/${encodeURIComponent(name)}`' in html


def test_frontend_has_no_mcp_app_or_original_host_runtime_dependency() -> None:
    html = VIEW_FILE.read_text(encoding="utf-8")

    for forbidden in (
        "postMessage",
        "window.openai",
        "ui/initialize",
        "ui/request-display-mode",
        "MCP Apps",
        "ft-kline-view",
    ):
        assert forbidden not in html
    assert "window.__DSH_CHART_SESSION__" in render_chart_html(
        draw_kline(_rows(), symbol="NVDA.US")
    ).decode("utf-8")


def test_vendored_visual_assets_match_the_verified_source_checkout() -> None:
    vendor_hash = hashlib.sha256((ROOT / "view" / "vendor" / "klinecharts.min.js").read_bytes()).hexdigest()
    logo_hash = hashlib.sha256((ROOT / "view" / "ft-logo.jpg").read_bytes()).hexdigest()

    assert vendor_hash == "66572fda4b825f3509a5358bd7d0c6b5f3ff6dc604095b6e2c8cac2069ae6cc1"
    assert logo_hash == "55a4bb09ebbd10b97003a8826ff3f227f1dc0f0f9ec2811993d4af923c8f9b2a"
