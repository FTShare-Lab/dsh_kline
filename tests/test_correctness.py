import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import chart_service
import server
import tools.fetch as f
from core.calc import calc_metrics, series_rsi


def bars(count=40, trend=0):
    return [dict(time=1700000000 + i * 86400, open=100+i*trend,
                 high=100+i*trend, low=100+i*trend, close=100+i*trend, volume=100)
            for i in range(count)]


def test_key_levels_use_supplied_rows_without_market_requests():
    rows = bars()
    with patch.object(chart_service, 'fetch_candles', side_effect=AssertionError('must not fetch')), \
         patch.object(server, '_resolve_symbol_input', side_effect=AssertionError('must not resolve')):
        result = chart_service._tool_dispatch('analyze_key_levels', {'symbol': 'EXTERNAL', 'rows': rows})
    assert result['ok']
    assert result['metrics'] == chart_service.run_calc_metrics(rows, metrics=['support_resistance'])
    assert result['chartCommands'] == [{"type": "TEXT_MARKER", **m} for m in server._support_resistance_marks(result['metrics'])]
    assert all(cmd['type'] == 'TEXT_MARKER' for cmd in result['chartCommands'])
    assert 'chart_session' not in result


@pytest.mark.parametrize('rows,error', [(bars(4), 'insufficient_candles'), (None, 'invalid_rows'),
                                       ([], 'invalid_rows'), (bars(12001), 'invalid_rows')])
def test_key_levels_validate_local_input(rows, error):
    assert chart_service._http_key_levels({'rows': rows})['error'] == error


def test_key_levels_no_levels_is_success():
    result = chart_service._http_key_levels({'symbol': 'X', 'rows': bars(trend=2)})
    assert result['ok']
    assert result['status'] == 'no_levels'
    assert result['chartCommands'] == []


@pytest.mark.parametrize('trend,expected', [(0, 50), (1, 100), (-1, 0)])
def test_rsi_degenerate_series(trend, expected):
    assert set(series_rsi(bars(trend=trend)).values()) == {expected}
    if trend == 0:
        assert calc_metrics(bars(), ['rsi'])['rsi']['overbought'] == []


@pytest.mark.parametrize('interval,limit', [('day', 1000), ('week', 200), ('month', 120), ('quarter', 40), ('year', 200)])
@pytest.mark.parametrize('adapter', [f._fetch_generic_history, f._fetch_index_history])
def test_calendar_pagination_matches_daily_reference(interval, limit, adapter):
    start = datetime(2016, 1, 1, 15, tzinfo=ZoneInfo('Asia/Shanghai'))
    source = []
    for i in range(3900):
        day = start + timedelta(days=i)
        if day.weekday() < 5:
            source.append(dict(time=int(day.timestamp()), open=i+1, high=i+3,
                               low=i, close=i+2, volume=i+100))
    calls = []

    def fetch_page(_market, **kwargs):
        calls.append(kwargs)
        assert kwargs['interval_unit'] == 'Day'
        assert kwargs['adjust_kind'] == 'forward'
        assert kwargs['until_ts_millis'] - kwargs['since_ts_millis'] <= 360 * 86400000
        return [r for r in source if kwargs['since_ts_millis'] <= r['time']*1000 <= kwargs['until_ts_millis']]

    endpoint = '_ftshare_index_candlesticks' if adapter is f._fetch_index_history else '_ftshare_stock_candlesticks'
    with patch.object(f, endpoint, side_effect=fetch_page), patch.object(f, '_until_ms', return_value=(source[-1]['time']+86400)*1000):
        actual = adapter(None, symbol='600519.XSHG', interval=interval, interval_unit='ignored',
                         interval_value=1, adjust_kind='forward', limit=limit)
    expected = f._aggregate_interval(source, interval, timezone_name='Asia/Shanghai')[-limit:]
    assert actual == expected
    assert len(calls) > 1


def test_short_page_does_not_end_history():
    pages = [bars(1), [{**bars(1)[0], 'time': 1600000000}], []]
    with patch.object(f, '_ftshare_stock_candlesticks', side_effect=pages):
        result = f._fetch_generic_history(None, symbol='X', interval='year', interval_unit='Year',
                                         interval_value=1, adjust_kind='none', limit=200)
    assert len(result) == 2


