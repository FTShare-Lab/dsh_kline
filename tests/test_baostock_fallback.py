import json
import subprocess
import unittest
from unittest.mock import patch

from tools.baostock_source import _normalize_rows, eligible_stock_code, fetch_stock_daily
from tools.fetch import fetch_candles


RAW = [
    ["2026-10-26", "sh.600519", "10", "12", "9", "11", "100"],
    ["2026-10-27", "sh.600519", "11", "13", "10", "12", "120"],
]


class BaoStockFallbackTests(unittest.TestCase):
    def test_only_explicit_shenzhen_shanghai_equities_are_eligible(self):
        self.assertEqual(eligible_stock_code("600519.XSHG"), "sh.600519")
        self.assertEqual(eligible_stock_code("000001.XSHE"), "sz.000001")
        for symbol in ("600519", "000001.XSHG", "399001.XSHE", "510300.XSHG", "159919.XSHE", "AAPL.US", "830799.BJSE"):
            self.assertIsNone(eligible_stock_code(symbol), symbol)

    def test_rejects_wrong_identity_and_invalid_prices(self):
        self.assertEqual(len(_normalize_rows(RAW, "sh.600519")), 2)
        self.assertEqual(_normalize_rows([RAW[0], [*RAW[1][:1], "sh.600000", *RAW[1][2:]]], "sh.600519"), [])
        invalid = [*RAW[1]]
        invalid[3] = "8"
        self.assertEqual(_normalize_rows([RAW[0], invalid], "sh.600519"), [])

    def test_bounded_worker_and_adjustment_request(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({"rows": RAW}), "")
        with patch.dict("tools.baostock_source.os.environ", {"FTSHARE_API_KEY": "test-only-secret"}), patch(
            "tools.baostock_source.subprocess.run", return_value=response
        ) as run:
            rows = fetch_stock_daily("600519.XSHG", limit=2, adjust="forward")
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["adjustflag"], "2")
        self.assertEqual(run.call_args.kwargs["timeout"], 12)
        self.assertNotIn("FTSHARE_API_KEY", run.call_args.kwargs["env"])
        with patch("tools.baostock_source.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 12)):
            self.assertIsNone(fetch_stock_daily("600519.XSHG", limit=2, adjust="none"))

    def test_no_key_uses_free_stock_without_calling_ftshare(self):
        rows = _normalize_rows(RAW, "sh.600519")
        with patch("tools.fetch._ftshare_credential_source", return_value="none"), patch(
            "tools.fetch.fetch_stock_daily", return_value=rows
        ), patch("tools.fetch._fetch_candles_ftshare") as primary:
            result = fetch_candles("600519.XSHG", limit=2, adjust="forward")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "baostock_free")
        self.assertEqual(result["instrument_type"], "stock")
        self.assertEqual(result["adjust"], "forward")
        self.assertEqual(result["count"], 2)
        self.assertNotIn("fallback_from", result)
        primary.assert_not_called()

    def test_configured_ftshare_success_wins_and_failure_falls_back(self):
        rows = _normalize_rows(RAW, "sh.600519")
        with patch("tools.fetch._ftshare_credential_source", return_value="plugin_store"), patch(
            "tools.fetch.fetch_stock_daily", return_value=rows
        ) as fallback, patch("tools.fetch._fetch_candles_ftshare", return_value={"ok": True, "source": "ftshare", "rows": rows}):
            self.assertEqual(fetch_candles("600519.XSHG", limit=2)["source"], "ftshare")
            fallback.assert_not_called()
        with patch("tools.fetch._ftshare_credential_source", return_value="plugin_store"), patch(
            "tools.fetch.fetch_stock_daily", return_value=rows
        ), patch("tools.fetch._fetch_candles_ftshare", return_value={"ok": False, "error": "rate_limited"}):
            result = fetch_candles("600519.XSHG", limit=2)
            self.assertEqual(result["source"], "baostock_free")
            self.assertEqual(result["fallback_from"], "ftshare")

    def test_no_key_free_stock_failure_reports_actual_source(self):
        with patch("tools.fetch._ftshare_credential_source", return_value="none"), patch(
            "tools.fetch.fetch_stock_daily", return_value=None
        ), patch(
            "tools.fetch.fetch_tencent_stock_daily", return_value=None
        ), patch("tools.fetch._fetch_candles_ftshare") as primary, patch(
            "tools.fetch._free_index_candles_result", return_value=None
        ):
            result = fetch_candles("600519.XSHG", limit=120)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "free_stock_unavailable")
        self.assertEqual(result["attempted_sources"], ["baostock_free", "tencent_free"])
        self.assertFalse(result["ftshare_key_configured"])
        self.assertNotIn("rows", result)
        primary.assert_not_called()

    def test_tencent_follows_baostock_for_anonymous_stock_history(self):
        rows = [
            {"time": 1, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0},
            {"time": 2, "open": 11.0, "high": 13.0, "low": 10.0, "close": 12.0, "volume": 120.0},
        ]
        with patch("tools.fetch._ftshare_credential_source", return_value="none"), patch(
            "tools.fetch.fetch_stock_daily", return_value=None
        ), patch("tools.fetch.fetch_tencent_stock_daily", return_value=rows) as tencent, patch(
            "tools.fetch._fetch_candles_ftshare"
        ) as primary:
            result = fetch_candles("600519.XSHG", limit=2, adjust="forward")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "tencent_free")
        self.assertEqual(result["adjust"], "forward")
        self.assertEqual(result["source_url"], "https://qt.gtimg.cn")
        tencent.assert_called_once()
        primary.assert_not_called()

    def test_no_fallback_for_minutes_indices_etfs_or_unsupported_markets(self):
        with patch("tools.fetch._ftshare_credential_source", return_value="none"), patch(
            "tools.fetch.fetch_stock_daily"
        ) as fallback, patch("tools.fetch._fetch_candles_ftshare", return_value={"ok": False, "error": "unavailable"}), patch(
            "tools.fetch._free_index_candles_result", return_value=None
        ):
            for symbol, interval in (("600519.XSHG", "minute"), ("000001.XSHG", "day"), ("510300.XSHG", "day"), ("00700.HK", "day")):
                self.assertFalse(fetch_candles(symbol, interval=interval)["ok"])
            fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
