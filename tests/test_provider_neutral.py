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
from server import _analysis_from_rows, analyze_kline_rows
from tools.fetch import (
    _classify_ftshare_error,
    _ftshare_stock_candlesticks,
    _ftshare_market_api,
    _symbol_name,
    configure_ftshare_api_key,
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


if __name__ == "__main__":
    unittest.main()