def test_calendar_uses_exchange_timezone_at_us_month_end():
    jan = int(datetime(2024, 1, 31, 16, tzinfo=ZoneInfo('America/New_York')).timestamp())
    feb = int(datetime(2024, 2, 1, 16, tzinfo=ZoneInfo('America/New_York')).timestamp())
    rows = [{**bars(1)[0], 'time': stamp} for stamp in [jan, feb]]
    with patch.object(f, '_ftshare_stock_candlesticks', side_effect=[rows, []]):
        result = f._fetch_generic_history(None, symbol='NVDA.US', interval='month', interval_unit='Month',
                                         interval_value=1, adjust_kind='none', limit=200)
    assert len(result) == 2


@pytest.mark.parametrize('interval,limit', [('day', 30), ('week', 10), ('month', 4)])
def test_us_history_supplies_upper_bound_and_aggregates_before_trimming(interval, limit):
    from unittest.mock import Mock
    market = Mock()
    history = bars(180, trend=1)

    def daily(**kwargs):
        assert kwargs['stock_code'] == 'NVDA'
        assert kwargs['all_pages'] is True
        assert 'start_date' not in kwargs  # Paired dates impose a three-day cap.
        if not kwargs.get('end_date'):
            return history[-1:]  # Live endpoint's undated snapshot behavior.
        assert kwargs['end_date'] == datetime.now(ZoneInfo('America/New_York')).date().isoformat()
        return history

    market.eastmoney_us_stock_daily_ohlc.side_effect = daily
    f._candle_cache.clear()
    with patch.object(f, '_ftshare_market_api', return_value=market), \
         patch.object(f, '_symbol_name', return_value='NVIDIA'):
        result = f.fetch_candles('NVDA.US', interval=interval, limit=limit)
    assert result['ok']
    assert result['rows'] == f._aggregate_interval(history, interval, timezone_name='America/New_York')[-limit:]
    assert result['count'] == limit
    f._candle_cache.clear()


def test_us_minute_reports_market_limit_without_misdiagnosing_key():
    with patch.object(f, '_ftshare_market_api', side_effect=AssertionError('unsupported market must not request')):
        result = f.fetch_candles('NVDA.US', interval='minute')
    assert result['error'] == 'intraday_provider_unavailable'
    assert result['retryable'] is False
    assert '不代表 API Key 无效' in result['message']


def test_us_date_only_bars_keep_exchange_day_at_month_boundary():
    from unittest.mock import Mock
    market = Mock()
    source = [{'date': day, 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 100}
              for day in ['2026-06-30', '2026-07-01']]
    market.eastmoney_us_stock_daily_ohlc.return_value = source
    rows = f._normalize_raw(f._fetch_us_daily_candles(market, 'NVDA.US', 2))
    assert [datetime.fromtimestamp(row['time'], ZoneInfo('America/New_York')).date().isoformat()
            for row in rows] == ['2026-06-30', '2026-07-01']
    assert len(f._aggregate_interval(rows, 'month', timezone_name='America/New_York')) == 2
    assert all('time' not in row for row in source)


def test_hk_history_uses_compact_provider_dates():
    from unittest.mock import Mock
    market = Mock()
    now = int(datetime.now(ZoneInfo('Asia/Hong_Kong')).timestamp())
    recent = [{**bars(1)[0], 'time': now - offset * 86400} for offset in (2, 1, 0)]
    market.hk_candlesticks.return_value = recent
    result = f._fetch_hk_candles(market, '00700.HK', 'day', 60, 'none')
    assert result == recent
    request = market.hk_candlesticks.call_args.kwargs
    assert request['trade_code'] == '00700.HK'
    assert request['interval_unit'] == 'day'
    assert request['since_date'].isdigit() and len(request['since_date']) == 8
    assert request['until_date'].isdigit() and len(request['until_date']) == 8


@pytest.mark.parametrize('error,state', [('HTTP 401 missing API Key', 'auth_required'),
                                        ('HTTP 429', 'rate_limited'), ('timeout', 'upstream_unavailable')])
