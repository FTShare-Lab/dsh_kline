import os
import asyncio
import stat
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.rows import RowsValidationError, normalize_rows
from chart_service import ChartService, _tool_dispatch
from server import _analysis_from_rows, _normalized_indicators, analyze_kline_rows
from tools.draw import draw_kline
from tools.fetch import (
    FT_CONTRACTS,
    _classify_ftshare_error,
    _ftshare_index_minutes,
    _ftshare_stock_candlesticks,
    _ftshare_market_api,
    _rows_from_directory_response,
    _symbol_name,
    configure_ftshare_api_key,
    fetch_candles,
    ftshare_index_kline_available,
    ftshare_status,
    search_symbols,
    test_ftshare_connection as run_ftshare_connection,
)


def sample_rows(count=30):
    return [
        {
            "time": (1_700_000_000 + index * 86_400) * 1000,
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "volume": 1000 + index,
        }
        for index in range(count)
    ]


class ProviderNeutralTests(unittest.TestCase):
    def test_external_rows_complete_workflow(self):
        with patch("server.publish_chart", return_value=("session-external", "http://127.0.0.1:8765")):
            result = _analysis_from_rows(
                sample_rows(),
                symbol="TEST.US",
                name="Test",
                interval="day",
                limit=20,
                adjust="none",
                indicators=["ma", "rsi"],
                metrics=["rsi"],
                mark_support_resistance=False,
                ma_periods=[5, 10],
                rsi_period=14,
                boll_period=20,
                boll_std=2.0,
                volume_ma=20,
                atr_period=14,
                data_source="user-feed",
                data_source_url="https://example.com/data",
                security_workspace=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_mode"], "external")
        self.assertEqual(result["workflow"], "provided_rows_analyze_chart_session")
        self.assertEqual(result["count"], 20)
        self.assertEqual(result["fetched_count"], 30)
        self.assertEqual(result["source"], "user-feed")
        self.assertTrue(result["chart_ready"])
        self.assertEqual(result["chart"]["session_id"], "session-external")

    def test_external_rows_accept_arbitrary_display_labels(self):
        async def run():
            with patch("server.publish_chart", return_value=("session-label", "http://127.0.0.1:8765")):
                return await analyze_kline_rows(
                    sample_rows(10),
                    symbol="TEST.X",
                    name="测试股",
                    interval="day",
                    limit=10,
                    indicators=["ma"],
                    metrics=["rsi"],
                )

        result = asyncio.run(run())
        self.assertTrue(result.structuredContent["ok"])
        self.assertEqual(result.structuredContent["symbol"], "TEST.X")
        self.assertEqual(result.structuredContent["name"], "测试股")

    def test_invalid_interval_returns_actionable_chinese_error(self):
        async def run():
            return await analyze_kline_rows(
                sample_rows(8), symbol="TEST.X", name="测试股", interval="1d", limit=8,
            )

        result = asyncio.run(run())
        payload = result.structuredContent
        self.assertTrue(result.isError)
        self.assertEqual(payload["error"], "unsupported_interval")
        self.assertEqual(payload["supported_intervals"], ["minute", "day", "week", "month", "quarter", "year"])
        self.assertIn("请选择", payload["message"])
        self.assertNotIn("pydantic", result.content[0].text.lower())
        self.assertNotIn("errors.pydantic.dev", result.content[0].text)

    def test_external_rows_bypass_ftshare_adapter(self):
        async def run():
            with patch("server.publish_chart", return_value=("session-bypass", "http://127.0.0.1:8765")), patch(
                "tools.fetch._ftshare_market_api", side_effect=AssertionError("rows must not fetch FTShare")
            ), patch(
                "tools.fetch.configure_ftshare_api_key", side_effect=AssertionError("rows must not configure FTShare")
            ), patch(
                "tools.fetch.search_symbols", side_effect=AssertionError("rows must not search FTShare")
            ), patch(
                "server.fetch_candles", side_effect=AssertionError("rows must not use provider fetch")
            ), patch(
                "server.search_symbol_directory", side_effect=AssertionError("rows must not resolve symbols")
            ):
                return await analyze_kline_rows(
                    sample_rows(8), symbol="BTCUSDT", name="外部数据", interval="day", limit=8,
                    indicators=["ma"], metrics=["rsi"],
                )

        result = asyncio.run(run())
        self.assertTrue(result.structuredContent["ok"])
        self.assertEqual(result.structuredContent["provider_mode"], "external")

    def test_normalize_rejects_non_finite_ohlcv(self):
        rows = sample_rows(3)
        rows[1]["close"] = float("nan")
        self.assertEqual(len(normalize_rows(rows)), 2)
        with self.assertRaises(RowsValidationError):
            _analysis_from_rows(
                rows[:1], symbol="TEST", name=None, interval="day", limit=60, adjust="none",
                indicators=None, metrics=None, mark_support_resistance=False, ma_periods=None,
                rsi_period=14, boll_period=20, boll_std=2.0, volume_ma=20, atr_period=14,
                data_source=None, data_source_url=None, security_workspace=None,
            )

    def test_search_uses_cached_directory_without_api_key(self):
        cached = {
            "version": 4,
            "items": [{"symbol": "601899.XSHG", "name": "紫金矿业", "market": "CN"}],
        }
        with patch.dict("os.environ", {"FTSHARE_API_KEY": ""}, clear=False), patch(
            "tools.fetch._read_symbol_directory_cache", return_value=cached
        ):
            result = search_symbols("紫金矿业")
        self.assertEqual(result["results"][0]["symbol"], "601899.XSHG")
        self.assertEqual(result["source"], "directory")

    def test_directory_name_matches_canonical_mainland_symbol(self):
        cached = {
            "version": 4,
            "items": [{"symbol": "600021", "name": "上海电力", "market": "CN"}],
        }
        with patch("tools.fetch._read_symbol_directory_cache", return_value=cached):
            self.assertEqual(_symbol_name(None, "600021.XSHG"), "上海电力")

    def test_chart_service_requires_internal_token(self):
        service = ChartService("127.0.0.1", 0)
        session = service.store.create({"symbol": "TEST.US"})
        url = f"http://127.0.0.1:{service.port}/api/session/{session}"
        try:
            with self.assertRaises(HTTPError) as blocked:
                urlopen(url, timeout=2)
            self.assertEqual(blocked.exception.code, 401)

            request = Request(url, headers={"X-DSH-Kline-Token": service.auth_token})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
        finally:
            service.httpd.shutdown()
            service.httpd.server_close()

    def test_ftshare_runtime_configuration_never_returns_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"FTSHARE_API_KEY_FILE": str(Path(directory) / "credentials.json")}, clear=True
        ):
            configured = configure_ftshare_api_key("  test-key  ", test_connection=False)
            self.assertTrue(configured["ok"])
            self.assertTrue(configured["configured"])
            self.assertTrue(configured["persistent"])
            self.assertNotIn("test-key", str(configured))
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "test-key")
            credential_file = Path(directory) / "credentials.json"
            self.assertEqual(stat.S_IMODE(credential_file.stat().st_mode), 0o600)

            os.environ.pop("FTSHARE_API_KEY")
            loaded = ftshare_status()
            self.assertTrue(loaded["configured"])
            self.assertTrue(loaded["persistent"])

            cleared = configure_ftshare_api_key("", test_connection=False)
            self.assertTrue(cleared["ok"])
            self.assertFalse(cleared["configured"])
            self.assertFalse(credential_file.exists())
            self.assertNotIn("FTSHARE_API_KEY", os.environ)

    def test_ftshare_status_never_exposes_host_details(self):
        with patch.dict("os.environ", {"DSH_KLINE_DEBUG": "1"}, clear=False), patch(
            "tools.fetch.ftshare_available", return_value=False
        ):
            status = ftshare_status()
        for field in ("python", "injected_path", "module_file", "import_error"):
            self.assertNotIn(field, status)

    def test_temporary_ftshare_key_keeps_the_saved_credential(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"FTSHARE_API_KEY_FILE": str(Path(directory) / "credentials.json")}, clear=True
        ):
            configure_ftshare_api_key("saved-key", test_connection=False, persist=True)
            credential_file = Path(directory) / "credentials.json"
            configure_ftshare_api_key("temporary-key", test_connection=False, persist=False)
            self.assertTrue(credential_file.exists())
            os.environ.pop("FTSHARE_API_KEY")
            self.assertTrue(ftshare_status()["persistent"])

    def test_ftshare_persisted_key_lifecycle_after_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"FTSHARE_API_KEY_FILE": str(Path(directory) / "credentials.json")}, clear=True
        ), patch(
            "tools.fetch.test_ftshare_connection",
            return_value={"ok": True, "message": "FTShare 连接成功", "configured": True},
        ):
            configured = configure_ftshare_api_key("lifecycle-key", test_connection=True, persist=True)
            self.assertTrue(configured["ok"])
            self.assertTrue(configured["key_saved"])
            self.assertTrue(configured["connection_ok"])
            self.assertTrue(configured["persistent"])
            self.assertNotIn("lifecycle-key", str(configured))

            os.environ.pop("FTSHARE_API_KEY")
            loaded = ftshare_status()
            self.assertTrue(loaded["configured"])
            self.assertTrue(loaded["persistent"])

            cleared = configure_ftshare_api_key("", test_connection=False)
            self.assertTrue(cleared["ok"])
            self.assertFalse(cleared["configured"])
            self.assertFalse(Path(directory, "credentials.json").exists())

    def test_ftshare_key_is_attached_to_sdk_requests(self):
        captured = {}

        def market_api(**kwargs):
            captured.update(kwargs)
            return object()

        fake_ftshare = SimpleNamespace(market_api=market_api)
        with patch.dict("os.environ", {"FTSHARE_API_KEY": "header-test-key"}, clear=False), patch.dict(
            "sys.modules", {"ftshare": fake_ftshare}
        ):
            _ftshare_market_api(timeout=3)
        self.assertEqual(captured["headers"], {"FTSHARE_API_KEY": "header-test-key"})

    def test_ftshare_connection_classifies_invalid_key_and_persists_state(self):
        class FakeMarket:
            def stock_candlesticks(self, **kwargs):
                raise RuntimeError("HTTP 401: API Key 格式非法")

        fake_ftshare = SimpleNamespace(market_api=lambda **kwargs: FakeMarket())
        with patch.dict("os.environ", {"FTSHARE_API_KEY": "bad-key"}, clear=False), patch(
            "tools.fetch.ftshare_available", return_value=True
        ), patch.dict("sys.modules", {"ftshare": fake_ftshare}):
            result = run_ftshare_connection()
        self.assertEqual(result["error"], "invalid_key")
        self.assertIn("校验失败", result["message"])
        self.assertEqual(_classify_ftshare_error(RuntimeError("HTTP 401: missing API Key"))[0], "auth_required")

    def test_ftshare_connection_separates_key_validity_from_minute_access(self):
        calls = []

        class FakeMarket:
            def stock_candlesticks(self, **kwargs):
                calls.append(kwargs["interval_unit"])
                if kwargs["interval_unit"] == "Minute":
                    raise RuntimeError("HTTP 403: 当前套餐无分钟行情权限")
                return [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]

        fake_ftshare = SimpleNamespace(market_api=lambda **kwargs: FakeMarket())
        with patch.dict("os.environ", {"FTSHARE_API_KEY": "free-tier-key"}, clear=False), patch(
            "tools.fetch.ftshare_available", return_value=True
        ), patch.dict("sys.modules", {"ftshare": fake_ftshare}):
            result = run_ftshare_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["capabilities"]["daily"], "available")
        self.assertEqual(result["capabilities"]["minute"], "insufficient_quota")
        self.assertIn("分钟", result["message"])
        self.assertIn("升级", result["message"])
        self.assertNotIn("free-tier-key", str(result))
        self.assertEqual(calls, ["Day", "Minute"])

    def test_ftshare_contract_falls_back_after_method_not_allowed(self):
        calls = []

        class FakeMarket:
            def get(self, path, **kwargs):
                calls.append(("http_get", path))
                raise RuntimeError("HTTP 405: method not allowed")

            def stock_candlesticks(self, **kwargs):
                calls.append(("sdk", kwargs["interval_unit"]))
                return [{"time": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1}]

        with patch("tools.fetch._FTSHARE_TRANSPORT_STATE", {}):
            result = _ftshare_stock_candlesticks(
                FakeMarket(), symbol="600519.XSHG", interval_unit="Day", interval_value=1,
                adjust_kind="none", since_ts_millis=0, until_ts_millis=2, limit=2,
                as_dataframe=False,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(calls, [("http_get", "api/v1/market/data/stock-candlesticks"), ("sdk", "Day")])

    def test_ftshare_103_contract_metadata_matches_official_tiers(self):
        self.assertEqual({spec["verified_sdk_version"] for spec in FT_CONTRACTS.values()}, {"1.0.3"})
        self.assertEqual(FT_CONTRACTS["daily_candles"]["tier"], "free")
        self.assertEqual(FT_CONTRACTS["index_daily_candles"]["tier"], "free")
        self.assertEqual(FT_CONTRACTS["history_minute_candles"]["tier"], "base+")
        self.assertEqual(FT_CONTRACTS["index_history_minute_candles"]["tier"], "base+")
        self.assertEqual(
            FT_CONTRACTS["index_history_minute_candles"]["doc"],
            "https://market.ft.tech/gateway/doc/p/ls85mq5n",
        )

    def test_installed_ftshare_103_sdk_surface_matches_registered_contracts(self):
        from importlib.metadata import version

        import ftshare
        from ftshare.config import DEFAULT_BASE_URL
        from ftshare.endpoints import ENDPOINTS

        self.assertEqual(version("ftshare"), "1.0.3")
        self.assertEqual(DEFAULT_BASE_URL, "https://market.ft.tech/gateway/")
        expected_paths = {
            "stock_candlesticks": "api/v1/market/data/stock-candlesticks",
            "stock_minutes": "api/v2/market/data/stock_minutes",
            "index_candlesticks": "api/v1/market/data/index-candlesticks",
            "index_minutes": "api/v2/market/data/index_minutes",
            "hk_candlesticks": "api/v2/market/data/hk/hk-candlesticks",
            "eastmoney_us_stock_list": "api/v1/market/data/eastmoney-us-stock-list",
            "eastmoney_us_stock_daily_ohlc": "api/v1/market/data/eastmoney-us-stock-daily-ohlc",
        }
        client = ftshare.market_api(timeout=1)
        for method_name, path in expected_paths.items():
            self.assertEqual(ENDPOINTS[method_name].path, path)
            self.assertTrue(callable(getattr(client, method_name, None)))

    def test_index_minutes_uses_103_contract_shape(self):
        calls = []

        class FakeMarket:
            def index_minutes(self, **kwargs):
                calls.append(kwargs)
                return []

        _ftshare_index_minutes(
            FakeMarket(),
            symbol="000300.XSHG",
            interval_value=5,
            adjust_kind="none",
            since_ts_millis=1,
            until_ts_millis=2,
            limit=50,
            as_dataframe=False,
        )
        self.assertEqual(
            calls,
            [{
                "symbol": "000300.SH",
                "interval_value": 5,
                "since_ts_millis": 1,
                "until_ts_millis": 2,
                "limit": 50,
                "as_dataframe": False,
            }],
        )

    def test_ftshare_103_nested_directory_envelope_is_unwrapped(self):
        payload = {
            "code": 200,
            "message": "success",
            "data": {
                "code": 200,
                "message": "success",
                "data": {"records": [{"symbol": "000300.SZ", "name": "沪深300"}]},
            },
        }
        self.assertEqual(
            _rows_from_directory_response(payload),
            [{"symbol": "000300.SZ", "name": "沪深300"}],
        )

    def test_ftshare_contract_does_not_switch_transport_on_auth_failure(self):
        calls = []

        class FakeMarket:
            def get(self, path, **kwargs):
                calls.append("http_get")
                raise RuntimeError("HTTP 403: 当前套餐无权限")

            def stock_candlesticks(self, **kwargs):
                calls.append("sdk")
                return []

        with patch("tools.fetch._FTSHARE_TRANSPORT_STATE", {}):
            with self.assertRaises(RuntimeError):
                _ftshare_stock_candlesticks(FakeMarket(), symbol="600519.XSHG", interval_unit="Day")
        self.assertEqual(calls, ["http_get"])

    def test_ftshare_contract_retries_rate_limit_on_same_transport(self):
        calls = []

        class FakeMarket:
            def get(self, path, **kwargs):
                calls.append("http_get")
                if len(calls) < 3:
                    raise RuntimeError("HTTP 429: too many requests")
                return [{"time": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1}]

        with patch("tools.fetch._FTSHARE_TRANSPORT_STATE", {}), patch("tools.fetch.time.sleep") as sleeper:
            result = _ftshare_stock_candlesticks(FakeMarket(), symbol="600519.XSHG", interval_unit="Day")
        self.assertEqual(len(result), 1)
        self.assertEqual(calls, ["http_get", "http_get", "http_get"])
        self.assertEqual(sleeper.call_count, 2)

    def test_ftshare_rate_limit_does_not_fallback_after_retries(self):
        calls = []

        class FakeMarket:
            def get(self, path, **kwargs):
                calls.append("http_get")
                raise RuntimeError("HTTP 429: too many requests")

            def stock_candlesticks(self, **kwargs):
                calls.append("sdk")
                return []

        with patch("tools.fetch._FTSHARE_TRANSPORT_STATE", {}), patch("tools.fetch.time.sleep"):
            with self.assertRaises(RuntimeError):
                _ftshare_stock_candlesticks(FakeMarket(), symbol="600519.XSHG", interval_unit="Day")
        self.assertEqual(calls, ["http_get", "http_get", "http_get"])

    def test_ftshare_configuration_reports_saved_key_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"FTSHARE_API_KEY_FILE": str(Path(directory) / "credentials.json")}, clear=True
        ), patch(
            "tools.fetch.test_ftshare_connection",
            return_value={"ok": False, "error": "invalid_key", "message": "FTShare API Key 校验失败"},
        ):
            result = configure_ftshare_api_key("bad-key", test_connection=True, persist=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["key_saved"])
        self.assertTrue(result["persistent"])
        self.assertIn("已保存", result["message"])

    def test_chart_service_routes_data_source_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"FTSHARE_API_KEY_FILE": str(Path(directory) / "credentials.json")}, clear=True
        ):
            status = _tool_dispatch("data_source_status", {})
            self.assertTrue(status["ok"])
            self.assertIn("ftshare", status["providers"])
            configured = _tool_dispatch("configure_ftshare", {"api_key": "route-test-key", "test_connection": False})
            self.assertTrue(configured["ok"])
            self.assertTrue(configured["configured"])
            self.assertTrue(configured["persistent"])
            self.assertNotIn("route-test-key", str(configured))
            _tool_dispatch("configure_ftshare", {"api_key": "", "test_connection": False})


