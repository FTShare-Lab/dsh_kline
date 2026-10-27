import unittest
from unittest.mock import patch

from tools.fetch import fetch_candles


class FtshareKeyGuidanceTests(unittest.TestCase):
    def test_anonymous_stock_failure_exposes_only_key_presence(self):
        with patch("tools.fetch._fetch_candles_ftshare", return_value={
            "ok": False, "error": "rate_limited", "error_code": "rate_limited",
            "message": "Too many requests", "source": "ftshare",
        }), patch("tools.fetch._free_index_candles_result", return_value=None), patch(
            "tools.fetch._ftshare_credential_source", return_value="none"
        ):
            result = fetch_candles("600519.XSHG")
        self.assertFalse(result["ok"])
        self.assertIs(result["ftshare_key_configured"], False)
        self.assertNotIn("credential_source", result)

    def test_configured_rate_limit_is_not_reported_as_missing_key(self):
        with patch("tools.fetch._fetch_candles_ftshare", return_value={
            "ok": False, "error": "rate_limited", "error_code": "rate_limited",
            "message": "Too many requests", "source": "ftshare",
        }), patch("tools.fetch._free_index_candles_result", return_value=None), patch(
            "tools.fetch._ftshare_credential_source", return_value="plugin_store"
        ):
            result = fetch_candles("600519.XSHG")
        self.assertIs(result["ftshare_key_configured"], True)

    def test_index_fallback_keeps_its_own_source_identity(self):
        with patch("tools.fetch._fetch_candles_ftshare", return_value={
            "ok": False, "error": "rate_limited", "source": "ftshare",
        }), patch("tools.fetch._free_index_candles_result", return_value={
            "ok": True, "source": "tencent_free", "rows": [{"time": 1}],
        }), patch("tools.fetch._ftshare_credential_source", return_value="none"):
            result = fetch_candles("000300.XSHG")
        self.assertEqual(result["source"], "tencent_free")
        self.assertNotIn("ftshare_key_configured", result)


if __name__ == "__main__":
    unittest.main()