def test_daily_success_survives_minute_failure(error, state):
    with patch.object(f, 'ftshare_available', return_value=True), patch.object(f, '_ftshare_market_api'), \
         patch.object(f, '_ftshare_stock_candlesticks', return_value=bars(2)), \
         patch.object(f, '_ftshare_stock_minutes', side_effect=RuntimeError(error)), \
         patch.object(f, '_read_persisted_ftshare_key', return_value=''), patch.dict('os.environ', {'FTSHARE_API_KEY': ''}):
        result = f.test_ftshare_connection()
    assert result['ok']
    assert result['status'] == 'partial'
    assert result['capabilities'] == {'daily': 'available', 'minute': state}
    assert '已配置并验证通过' not in result['message']


def test_empty_daily_probe_is_not_available():
    with patch.object(f, 'ftshare_available', return_value=True), patch.object(f, '_ftshare_market_api'), \
         patch.object(f, '_ftshare_stock_candlesticks', return_value=[]):
        assert not f.test_ftshare_connection()['ok']


@pytest.mark.parametrize('query,expected', [('平安银行', '000001.XSHE'), ('工商银行', '601398.XSHG'),
    ('民生银行', '600016.XSHG'), ('五粮液', '000858.XSHE'), ('比亚迪', '002594.XSHE'),
    ('万科A', '000002.XSHE'), ('招商银行', '600036.XSHG'), ('小米', '01810.HK'), ('601398', '601398.XSHG')])
def test_first_install_search_offline(query, expected):
    f._symbol_search_cache.clear()
    with patch.object(f, '_read_symbol_directory_cache', return_value=None), patch.object(f, '_ftshare_market_api', side_effect=AssertionError('search must stay offline')):
        result = f.search_symbols(query)
    assert expected in [r['symbol'] for r in result['results']]
    assert result['partial']


def test_ambiguous_code_requires_choice():
    f._symbol_search_cache.clear()
    with patch.object(f, '_read_symbol_directory_cache', return_value=None):
        assert server._resolve_symbol_input('000001')[2]['error'] == 'ambiguous_symbol'
        assert server._resolve_symbol_input('000001.SZ')[0] == '000001.XSHE'


def test_unknown_search_and_explicit_code_fallback():
    f._symbol_search_cache.clear()
    with patch.object(f, '_read_symbol_directory_cache', return_value=None):
        assert '目录' in f.search_symbols('不存在的名字')['message']
        assert f.search_symbols('603123.SH')['results'][0]['symbol'] == '603123.XSHG'


def test_history_depth_is_disclosed():
    with patch.object(f, '_fetch_candles_ftshare', return_value={'ok': True, 'rows': bars(2), 'count': 2}):
        result = f.fetch_candles('600519.XSHG', limit=4000)
    assert result['requested_count'] == 4000
    assert not result['history_complete']
    assert result['warnings']


def test_minute_history_keeps_only_complete_requested_bars():
    base = 1_700_000_000
    full = {
        'time': base + 300, 'open_time': base,
        'open': 10, 'high': 11, 'low': 9, 'close': 10.5, 'volume': 100,
    }
    partial = {
        'time': base + 540, 'open_time': base + 300,
        'open': 10.5, 'high': 11, 'low': 10, 'close': 10.8, 'volume': 100,
    }
    assert f._complete_intraday_bars([full, partial], interval_value=5) == [full]


def test_intraday_history_counts_only_full_sessions_and_pages_from_prior_close():
    zone = ZoneInfo('Asia/Shanghai')
    day = datetime(2026, 9, 7, 9, 30, tzinfo=zone)  # Monday
    full_session = [
        {
            'time': int((day + timedelta(minutes=(index + 1) * 5)).timestamp()),
            'open_time': int((day + timedelta(minutes=index * 5)).timestamp()),
            'open': 10, 'high': 11, 'low': 9, 'close': 10.5, 'volume': 100,
        }
        for index in range(48)
    ]
    boundary = [{
        'time': int(datetime(2026, 9, 4, 15, 0, tzinfo=zone).timestamp()),
        'open_time': int(datetime(2026, 9, 4, 14, 55, tzinfo=zone).timestamp()),
        'open': 10, 'high': 11, 'low': 9, 'close': 10.5, 'volume': 100,
    }]
    assert f._complete_intraday_session_dates(
        full_session + boundary, timezone_name='Asia/Shanghai', interval_value=5,
    ) == {day.date()}
    previous_close = f._previous_weekday_session_close_millis(day.date(), 'Asia/Shanghai')
    assert datetime.fromtimestamp(previous_close / 1000, tz=zone) == datetime(2026, 9, 4, 15, 0, tzinfo=zone)


