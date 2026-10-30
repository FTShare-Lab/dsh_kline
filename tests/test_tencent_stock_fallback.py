from unittest.mock import patch

from tools.free_sources import fetch_tencent_index_daily, fetch_tencent_stock_daily


def _payload(series, rows):
    return {"data": {"sh600313": {series: rows}}}


def test_tencent_stock_daily_uses_the_exact_requested_adjustment_series():
    qfq = [
        ["2026-10-29", "10", "11", "12", "9", "100"],
        ["2026-10-30", "11", "12", "13", "10", "120"],
    ]
    with patch("tools.free_sources._http_get_json", return_value=_payload("qfqday", qfq)) as request:
        rows = fetch_tencent_stock_daily("600313.XSHG", limit=2, adjust="forward")
    assert rows and [row["close"] for row in rows] == [11.0, 12.0]
    assert ",qfq" in request.call_args.args[0]


def test_tencent_stock_daily_uses_unadjusted_day_and_rejects_unsupported_identity():
    day = [
        ["2026-10-29", "10", "11", "12", "9", "100"],
        ["2026-10-30", "11", "12", "13", "10", "120"],
    ]
    with patch("tools.free_sources._http_get_json", return_value=_payload("day", day)) as request:
        rows = fetch_tencent_stock_daily("600313.XSHG", limit=2, adjust="none")
    assert rows and rows[-1]["close"] == 12.0
    assert request.call_args.args[0].endswith(",")
    assert fetch_tencent_stock_daily("600313", limit=2, adjust="none") is None
    assert fetch_tencent_stock_daily("000300.XSHG", limit=2, adjust="none") is None
    assert fetch_tencent_stock_daily("510300.XSHG", limit=2, adjust="none") is None


def test_tencent_stock_daily_uses_backward_adjustment_only_when_requested():
    hfq = [
        ["2026-10-29", "100", "110", "120", "90", "100"],
        ["2026-10-30", "110", "120", "130", "100", "120"],
    ]
    with patch("tools.free_sources._http_get_json", return_value=_payload("hfqday", hfq)) as request:
        rows = fetch_tencent_stock_daily("600313.XSHG", limit=2, adjust="backward")
    assert rows and rows[-1]["close"] == 120.0
    assert request.call_args.args[0].endswith(",hfq")


def test_tencent_index_accepts_its_verified_day_response_shape():
    day = [
        ["2026-10-29", "3800", "3810", "3820", "3790", "100"],
        ["2026-10-30", "3810", "3820", "3830", "3800", "120"],
    ]
    with patch("tools.free_sources._http_get_json", return_value=_payload("day", day)):
        rows = fetch_tencent_index_daily("000001.XSHG", limit=2)
    assert rows and rows[-1]["close"] == 3820.0
