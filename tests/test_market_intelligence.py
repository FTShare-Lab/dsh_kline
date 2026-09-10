from types import SimpleNamespace
from unittest.mock import patch

import pytest

import tools.fetch as f


def _rows(name, **extra):
    return [{"name": name, "net_inflow": 123456, "change_pct": 1.25, **extra}]


@pytest.fixture(autouse=True)
def _clear_intelligence_caches():
    f._market_pulse_cache = None
    f._market_pulse_section_cache.clear()
    f._security_intelligence_cache.clear()
    f._candle_cache.clear()
    f._symbol_search_cache.clear()
    yield
    f._market_pulse_cache = None
    f._market_pulse_section_cache.clear()
    f._security_intelligence_cache.clear()
    f._candle_cache.clear()
    f._symbol_search_cache.clear()


def test_market_pulse_keeps_available_sections_when_one_endpoint_fails():
    market = SimpleNamespace(
        limit_list=lambda **kwargs: _rows("涨跌停池", limit_type=kwargs["limit_type"]),
        eastmoney_dapan_flow=lambda **_: _rows("大盘资金"),
        northbound=lambda **_: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
        southbound=lambda **_: _rows("南向资金"),
        eastmoney_sector_flow=lambda **_: _rows("半导体"),
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse()
    assert result["ok"]
    assert result["market_pulse"]["breadth"][0]["title"] == "涨停"
    assert result["market_pulse"]["hot_sectors"][0]["title"] == "半导体"
    assert result["sections"]["flows"]["state"] == "partial"
    assert result["sections"]["flows"]["errors"][0]["code"] == "rate_limited"


def test_market_pulse_uses_latest_market_reading_and_industry_flows():
    market = SimpleNamespace(
        limit_list=lambda **_: [],
        eastmoney_dapan_flow=lambda **_: [
            {"name": "上证指数", "trade_date": "20260109", "sh_close": "4100", "sh_change_pct": "0.2", "main_net": "-9", "main_pct": "-0.1"},
            {"name": "上证指数", "trade_date": "20260908", "sh_close": "3940.55", "sh_change_pct": "0.92", "main_net": "12.5", "main_pct": "0.3"},
        ],
        northbound=lambda **_: [],
        southbound=lambda **_: [],
        eastmoney_sector_flow=lambda **_: [
            {"sector_name": "上海板块", "sector_type": "regional", "trade_date": "20260908", "main_net": "999", "main_pct": "9"},
            {"sector_name": "白酒", "sector_type": "industry", "trade_date": "20260908", "main_net": "20.5", "main_pct": "3.2"},
            {"sector_name": "半导体", "sector_type": "industry", "trade_date": "20260908", "main_net": "8", "main_pct": "1.1"},
        ],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse()
    pulse = result["market_pulse"]
    assert pulse["as_of"] == "20260908"
    assert pulse["flows"] == [{"title": "上证指数", "value": "12.5", "detail": "20260908", "change": "0.30%"}]
    assert [item["title"] for item in pulse["hot_sectors"]] == ["白酒", "半导体"]
    assert pulse["hot_sectors"][0]["value"] == "20.5"
    assert pulse["hot_sectors"][0]["change"] == "3.20%"
    assert [item["tone"] for item in pulse["breadth"]] == ["up", "down"]


def test_market_pulse_keeps_concepts_and_actionable_stock_rankings_separate():
    market = SimpleNamespace(
        limit_list=lambda **_: [],
        eastmoney_dapan_flow=lambda **_: [],
        northbound=lambda **_: [],
        southbound=lambda **_: [],
        eastmoney_sector_flow=lambda **_: [
            {"sector_name": "半导体", "sector_type": "industry", "main_net": "8"},
            {"sector_name": "机器人", "sector_type": "concept", "main_net": "12"},
        ],
        eastmoney_rank=lambda **kwargs: [
            {"stock_name": "紫金矿业", "stock_code": "601899", "current_price": "32.87", "change_pct": "3.2", "rank": "1"}
        ] if kwargs["rank_group"] == "hot" else [
            {"stock_name": "贵州茅台", "stock_code": "600519", "current_price": "1309.3", "change_pct": "1.1", "rank": "2"}
        ],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse()
    pulse = result["market_pulse"]
    assert [item["title"] for item in pulse["hot_sectors"]] == ["半导体"]
    assert [item["title"] for item in pulse["hot_concepts"]] == ["机器人"]
    assert pulse["rankings"]["hot"][0]["symbol"] == "601899.XSHG"
    assert pulse["rankings"]["surging"][0]["symbol"] == "600519.XSHG"


def test_market_pulse_falls_back_to_xueqiu_popularity_and_exposes_abnormal_trading():
    market = SimpleNamespace(
        limit_list=lambda **_: [],
        eastmoney_dapan_flow=lambda **_: [],
        northbound=lambda **_: [],
        southbound=lambda **_: [],
        eastmoney_sector_flow=lambda **_: [],
        eastmoney_rank=lambda **_: [],
        xueqiu_rank=lambda **_: [{"stock_name": "贵州茅台", "normalized_symbol": "600519", "latest_price": "1290.88", "metric_value": "3717329", "rank_no": 1}],
        abnormal_trading_overview=lambda **_: [{"symbol": "600371.SH", "symbol_name": "万向德农", "close": "15.83", "change_rate": "0.0504", "turnover": "1535853891.76"}],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse()
    pulse = result["market_pulse"]
    assert pulse["rankings"]["hot_source"] == "xueqiu"
    assert pulse["rankings"]["hot"][0]["symbol"] == "600519.XSHG"
    assert pulse["abnormal_trading"][0] == {
        "title": "万向德农", "symbol": "600371.XSHG", "value": "15.83", "change": "5.04%", "detail": "成交额 15.36亿",
    }


def test_market_pulse_uses_five_seat_net_for_dragon_tiger_rankings():
    market = SimpleNamespace(
        abnormal_trading_details=lambda **_: [{
            "symbol": "600371.SH", "symbol_name": "万向德农", "close": "15.83", "change_rate": "0.0504", "turnover": "1535853891.76",
            "top_buyers": [{"name": "甲营业部", "net": "30000000"}, {"name": "乙营业部", "net": "10000000"}],
            # 甲营业部出现在卖方列表中仍只应计算一次，避免双计。
            "top_sellers": [{"name": "甲营业部", "net": "30000000"}, {"name": "丙营业部", "net": "-5000000"}],
        }],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse(sections=["events"])
    item = result["market_pulse"]["abnormal_trading"][0]
    assert item["five_seat_net"] == "3500.00万"
    assert item["five_seat_net_value"] == 35000000
    assert item["tone"] == "up"


def test_market_pulse_can_load_overview_without_waiting_for_other_groups():
    market = SimpleNamespace(
        limit_list=lambda **_: [],
        eastmoney_dapan_flow=lambda **_: _rows("大盘资金"),
        northbound=lambda **_: [],
        southbound=lambda **_: [],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_pulse(sections=["breadth", "flows"])
    pulse = result["market_pulse"]
    assert {"as_of", "breadth", "flows"} == set(pulse)
    assert result["sections"]["rankings"]["state"] == "deferred"


def test_market_index_registry_covers_mainland_hong_kong_and_us_benchmarks():
    symbols = {item["symbol"] for item in f.MARKET_TICKER_SOURCES}
    assert {"000001.XSHG", "000300.XSHG", "399001.XSHE", "399006.XSHE"} <= symbols
    assert "100.HSI" in symbols
    assert {"100.NDX", "100.SPX", "100.DJIA"} <= symbols


def test_data_source_capability_contract_keeps_external_rows_intentionally_narrow():
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "ftshare_capabilities", return_value={"daily": "available", "minute": "available"}):
        contract = f.data_source_capability_contract()
    assert contract["version"] == 1
    assert contract["providers"]["ftshare"]["market_boards"] == "available"
    assert contract["providers"]["ftshare"]["board_members"] == "source_dependent"
    assert contract["providers"]["external_rows"]["daily_candles"] == "available"
    assert contract["providers"]["external_rows"]["market_rankings"] == "unsupported"


def test_market_board_detail_uses_the_exact_snapshot_code_and_marks_members_source_dependent():
    market = SimpleNamespace(
        eastmoney_sector_flow=lambda **_: [{"sector_code": "BK0421", "sector_name": "铁路公路", "sector_type": "industry", "main_net": "0.98", "main_pct": "2.44"}],
        ths_industry_daily_flow=lambda **_: [{"trade_date": "20260909", "net_amount": "3.79", "change_pct": "0.14", "leader_name": "张家港行", "leader_change_pct": "1.59"}],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market):
        result = f.fetch_market_board_detail("铁路公路", board_code="BK0421")
    assert result["ok"]
    assert result["board"]["code"] == "BK0421"
    assert result["board"]["history"][0]["title"] == "09-09"
    assert result["sections"]["members"]["state"] == "source_dependent"


def test_security_intelligence_isolated_sections_and_industry_linkage():
    market = SimpleNamespace(
        company_list=lambda **_: [{"stock_name": "贵州茅台", "industry": "白酒"}],
        eastmoney_stock_flow=lambda **_: _rows("主力净流入"),
        limit_event_timeline_3s=lambda **_: _rows("涨停事件", event="触及涨停"),
        ths_industry_daily_flow=lambda **kwargs: _rows(kwargs["sector_name"]),
        supply_chain_subsubindustry_companies=lambda **kwargs: _rows("同类公司", industry=kwargs["subindustry_name"]),
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market), patch.object(f, "_symbol_name", return_value="贵州茅台"):
        result = f.fetch_security_intelligence("600519.XSHG")
    assert result["ok"]
    intelligence = result["security_intelligence"]
    assert intelligence["sector"]["industry"] == "白酒"
    assert intelligence["flows"][0]["title"] == "主力净流入"
    assert intelligence["events"][0]["title"] == "涨停事件"
    assert intelligence["sector"]["peers"][0]["title"] == "同类公司"


def test_security_intelligence_turns_dated_flow_series_into_useful_history_cards():
    market = SimpleNamespace(
        company_list=lambda **_: [{"stock_name": "招商银行", "industry": "银行"}],
        eastmoney_stock_flow=lambda **_: [{"trade_date": "20260908", "close_price": "40.9", "change_pct": "-0.41", "main_net": "6575413", "main_pct": "0.33"}],
        limit_event_timeline_3s=lambda **_: [],
        ths_industry_daily_flow=lambda **_: [{"trade_date": "20260909", "net_amount": "3.79", "change_pct": "0.14", "leader_name": "张家港行", "leader_change_pct": "1.59"}],
        supply_chain_subsubindustry_companies=lambda **_: [],
    )
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market), patch.object(f, "_symbol_name", return_value="招商银行"):
        intelligence = f.fetch_security_intelligence("600036.XSHG")["security_intelligence"]
    assert intelligence["sector"]["flow"] == [{"title": "09-09", "value": "3.79", "change": "0.14%", "detail": "领涨 张家港行 1.59%", "tone": "up"}]
    assert intelligence["flows"] == [{"title": "09-08", "value": "657.54万", "change": "0.33%", "detail": "收盘 40.9 · -0.41%", "tone": "up"}]


def test_etf_uses_its_own_candle_endpoint_and_seed_search():
    rows = [
        {"time": 1700000000 + index * 86400, "open": 3 + index, "high": 4 + index, "low": 2 + index, "close": 3.5 + index, "volume": 100}
        for index in range(3)
    ]
    calls = []

    def etf_candlesticks(**kwargs):
        calls.append(kwargs)
        return rows

    market = SimpleNamespace(etf_candlesticks=etf_candlesticks)
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market), patch.object(f, "_symbol_name", return_value="沪深300ETF"):
        result = f.fetch_candles("510300.XSHG", interval="day", limit=2)
    assert result["ok"]
    assert result["instrument_type"] == "etf"
    assert result["name"] == "沪深300ETF"
    assert calls and calls[0]["interval_unit"] == "Day"
    search = f.search_symbols("沪深300ETF")
    assert any(item["symbol"] == "510300.XSHG" for item in search["results"])
    industry_etf = f.search_symbols("银行ETF")
    assert any(item["symbol"] == "512800.XSHG" for item in industry_etf["results"])


def test_etf_minutes_use_the_provider_short_exchange_suffix():
    rows = [
        {"time": 1788824700 + index * 300, "open": 3, "high": 3.1, "low": 2.9, "close": 3.05, "volume": 100}
        for index in range(48)
    ]
    calls = []

    def etf_minutes(**kwargs):
        calls.append(kwargs)
        return rows

    market = SimpleNamespace(etf_minutes=etf_minutes)
    with patch.object(f, "ftshare_available", return_value=True), patch.object(f, "_ftshare_market_api", return_value=market), patch.object(f, "_latest_session_close_millis", return_value=1788830100000):
        result = f.fetch_candles("510300.XSHG", interval="minute", interval_value=5, session_count=1, limit=20)
    assert result["ok"]
    assert result["instrument_type"] == "etf"
    assert calls and calls[0]["symbol"] == "510300.SH"
