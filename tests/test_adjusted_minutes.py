"""Minute adjustment routing with distinct raw/adjusted fixtures, no live provider I/O."""
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import tools.fetch as fetch


@pytest.fixture
def minute_market():
    zone = ZoneInfo("Asia/Shanghai")
    day = datetime(2026, 9, 7, 9, 30, tzinfo=zone)
    opens = [day + timedelta(minutes=i) for i in range(120)] + [day.replace(hour=13, minute=0) + timedelta(minutes=i) for i in range(120)]
    def rows(base):
        return [{"time": int((t + timedelta(minutes=1)).timestamp()), "open_time": int(t.timestamp()),
                 "open": base, "high": base + 1, "low": base - 1, "close": base + .5, "volume": 100} for t in opens]
    calls = []
    class Market:
        realtime_unavailable = False
        def stock_realtime_minute_kline(self, **kwargs):
            calls.append(("v4", kwargs))
            if self.realtime_unavailable: raise OSError("fixture realtime unavailable")
            return {"data": [{"symbol": "600519.SH", "items": rows(10)}]}
        def stock_minutes(self, **kwargs):
            calls.append(("v2", kwargs))
            return rows({"none": 10, "forward": 100, "backward": 200}[kwargs["adjust_kind"]])
    market = Market()
    with patch.object(fetch, "ftshare_available", return_value=True), \
         patch.object(fetch, "_ftshare_market_api", return_value=market), \
         patch.object(fetch, "_symbol_name", return_value="分钟测试"), \
         patch.object(fetch, "_latest_session_close_millis", return_value=int(day.replace(hour=15, minute=0).timestamp() * 1000)), \
         patch.object(fetch, "_preferred_ftshare_transport", return_value="sdk"), \
         patch.object(fetch, "_candle_cache", {}), patch.object(fetch, "_FTSHARE_TRANSPORT_STATE", {}), \
         patch.object(fetch.time, "sleep"):
        yield market, calls


def get(adjust):
    return fetch.fetch_candles("600519.XSHG", interval="minute", interval_value=1, session_count=1, limit=20, adjust=adjust)


@pytest.mark.parametrize("requested,canonical,close", [("forward", "forward", 100.5), ("qfq", "forward", 100.5),
                                                       ("backward", "backward", 200.5), ("hfq", "backward", 200.5)])
def test_adjusted_minute_request_never_uses_unadjusted_realtime(minute_market, requested, canonical, close):
    _, calls = minute_market
    result = get(requested)
    assert result["ok"]
    assert [kind for kind, _ in calls] == ["v2"]
    assert calls[0][1]["adjust_kind"] == canonical
    assert result["adjust"] == canonical
    assert result["rows"][-1]["close"] == close
    # Existing minute contract returns complete sessions, not a 20-row slice.
    assert result["count"] == len(result["rows"]) == 240
    assert result["requested_count"] == 20 and result["history_complete"] is True


@pytest.mark.parametrize("fallback", [False, True])
def test_none_still_prefers_realtime_and_keeps_history_fallback(minute_market, fallback):
    market, calls = minute_market
    market.realtime_unavailable = fallback
    # Patch the realtime wrapper when failing so no adaptive transport can use real HTTP.
    def fail(**_kwargs):
        calls.append(("v4", {})); raise OSError("fixture realtime unavailable")
    from contextlib import nullcontext
    with patch.object(fetch, "_ftshare_stock_realtime_minutes", side_effect=lambda *a, **k: fail(**k)) if fallback else nullcontext():
        result = get("none")
    assert result["ok"] and result["adjust"] == "none"
    assert [kind for kind, _ in calls] == (["v4", "v2"] if fallback else ["v4"])
    assert result["rows"][-1]["close"] == 10.5
    if fallback: assert calls[-1][1]["adjust_kind"] == "none"


@pytest.mark.parametrize("empty", [False, True])
def test_adjusted_history_failure_never_falls_back_to_raw_success(minute_market, empty):
    _, calls = minute_market
    assert get("none")["ok"]  # Even an available warm raw cache is not an adjusted fallback.
    calls.clear()
    with patch.object(fetch, "_ftshare_stock_minutes", **({"return_value": []} if empty else {"side_effect": OSError("fixture history unavailable")})) as history:
        result = get("forward")
    assert result["ok"] is False
    assert history.called and all(call.kwargs["adjust_kind"] == "forward" for call in history.call_args_list)
    assert calls == []  # In particular no v4 call, even on historical failure.
    assert "rows" not in result


def test_adjusted_failure_can_only_reuse_explicitly_stale_same_adjustment_cache(minute_market):
    _, calls = minute_market
    assert get("forward")["rows"][-1]["close"] == 100.5
    calls.clear()
    with patch.object(fetch, "_recent_candle_cache", return_value=None), \
         patch.object(fetch, "_ftshare_stock_minutes", side_effect=OSError("fixture history unavailable")) as history:
        result = get("qfq")
    assert history.called and calls == []
    assert result["ok"] and result["cached"] and result["status"] == "stale"
    assert result["adjust"] == "forward" and result["rows"][-1]["close"] == 100.5
    assert result["freshness"] == "recent_cached_fallback"


def test_adjustment_cache_does_not_reuse_raw_or_other_adjustment_rows(minute_market):
    _, calls = minute_market
    raw, forward, backward = get("none"), get("forward"), get("backward")
    assert [kind for kind, _ in calls] == ["v4", "v2", "v2"]
    assert [r["rows"][-1]["close"] for r in [raw, forward, backward]] == [10.5, 100.5, 200.5]
    assert [r["time"] for r in raw["rows"]] == [r["time"] for r in forward["rows"]] == [r["time"] for r in backward["rows"]]
    before = len(calls)
    assert get("qfq")["rows"][-1]["close"] == 100.5
    assert get("hfq")["rows"][-1]["close"] == 200.5
    assert get("none")["rows"][-1]["close"] == 10.5
    assert len(calls) == before  # Same canonical adjustment can reuse its own cache only.