def test_a_share_current_minute_session_prefers_v4_and_keeps_v2_as_fallback():
    zone = ZoneInfo('Asia/Shanghai')
    day = datetime(2026, 9, 7, 9, 30, tzinfo=zone)
    minute_opens = [
        day + timedelta(minutes=index)
        for index in range(120)
    ] + [
        datetime(2026, 9, 7, 13, 0, tzinfo=zone) + timedelta(minutes=index)
        for index in range(120)
    ]
    realtime_one_minute_rows = [
        {
            'time': int((opened + timedelta(minutes=1)).timestamp()),
            'open_time': int(opened.timestamp()),
            'open': 10, 'high': 11, 'low': 9, 'close': 10.5, 'volume': 100,
        }
        for opened in minute_opens
    ]
    calls = []

    class V4Market:
        def stock_realtime_minute_kline(self, **kwargs):
            calls.append(('v4', kwargs))
            return {'data': [{'symbol': '600519.SH', 'items': realtime_one_minute_rows}]}

        def stock_minutes(self, **kwargs):
            calls.append(('v2', kwargs))
            return realtime_one_minute_rows

    f._candle_cache.clear()
    with patch.object(f, 'ftshare_available', return_value=True), \
         patch.object(f, '_ftshare_market_api', return_value=V4Market()), \
         patch.object(f, '_symbol_name', return_value='贵州茅台'), \
         patch.object(f, '_latest_session_close_millis', return_value=int((day + timedelta(hours=5, minutes=30)).timestamp() * 1000)):
        result = f.fetch_candles('600519.XSHG', interval='minute', interval_value=1, session_count=1, limit=20)
    assert result['ok']
    assert [kind for kind, _kwargs in calls] == ['v4']
    assert calls[0][1] == {'symbols': '["600519.SH"]', 'as_dataframe': False}

    calls.clear()

    class FallbackMarket:
        def stock_realtime_minute_kline(self, **kwargs):
            calls.append(('v4', kwargs))
            raise RuntimeError('HTTP 404: endpoint temporarily unavailable')

        def stock_minutes(self, **kwargs):
            calls.append(('v2', kwargs))
            return realtime_one_minute_rows

    f._candle_cache.clear()
    with patch.object(f, 'ftshare_available', return_value=True), \
         patch.object(f, '_ftshare_market_api', return_value=FallbackMarket()), \
         patch.object(f, '_symbol_name', return_value='贵州茅台'), \
         patch.object(f, '_latest_session_close_millis', return_value=int((day + timedelta(hours=5, minutes=30)).timestamp() * 1000)):
        fallback = f.fetch_candles('600519.XSHG', interval='minute', interval_value=1, session_count=1, limit=20)
    assert fallback['ok']
    assert [kind for kind, _kwargs in calls] == ['v4', 'v2']


def test_published_charts_are_independent_and_persistent():
    with tempfile.TemporaryDirectory() as directory, patch.object(chart_service, 'RUNTIME_DIR', Path(directory)), \
         patch.object(chart_service, 'RUNTIME_SESSION_FILE', Path(directory)/'chart-session.json'):
        service = chart_service.ChartService('127.0.0.1', 0)
        try:
            a, _ = service.publish({'symbol': '601899.XSHG', 'name': '紫金矿业'})
            b, _ = service.publish({'symbol': '600519.XSHG', 'name': '贵州茅台'})
            assert a != b
            assert service.store.get(a)['symbol'] == '601899.XSHG'
            assert service.store.get(b)['symbol'] == '600519.XSHG'
            saved_a = json.loads((Path(directory)/'sessions'/f'{a}.json').read_text(encoding='utf-8'))
            assert saved_a['payload']['symbol'] == '601899.XSHG'
            locator = json.loads(chart_service.RUNTIME_SESSION_FILE.read_text(encoding='utf-8'))
            assert locator['host_process_id'] == chart_service.HOST_PROCESS_ID
            assert locator['session'] == b
            if os.name == 'posix':
                assert ((Path(directory)/'sessions'/f'{a}.json').stat().st_mode & 0o777) == 0o600
        finally:
            service.httpd.shutdown()
            service.httpd.server_close()