class ChartApiAnalyzeTests(unittest.TestCase):
    """analyze_kline over the loopback chart API (key-level re-analysis)."""

    @staticmethod
    def wavy_rows(count=140):
        up = [100, 103, 106, 109, 112, 115, 118, 120]
        seq = []
        index = 0
        while len(seq) < count:
            chunk = up if index % 2 == 0 else list(reversed(up))
            seq.extend(chunk)
            index += 1
        seq = seq[:count]
        rows = []
        for idx, close in enumerate(seq):
            previous = seq[idx - 1] if idx else close
            rows.append(
                {
                    "time": 1_700_000_000 + idx * 86_400,
                    "open": previous,
                    "high": max(previous, close) + 1.0,
                    "low": min(previous, close) - 1.0,
                    "close": close,
                    "volume": 1000 + idx,
                }
            )
        return rows

    @staticmethod
    def canned_fetch(symbol, **kwargs):
        return {
            "ok": True,
            "symbol": symbol,
            "name": "贵州茅台" if symbol == "600519.XSHG" else symbol,
            "interval": kwargs.get("interval", "day"),
            "interval_value": kwargs.get("interval_value", 1),
            "session_count": kwargs.get("session_count"),
            "adjust": kwargs.get("adjust", "none"),
            "source": "canned",
            "rows": ChartApiAnalyzeTests.wavy_rows(),
        }

    def test_chart_api_analyze_kline_returns_level_markers(self):
        with patch("chart_service.fetch_candles", side_effect=self.canned_fetch):
            result = _tool_dispatch(
                "analyze_kline",
                {
                    "symbol": "600519.XSHG",
                    "interval": "day",
                    "limit": 60,
                    "indicators": ["ma", "vol"],
                    "metrics": ["support_resistance"],
                    "mark_support_resistance": True,
                },
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["symbol"], "600519.XSHG")
        commands = result.get("chartCommands")
        self.assertIsInstance(commands, list)
        kinds = [command.get("type") for command in commands]
        self.assertIn("SET_CANDLES", kinds)
        self.assertIn("TEXT_MARKER", kinds)
        markers = [command for command in commands if command.get("type") == "TEXT_MARKER"]
        self.assertTrue(markers, "support/resistance request must emit TEXT_MARKER commands")
        self.assertTrue(all(marker.get("text") and marker.get("time") for marker in markers))
        self.assertTrue(any("支撑" in marker.get("text", "") for marker in markers))
        self.assertGreater(result["count"], 0)

    def test_chart_api_analyze_kline_validates_before_fetch(self):
        calls = []
        with patch("chart_service.fetch_candles", side_effect=lambda *a, **k: calls.append(a) or {}):
            result = _tool_dispatch("analyze_kline", {"symbol": "600519.XSHG", "interval": "1d", "limit": 60})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_interval")
        self.assertEqual(calls, [])

    def test_chart_api_analyze_kline_passes_fetch_errors_through(self):
        with patch(
            "chart_service.fetch_candles",
            return_value={"ok": False, "error": "provider_unavailable", "message": "temporarily unavailable"},
        ):
            result = _tool_dispatch("analyze_kline", {"symbol": "600519.XSHG", "interval": "day", "limit": 60})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "provider_unavailable")

    def test_data_source_status_reports_index_kline_capability(self):
        with patch("chart_service.ftshare_index_kline_available", return_value=False):
            status = _tool_dispatch("data_source_status", {})
        self.assertTrue(status["ok"])
        ftshare = status["providers"]["ftshare"]
        self.assertIn("index_kline", ftshare)
        self.assertFalse(ftshare["index_kline"])

    def test_index_kline_capability_defaults_to_available_with_sdk_1(self):
        self.assertTrue(ftshare_index_kline_available())

    def test_fetch_candles_serves_ashare_index_daily(self):
        import time as _time

        now = int(_time.time() * 1000)
        rows = [
            {
                "ts_millis": now - index * 86_400_000,
                "ts_millis_open": now - index * 86_400_000 - 8 * 3_600_000,
                "open": str(4000 + index * 0.5),
                "high": str(4000 + index * 0.5 + 10),
                "low": str(4000 + index * 0.5 - 10),
                "close": str(4000 + index * 0.5 + 1),
                "volume": 12_345_678,
                "turnover": "1234567890",
            }
            for index in range(60, 0, -1)
        ]

        def fake_index(market, **params):
            return {"code": 200, "message": "success", "data": rows}

        with patch("tools.fetch.ftshare_available", return_value=True), patch(
            "tools.fetch._ftshare_market_api", return_value=SimpleNamespace()
        ), patch("tools.fetch._ftshare_index_candlesticks", side_effect=fake_index), patch(
            "tools.fetch._recent_candle_cache", return_value=None
        ), patch("tools.fetch._cached_candle_fallback", return_value=None):
            result = fetch_candles("000300.XSHG", interval="day", limit=5, adjust="none")
        self.assertTrue(result.get("ok"), str(result.get("error")))
        self.assertEqual(result["symbol"], "000300.XSHG")
        self.assertGreaterEqual(len(result.get("rows") or []), 2)

    def test_default_indicator_stack_is_calm(self):
        active, unknown = _normalized_indicators(None)
        self.assertEqual(active, ["ma", "vol", "macd"])
        self.assertEqual(unknown, [])

    def test_draw_payload_marks_indicator_explicitness(self):
        implicit = draw_kline(self.wavy_rows(24), indicators=["ma", "vol", "macd"], symbol="TEST.X", name="Test")
        self.assertIs(implicit["indicators_explicit"], False)
        explicit = draw_kline(self.wavy_rows(24), indicators=["ma", "boll"], indicators_explicit=True, symbol="TEST.X", name="Test")
        self.assertIs(explicit["indicators_explicit"], True)


if __name__ == "__main__":
    unittest.main()
