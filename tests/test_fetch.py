"""FTShare adapter behavior that does not require the network."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from tools import fetch


def test_search_symbols_normalizes_ftshare_results(monkeypatch) -> None:
    class FakeMarket:
        def search(self, *, query: str, limit: int, as_dataframe: bool) -> list[dict[str, object]]:
            assert query == "招商"
            assert limit == 3
            assert as_dataframe is False
            return [
                {"symbol": "600036.SH", "name": "招商银行", "board": "sh", "close": "39.59", "change_rate": 0.01},
                {"symbol": "600036.SH", "name": "duplicate"},
                {"symbol_id": "03968", "name": "招商银行", "board": "hk"},
            ]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.search_symbols("招商", limit=3)

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["results"][0]["symbol"] == "600036.XSHG"
    assert result["results"][0]["change_rate"] == 0.01
    assert result["results"][1]["symbol"] == "03968"


def test_search_symbols_accepts_vendor_name_alias_fields(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {"stock_code": "600519.XSHG", "stock_name": "600519.XSHG"},
                {"stock_code": "600519.SH", "stock_name": "贵州茅台"},
            ]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))
    fetch._symbol_search_cache.clear()

    result = fetch.search_symbols("600519", limit=3)

    assert result["results"] == [{"symbol": "600519.XSHG", "name": "贵州茅台"}]


def test_symbol_name_prefers_named_exchange_alias_over_code_fallback() -> None:
    class FakeMarket:
        def search(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs == {"query": "600519", "limit": 8, "as_dataframe": False}
            return [
                {"stock_code": "600519.XSHG", "stock_name": "600519.XSHG"},
                {"stock_code": "600519.SH", "stock_name": "贵州茅台"},
            ]

    assert fetch._symbol_name(FakeMarket(), "600519.XSHG") == "贵州茅台"


def test_symbol_name_falls_back_to_canonicalized_directory_cache(monkeypatch) -> None:
    class EmptyMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(
        fetch,
        "_read_symbol_directory_cache",
        lambda: {"items": [{"symbol": "600519.SH", "name": "贵州茅台", "market": "CN"}]},
    )

    assert fetch._symbol_name(EmptyMarket(), "600519.XSHG") == "贵州茅台"


def test_search_symbols_rejects_empty_query() -> None:
    result = fetch.search_symbols("   ")

    assert result == {"ok": False, "error": "invalid_query", "message": "query is required"}


def test_search_symbols_uses_short_lived_cache(monkeypatch) -> None:
    calls = 0

    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            nonlocal calls
            calls += 1
            return [{"symbol": "600036.SH", "name": "招商银行"}]

    fetch._symbol_search_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    assert fetch.search_symbols("招商", limit=8)["count"] == 1
    assert fetch.search_symbols("招商", limit=8)["count"] == 1
    assert calls == 1


def test_search_symbols_keeps_essential_aliases_when_vendor_directory_is_empty(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    fetch._symbol_search_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    assert fetch.search_symbols("英伟达", limit=5)["results"][0]["symbol"] == "NVDA.US"
    fetch._symbol_search_cache.clear()
    assert fetch.search_symbols("上证指数", limit=5)["results"][0]["symbol"] == "000001.XSHG"
    fetch._symbol_search_cache.clear()
    assert fetch.search_symbols("科创50", limit=5)["results"][0] == {"symbol": "000688.XSHG", "name": "科创50", "market": "CN_INDEX"}
    fetch._symbol_search_cache.clear()
    assert fetch.search_symbols("北证50", limit=5)["results"][0] == {"symbol": "899050.BJSE", "name": "北证50", "market": "CN_INDEX"}


def test_symbol_directory_refreshes_once_then_uses_disk_cache(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class FakeMarket:
        def stock_list(self, *, as_dataframe: bool) -> list[dict[str, object]]:
            calls.append("stock")
            assert as_dataframe is False
            return [{"symbol": "600036.XSHG", "name": "招商银行"}]

        def index_description_all(self, *, as_dataframe: bool) -> list[dict[str, object]]:
            calls.append("index")
            assert as_dataframe is False
            return [{"index_code": "000300.XSHG", "index_name": "沪深300"}]

        def eastmoney_us_stock_list(self, *, as_dataframe: bool, all_pages: bool, page_size: int) -> list[dict[str, object]]:
            calls.append("us")
            assert as_dataframe is False
            assert all_pages is True
            assert page_size == 200
            return [{"ticker": "AAPL.US", "name": "Apple"}]

    monkeypatch.setenv("DSH_KLINE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    first = fetch.symbol_directory()
    second = fetch.symbol_directory()

    assert first["refreshed"] is True
    assert second["refreshed"] is False
    assert calls == ["stock", "index", "us"]
    assert {item["symbol"] for item in first["items"]} >= {"600036.XSHG", "000300.XSHG", "AAPL.US", "00700.HK"}
    assert first["coverage"]["CN"]["complete"] is True
    assert first["coverage"]["US"]["complete"] is True
    assert first["coverage"]["HK"]["status"] == "partial"


def test_symbol_directory_normalizes_eastmoney_us_identifiers() -> None:
    rows = [{"secid": "105.AAPL", "market": "105", "name": "苹果"}]

    assert fetch._directory_items(rows, "US") == [{"symbol": "AAPL.US", "name": "苹果", "market": "US"}]


def test_external_symbol_directory_is_preserved_after_expiry(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DSH_KLINE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(fetch, "ftshare_available", lambda: False)

    registered = fetch.register_symbol_directory(
        [
            {"symbol": "600036.XSHG", "name": "招商银行", "market": "CN"},
            {"code": "00700.HK", "name": "腾讯控股", "market": "HK"},
        ],
        source="FTShare MCP",
        source_version="2026-07-29",
        complete_markets=["CN", "HK"],
        ttl_seconds=300,
    )

    assert registered["ok"] is True
    assert registered["provider_mode"] == "external"
    assert registered["coverage"]["HK"]["complete"] is True

    fresh = fetch.symbol_directory()
    expired = fetch.symbol_directory(force_refresh=True)

    assert fresh["stale"] is False
    assert fresh["provider_id"] == "FTShare MCP"
    assert expired["stale"] is True
    assert expired["needs_external_refresh"] is True
    assert {item["symbol"] for item in expired["items"]} == {"600036.XSHG", "00700.HK"}


def test_ftshare_enum_translation_supports_long_intervals_and_adjustment() -> None:
    assert fetch._interval_to_sdk("quarter") == "Month"
    assert fetch._interval_to_sdk("year") == "Year"
    assert fetch._adjust_to_sdk("none") == "none"
    assert fetch._adjust_to_sdk("forward") == "forward"
    assert fetch._adjust_to_sdk("backward") == "backward"
    assert fetch._adjust_to_sdk("unknown") == "none"


def test_fetch_candles_rejects_unsupported_interval_before_provider_call() -> None:
    result = fetch.fetch_candles("00700.HK", interval="hour")

    assert result["ok"] is False
    assert result["error"] == "unsupported_interval"
    assert result["supported_intervals"] == ["day", "minute", "month", "quarter", "week", "year"]


def test_fetch_candles_rejects_malformed_symbol_before_provider_call() -> None:
    result = fetch.fetch_candles("NOT A SYMBOL", interval="day")

    assert result["ok"] is False
    assert result["error"] == "invalid_symbol"


def test_normalize_raw_unwraps_ftshare_service_envelope() -> None:
    raw = {
        "code": 200,
        "message": "success",
        "data": [
            {"ts_millis": 1_700_000_000_000, "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": 100},
            {"ts_millis": 1_700_086_400_000, "open": "10.5", "high": "12", "low": "10", "close": "11.5", "volume": 120},
        ],
    }

    rows = fetch._normalize_raw(raw)

    assert len(rows) == 2
    assert rows[0]["close"] == 10.5


def test_month_candles_aggregate_to_calendar_quarters() -> None:
    rows = [
        {"time": 1_704_067_200, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
        {"time": 1_706_745_600, "open": 11, "high": 13, "low": 10, "close": 12, "volume": 110},
        {"time": 1_709_251_200, "open": 12, "high": 14, "low": 11, "close": 13, "volume": 120},
    ]

    assert fetch._aggregate_quarters(rows) == [
        {"time": 1_709_251_200, "open": 10.0, "high": 14.0, "low": 9.0, "close": 13.0, "volume": 330.0}
    ]


def test_market_ticker_uses_available_global_sources(monkeypatch) -> None:
    class FakeMarket:
        def global_index_daily_kline(self, *, secid: str, as_dataframe: bool) -> list[dict[str, object]]:
            assert as_dataframe is False
            return [
                {"trade_date": "2026-07-27", "name": secid, "close": "100", "change_pct": "1.0", "change_amount": "1"},
                {"trade_date": "2026-07-28", "name": secid, "close": "102", "change_pct": "2.0", "change_amount": "2"},
            ]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_market_ticker()

    assert result["ok"] is True
    assert [item["market"] for item in result["items"]] == ["HK", "US"]
    assert result["items"][0]["change"] == 2.0
    assert result["status"] in {"delayed", "closed"}
    assert isinstance(result["updated_at"], int)
    assert {item["status"] for item in result["items"]} <= {"delayed", "closed"}


def test_candle_fetch_exposes_source_timestamp_and_market_status(monkeypatch) -> None:
    class FakeMarket:
        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["symbol"] == "600519.XSHG"
            assert kwargs["interval_unit"] == "Day"
            assert kwargs["adjust_kind"] == "none"
            assert kwargs["since_ts_millis"] < kwargs["until_ts_millis"]
            return [
                {"ts_millis": 1_700_000_000_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
                {"ts_millis": 1_700_086_400_000, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))
    fetch._candle_cache.clear()

    result = fetch.fetch_candles("600519.SH", limit=12)

    assert result["ok"] is True
    assert result["source"] == "ftshare"
    assert isinstance(result["updated_at"], int)
    assert result["status"] in {"delayed", "closed", "stale"}
    assert result["market_status"] in {"open", "closed"}
    assert result["exchange_timezone"] == "Asia/Shanghai"
    assert result["freshness"] == "derived_from_latest_candle"
    assert isinstance(result["as_of"], int)


def test_daily_history_pages_within_ftshare_twelve_month_limit(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMarket:
        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            page = len(calls)
            newest = 1_700_000_000_000 - (page - 1) * 200 * 86_400_000
            return [
                {
                    "ts_millis": newest - index * 86_400_000,
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "volume": 100,
                }
                for index in range(200)
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setattr(fetch, "_until_ms", lambda: 1_800_000_000_000)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))
    fetch._candle_cache.clear()
    try:
        result = fetch.fetch_candles("600519.XSHG", limit=300)
    finally:
        fetch._candle_cache.clear()

    assert result["ok"] is True
    assert result["count"] == 300
    assert len(calls) == 2
    assert all(
        int(call["until_ts_millis"]) - int(call["since_ts_millis"]) <= 360 * 86_400_000
        for call in calls
    )
    assert int(calls[1]["until_ts_millis"]) < int(calls[0]["until_ts_millis"])


def test_candle_fetch_retries_and_uses_recent_cache_on_transient_failure(monkeypatch) -> None:
    class HealthyMarket:
        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {"ts_millis": 1_700_000_000_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
                {"ts_millis": 1_700_086_400_000, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "缓存测试"}]

    class FailingMarket:
        calls = 0

        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            self.calls += 1
            raise RuntimeError("HTTP 503")

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    state: dict[str, object] = {"market": HealthyMarket()}
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setattr(fetch.time, "sleep", lambda _seconds: None)
    # Exercise the stale-fallback branch rather than the 45-second hot cache.
    monkeypatch.setattr(fetch, "_CANDLE_CACHE_FRESH_SECONDS", -1)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: state["market"]))
    fetch._candle_cache.clear()
    try:
        fresh = fetch.fetch_candles("CACHE.TEST", limit=12)
        assert fresh["ok"] is True

        failing_market = FailingMarket()
        state["market"] = failing_market
        fallback = fetch.fetch_candles("CACHE.TEST", limit=12)

        assert failing_market.calls == 2
        assert fallback["ok"] is True
        assert fallback["cached"] is True
        assert fallback["status"] == "stale"
        assert fallback["freshness"] == "recent_cached_fallback"
        assert fallback["rows"] == fresh["rows"]
    finally:
        fetch._candle_cache.clear()


def test_candle_fetch_reuses_larger_hot_cache_for_smaller_lookback(monkeypatch) -> None:
    class HealthyMarket:
        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {"ts_millis": 1_700_000_000_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
                {"ts_millis": 1_700_086_400_000, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    class FailingMarket:
        calls = 0

        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            self.calls += 1
            raise RuntimeError("HTTP 503")

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    state: dict[str, object] = {"market": HealthyMarket()}
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setattr(fetch.time, "sleep", lambda _seconds: None)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: state["market"]))
    fetch._candle_cache.clear()
    try:
        fresh = fetch.fetch_candles("CACHE.LARGE", limit=60)
        assert fresh["ok"] is True

        failing_market = FailingMarket()
        state["market"] = failing_market
        cached = fetch.fetch_candles("CACHE.LARGE", limit=24)

        assert failing_market.calls == 0
        assert cached["ok"] is True
        assert cached["cached"] is True
        assert cached["freshness"] == "recent_memory_cache"
        assert cached["cache_source_limit"] == 60
        assert cached["rows"] == fresh["rows"]
    finally:
        fetch._candle_cache.clear()


def test_broad_index_candles_fail_closed_without_stock_fallback(monkeypatch) -> None:
    class FakeMarket:
        stock_calls = 0
        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            self.stock_calls += 1
            raise AssertionError("broad indices must never fall back to a same-code stock")

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            raise AssertionError("known index identity must not use ambiguous vendor search")

    market = FakeMarket()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: market))
    result = fetch.fetch_candles("000688.SH", limit=60)

    assert result["ok"] is False
    assert result["error"] == "index_candles_provider_unavailable"
    assert result["symbol"] == "000688.XSHG"
    assert result["name"] == "科创50"
    assert market.stock_calls == 0


def test_bare_broad_index_code_requires_exchange_qualification(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "ftshare_available", lambda: False)

    result = fetch.fetch_candles("000688", limit=60)

    assert result["ok"] is False
    assert result["error"] == "ambiguous_symbol"
    assert result["index_candidate"] == {"symbol": "000688.XSHG", "name": "科创50", "market": "CN_INDEX"}


def test_explicit_stock_with_same_numeric_code_remains_stock(monkeypatch) -> None:
    class FakeMarket:
        stock_calls = 0

        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            self.stock_calls += 1
            assert kwargs["symbol"] == "000688.XSHE"
            return [
                {"ts_millis": 1_700_000_000_000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
                {"ts_millis": 1_700_086_400_000, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "国城矿业"}]

    market = FakeMarket()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: market))

    result = fetch.fetch_candles("000688.SZ", limit=12)

    assert result["ok"] is True
    assert result["symbol"] == "000688.XSHE"
    assert result["name"] == "国城矿业"
    assert market.stock_calls == 1


def test_us_candle_fetch_uses_dedicated_daily_history_endpoint(monkeypatch) -> None:
    class FakeMarket:
        def eastmoney_us_stock_daily_ohlc(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["stock_code"] == "NVDA"
            assert kwargs["all_pages"] is True
            assert kwargs["page_size"] == 200
            assert "start_date" not in kwargs
            assert "end_date" not in kwargs
            return [
                {"date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"date": "2024-01-03", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "NVIDIA"}]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("NVDA.US", limit=12)

    assert result["ok"] is True
    assert result["name"] == "NVIDIA"
    assert result["count"] == 2
    assert result["rows"][-1]["close"] == 11.5
    assert result["exchange_timezone"] == "America/New_York"


def test_search_symbols_keeps_amd_discoverable_when_vendor_search_is_empty(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    fetch._symbol_search_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.search_symbols("amd", limit=5)

    assert result["results"][0]["symbol"] == "AMD.US"


def test_us_candle_fetch_falls_back_when_dedicated_history_endpoint_is_unavailable(monkeypatch) -> None:
    class FakeMarket:
        generic_calls = 0

        def eastmoney_us_stock_daily_ohlc(self, **_kwargs: object) -> list[dict[str, object]]:
            raise RuntimeError("HTTP 500 upstream")

        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            self.generic_calls += 1
            assert kwargs["symbol"] == "NVDA.US"
            assert kwargs["interval_unit"] == "Day"
            return [
                {"ts_millis": 1_704_067_200_000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"ts_millis": 1_704_153_600_000, "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "NVIDIA"}]

    market = FakeMarket()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: market))

    result = fetch.fetch_candles("NVDA.US", limit=24)

    assert result["ok"] is True
    assert market.generic_calls == 1
    assert result["fallback"] == "generic_stock_candlesticks"
    assert "US daily history endpoint failed" in result["warning"]
    assert "HTTP 500" in result["upstream_error"]


def test_hk_candle_fetch_prefers_dedicated_history_endpoint(monkeypatch) -> None:
    latest = int(datetime.now(timezone.utc).timestamp())

    class FakeMarket:
        def hk_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["trade_code"] == "00700.HK"
            assert kwargs["interval_unit"] == "day"
            assert kwargs["adjust_kind"] == "none"
            assert kwargs["since_date"] < kwargs["until_date"]
            assert (datetime.fromisoformat(str(kwargs["until_date"])) - datetime.fromisoformat(str(kwargs["since_date"]))).days >= 20
            return [
                {"ts_millis": (latest - 86_400) * 1000, "open": 300, "high": 305, "low": 298, "close": 302, "volume": 100},
                {"ts_millis": latest * 1000, "open": 302, "high": 308, "low": 301, "close": 306, "volume": 120},
            ]

        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            raise AssertionError("HK daily history should use hk_candlesticks first")

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "腾讯控股"}]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("00700.HK", interval="day", limit=12)

    assert result["ok"] is True
    assert result["name"] == "腾讯控股"
    assert result["exchange_timezone"] == "Asia/Hong_Kong"
    assert result["count"] == 2
    fetch._candle_cache.clear()


def test_hk_candle_fetch_preserves_backward_adjustment(monkeypatch) -> None:
    latest = int(datetime.now(timezone.utc).timestamp())

    class FakeMarket:
        def hk_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["adjust_kind"] == "backward"
            return [
                {"ts_millis": (latest - 86_400) * 1000, "open": 300, "high": 305, "low": 298, "close": 302, "volume": 100},
                {"ts_millis": latest * 1000, "open": 302, "high": 308, "low": 301, "close": 306, "volume": 120},
            ]

    fetch._candle_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("00700.HK", interval="day", limit=12, adjust="backward")

    assert result["ok"] is True
    assert result["adjust"] == "backward"
    fetch._candle_cache.clear()


def test_hk_minute_fetch_reports_missing_provider_capability() -> None:
    result = fetch.fetch_candles("00700.HK", interval="minute", interval_value=5, session_count=1)

    assert result["ok"] is False
    assert result["error"] == "intraday_provider_unavailable"
    assert result["retryable"] is False


def test_hk_candle_fetch_rejects_stale_dedicated_history(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMarket:
        def hk_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            return [
                {"date": "2010-01-07", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"date": "2010-01-08", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
            ]

        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            assert kwargs["since_ts_millis"] < kwargs["until_ts_millis"]
            return []

    fetch._candle_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("00700.HK", interval="day", limit=12)

    assert result["ok"] is False
    assert result["error"] == "insufficient_candles"
    assert "stale or unavailable" in result["warning"]
    assert "2010-01-08" in result["upstream_error"]
    assert calls
    fetch._candle_cache.clear()


def test_us_local_calendar_aggregation_does_not_split_utc_month_boundary() -> None:
    rows = [
        {"time": int(datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc).timestamp()), "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1},
        {"time": int(datetime(2024, 1, 1, 4, 30, tzinfo=timezone.utc).timestamp()), "open": 10, "high": 12, "low": 8, "close": 11, "volume": 2},
    ]

    aggregated = fetch._aggregate_interval(rows, "month", timezone_name="America/New_York")

    assert len(aggregated) == 1
    assert aggregated[0]["open"] == 10
    assert aggregated[0]["close"] == 11
    assert aggregated[0]["volume"] == 3


def test_candle_freshness_marks_old_open_market_history_stale() -> None:
    rows = [{"time": int(datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc).timestamp())}]

    freshness = fetch._candle_freshness("NVDA.US", rows, now=datetime(2024, 1, 5, 16, 0, tzinfo=timezone.utc))

    assert freshness["status"] == "stale"
    assert freshness["exchange_timezone"] == "America/New_York"


def test_security_workspace_normalizes_ftshare_sections_without_blocking_on_missing_fields(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "招商银行"}]

        def semantic_search_news(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["query"] == "招商银行 600036.XSHG"
            return [{"title": "招商银行模拟资讯", "publish_time": "2026-07-29", "summary": "摘要", "url": "https://example.test/article", "article_id": "n-1"}]

        def income(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"report_date": "2026Q1", "total_revenue": 10_000_000_000, "net_profit": 2_000_000_000, "currency": "CNY"}]

        def stock_holders(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"holder_name": "模拟股东", "hold_ratio": 12.5, "hold_amount": 100_000_000, "report_date": "2026-03-31"}]

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_security_workspace("600036.XSHG")
    workspace = result["security_workspace"]

    assert result["ok"] is True
    assert workspace["news"][0]["title"] == "招商银行模拟资讯"
    assert workspace["news"][0]["source_url"] == "https://example.test/article"
    assert workspace["news"][0]["article_id"] == "n-1"
    assert workspace["financials"]["rows"][0][0] == "2026Q1"
    assert workspace["financials"]["unit"] == "CNY"
    assert workspace["holders"]["items"][0]["name"] == "模拟股东"


def test_security_workspace_pivots_ftshare_us_income_records(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "Apple"}]

        def semantic_search_news(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def us_basic(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["stock_code"] == "AAPL"
            return [{"stock_code": "AAPL", "name": "Apple", "list_date": "1980-12-12"}]

        def us_income(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["stock_code"] == "AAPL"
            assert kwargs["limit"] == 200
            return [
                {"end_date": "2026-03-28", "ind_type": "Q2", "ind_name": "revenue", "ind_value": "111184000000"},
                {"end_date": "2026-03-28", "ind_type": "Q2", "ind_name": "net_income", "ind_value": "29578000000"},
                {"end_date": "2026-03-28", "ind_type": "Q2", "ind_name": "basic_eps", "ind_value": "2.02"},
            ]

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    workspace = fetch.fetch_security_workspace("AAPL.US", name="Apple")["security_workspace"]

    assert workspace["financials"]["rows"][0][:3] == ["2026-03-28 Q2", "1111.84亿", "295.78亿"]
    assert workspace["overview"]["metrics"][:2] == [{"label": "营业收入", "value": "1111.84亿"}, {"label": "净利润", "value": "295.78亿"}]


def test_security_workspace_accepts_ftshare_wide_income_field_names(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "紫金矿业"}]

        def semantic_search_news(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def income(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"report_type_cn": "一季报", "t_revenue": 98_497_579_591, "n_profit": 25_165_728_674, "currency": "CNY"}]

        def stock_holders(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    workspace = fetch.fetch_security_workspace("601899.XSHG")["security_workspace"]

    assert workspace["financials"]["rows"][0][:3] == ["一季报", "984.98亿", "251.66亿"]
    assert workspace["overview"]["metrics"][:2] == [{"label": "营业收入", "value": "984.98亿"}, {"label": "净利润", "value": "251.66亿"}]
    assert workspace["sections"]["overview"]["state"] == "available"


def test_security_workspace_flattens_ftshare_holder_records_and_overview_metrics(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "紫金矿业"}]

        def semantic_search_news(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def income(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"report_type_cn": "一季报", "t_revenue": 100_000_000, "n_profit": 20_000_000}]

        def stock_holders(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"publish_date": "2026-03-31", "fen_holders": [{"shareholder_name": "第一大股东", "share_ratio": "22.5", "shareholding": 100_000_000, "change_percentage": "0.2"}]}]

        def balance(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"t_assets": 500_000_000, "asset_liability_ratio": "51.37"}]

        def cashflow(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"net_oper_cash_flow": 30_000_000}]

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    workspace = fetch.fetch_security_workspace("601899.XSHG")["security_workspace"]

    assert workspace["holders"]["items"][0]["name"] == "第一大股东"
    assert workspace["holders"]["items"][0]["percent"] == 22.5
    assert {item["label"] for item in workspace["overview"]["metrics"]} >= {"总资产", "资产负债率", "经营现金流"}


def test_security_workspace_expands_company_and_capital_structure_details(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "紫金矿业"}]

        def semantic_search_news(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def company_list(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"establish_date": "2000-09-06", "registered_capital": 2_000_000_000, "legal_representative": "模拟法人", "main_business": "矿产资源开发"}]

        def income(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"report_date": "2026Q1", "total_revenue": 100_000_000, "net_profit": 20_000_000, "revenue_yoy": 18.2, "roe": 9.6, "basic_eps": 0.42}]

        def stock_holders(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

        def balance(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"t_assets": 500_000_000, "t_liabilities": 150_000_000, "money_cap": 80_000_000, "inventories": 20_000_000}]

        def cashflow(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"net_oper_cash_flow": 30_000_000, "net_invest_cash_flow": -12_000_000, "cash_equ_end_period": 66_000_000}]

        def stock_holders_number(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"holder_count": 123_456, "holder_change": -2.5}]

        def stock_pledge_detail(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"pledge_ratio": 3.2, "pledge_shares": 12_000_000}]

        def stock_share_chg(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"change_date": "2026-05-12", "change_ratio": 0.18}]

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    details = fetch.fetch_security_workspace("601899.XSHG")["security_workspace"]["overview"]["details"]
    values = {item["label"]: item["value"] for item in details}
    groups = {item["label"]: item["group"] for item in details}

    assert values["成立日期"] == "2000-09-06"
    assert values["总负债"] == "1.50亿"
    assert values["股东户数"] == "12.35万"
    assert values["股份质押比例"] == "3.20%"
    assert values["最近增减持比例"] == "0.18%"
    assert groups["注册资本"] == "公司档案"
    assert groups["货币资金"] == "经营与资本结构"
    assert groups["股东户数"] == "股东与治理"


def test_hk_workspace_reports_unsupported_company_sections(monkeypatch) -> None:
    class FakeMarket:
        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "腾讯控股"}]

        def semantic_search_news(self, **_kwargs: object) -> list[dict[str, object]]:
            return []

    fetch._security_workspace_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    workspace = fetch.fetch_security_workspace("00700.HK")["security_workspace"]

    assert workspace["overview"]["market"] == "HK"
    assert workspace["sections"]["financials"]["state"] == "unsupported"
    assert workspace["sections"]["holders"]["state"] == "unsupported"


def test_comparison_broad_index_uses_same_safe_capability_error(monkeypatch) -> None:
    class FakeMarket:
        def stock_candlesticks(self, **_kwargs: object) -> list[dict[str, object]]:
            raise AssertionError("comparison index must not fall back to a stock")

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_comparison_candles("000300.SH", limit=12)

    assert result["ok"] is False
    assert result["error"] == "index_candles_provider_unavailable"
    assert result["symbol"] == "000300.XSHG"
    assert result["name"] == "沪深300"


def test_minute_fetch_uses_requested_interval_and_keeps_recent_sessions(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMarket:
        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            assert kwargs["since_ts_millis"] < kwargs["until_ts_millis"]
            assert kwargs["until_ts_millis"] - kwargs["since_ts_millis"] <= 2 * 86_400_000
            return [
                {"ts_millis": 1_720_740_400_000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"ts_millis": 1_720_826_800_000, "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 120},
                {"ts_millis": 1_720_913_200_000, "open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 140},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "测试股票"}]

    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setattr(fetch, "_latest_session_close_millis", lambda _tz: 1_721_000_000_000)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("600000.XSHG", interval="minute", interval_value=5, session_count=2, limit=260)

    assert result["ok"] is True
    assert result["interval"] == "minute"
    assert result["interval_value"] == 5
    assert result["session_count"] == 2
    assert calls[0]["interval_unit"] == "Minute"
    assert calls[0]["interval_value"] == 5
    assert len(result["rows"]) == 2
    assert len(result["rows"]) == 2
    assert result["source"] == "ftshare"
    assert result["market_status"] in {"open", "closed"}


def test_us_minute_fetch_preserves_open_time_and_extended_session_labels(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMarket:
        def stock_candlesticks(self, **kwargs: object) -> list[dict[str, object]]:
            calls.append(kwargs)
            assert kwargs["since_ts_millis"] < kwargs["until_ts_millis"]
            assert kwargs["until_ts_millis"] - kwargs["since_ts_millis"] <= 2 * 86_400_000
            return [
                # 2024-01-02 04:00--04:05, 09:30--09:35 and 16:00--16:05 ET.
                {"ts_millis_open": 1_704_186_000_000, "ts_millis": 1_704_186_300_000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
                {"ts_millis_open": 1_704_205_800_000, "ts_millis": 1_704_206_100_000, "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
                {"ts_millis_open": 1_704_229_200_000, "ts_millis": 1_704_229_500_000, "open": 11.5, "high": 13, "low": 11, "close": 12.5, "volume": 140},
            ]

        def search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"name": "NVIDIA"}]

    fetch._candle_cache.clear()
    monkeypatch.setattr(fetch, "ftshare_available", lambda: True)
    monkeypatch.setattr(fetch, "_latest_session_close_millis", lambda _tz: 1_704_240_000_000)
    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=lambda **_kwargs: FakeMarket()))

    result = fetch.fetch_candles("NVDA.US", interval="minute", interval_value=5, session_count=1, limit=240)

    assert result["ok"] is True
    assert calls[0]["interval_unit"] == "Minute"
    assert result["exchange_timezone"] == "America/New_York"
    assert [row["session"] for row in result["rows"]] == ["pre_market", "regular", "after_hours"]
    assert result["rows"][0]["open_time"] == 1_704_186_000
    assert result["timestamp_semantics"].startswith("time is bar close")
    fetch._candle_cache.clear()
