"""Recorded corporate actions + adversarial paging/identity and host routing."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from tools import foreign_daily as d
from tools import fetch as f

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/foreign-daily.json').read_text())
NOW = datetime(2026, 11, 6, 18, tzinfo=ZoneInfo('Asia/Hong_Kong'))


@pytest.fixture(autouse=True)
def isolated_cache():
    with patch.object(d, '_cache_get', return_value=None), patch.object(d, '_cache_set'):
        yield


def page(rows, code='hk00700', series='day'):
    return {'code': 0, 'data': {code: {series: rows}}}


def bar(day, close=11, volume=100):
    return [day, str(close-1), str(close), str(close+1), str(close-2), str(volume)]


def parsed(key, code, series, zone):
    result = d._parse_page(FIXTURE[key], code, series, ZoneInfo(zone), NOW, series == 'qfqday')
    assert result is not None
    return {datetime.fromtimestamp(r['time'], ZoneInfo(zone)).date().isoformat(): r for r in result[0]}


def test_real_split_prices_and_historical_share_volume_are_not_rescaled():
    raw = parsed('nvda_raw', 'usNVDA.OQ', 'day', 'America/New_York')
    qfq = parsed('nvda_qfq', 'usNVDA.OQ', 'qfqday', 'America/New_York')
    assert raw['2024-06-07']['close'] == 1208.88
    assert raw['2024-06-10']['close'] == 121.79
    assert qfq['2024-06-07']['close'] == 120.51
    assert qfq['2024-06-10']['close'] == 121.41
    for day, shares in [('2024-06-07', 41238580), ('2024-06-10', 314162650)]:
        assert raw[day]['volume'] == qfq[day]['volume'] == shares


def test_recorded_hk_cash_dividend_and_three_distinct_price_bases():
    raw, qfq, hfq = [parsed('hk_'+key, 'hk00700', series, 'Asia/Hong_Kong')
                     for key, series in [('raw','day'), ('qfq','qfqday'), ('hfq','hfqday')]]
    a, b = '2024-05-16', '2024-05-17'
    assert [raw[x]['close'] for x in (a,b)] == [397,395]
    assert [qfq[x]['close'] for x in (a,b)] == [383.8,385.2]
    assert [hfq[x]['close'] for x in (a,b)] == [2197.93,2204.93]
    assert qfq[b]['close']-qfq[a]['close'] == pytest.approx(395-397+3.4)
    for day in (a,b):
        assert raw[day]['volume'] == qfq[day]['volume'] == hfq[day]['volume']


def test_recorded_us_dividend_changes_price_adjustment_factor():
    raw = parsed('aapl_raw','usAAPL.OQ','day','America/New_York')
    qfq = parsed('aapl_qfq','usAAPL.OQ','qfqday','America/New_York')
    before, after = '2024-05-09','2024-05-10'
    assert raw[before]['close'] == 184.57 and raw[after]['close'] == 183.05
    assert qfq[before]['close']/raw[before]['close'] != pytest.approx(qfq[after]['close']/raw[after]['close'], abs=0.0001)


@pytest.mark.parametrize('market,mode,route,series', [
    ('00700.HK','none','kline/kline','day'), ('00700.HK','forward','hkfqkline/get','qfqday'),
    ('00700.HK','backward','hkfqkline/get','hfqday'), ('AAPL.US','none','kline/kline','day'),
    ('AAPL.US','forward','usfqkline/get','qfqday')])
def test_exact_route_series_and_no_key_requirement(market,mode,route,series):
    code = 'hk00700' if market.endswith('.HK') else 'usAAPL.OQ'
    with patch.object(d, '_us_code', return_value=code), patch.object(d,'_read', return_value=page([bar('2024-06-06'),bar('2024-06-07')],code,series)) as get:
        result=d.fetch_foreign_daily(market,limit=2,adjust=mode)
    assert result['history_complete'] and result['volume_unit']=='shares'
    assert '/'+route+'?' in get.call_args.args[0]
    assert result['price_adjustment']==mode


@pytest.mark.parametrize('symbol', ['600519.XSHG','100.NDX','00700','../AAPL.US','AAPL.US?x=y','AAPL.US/evil'])
def test_no_foreign_routing_for_invalid_or_mainland_symbols(symbol):
    with patch.object(d,'_read') as get:
        assert d.fetch_foreign_daily(symbol) is None
        get.assert_not_called()


def test_us_backward_never_accepts_unadjusted_series():
    with patch.object(d,'_read') as get:
        assert d.fetch_foreign_daily('AAPL.US',adjust='backward') is None
        get.assert_not_called()
    assert d._parse_page(page([bar('2024-01-02')], 'usAAPL.OQ'), 'usAAPL.OQ', 'qfqday', ZoneInfo('America/New_York'), NOW, True) is None


@pytest.mark.parametrize('root,identity,valid', [('AAPL','AAPL.OQ',True),('BRK.B','BRK.B.N',True),('SPY','SPY.AM',True),('BRK.B','BRK.N',False),('AAPL','AAPL.PS',False),('AAPL','MSFT.OQ',False),('AAPL','https://evil',False)])
def test_quote_identity_is_exact_and_preserves_share_class(root,identity,valid):
    with patch.object(d,'_read',return_value=f'v_us{root.replace(".","__")}="1~Name~{identity}~1";'):
        assert d._us_code(root) == ('us'+identity if valid else None)


def test_paging_overlaps_deduplicates_and_stops_when_count_reached():
    first=[bar('2024-01-04'),bar('2024-01-05'),bar('2024-01-08')]
    older=[bar('2024-01-02'),bar('2024-01-03'),bar('2024-01-04')]
    with patch.object(d,'_PAGE_SIZE',3), patch.object(d,'_read',side_effect=[page(first),page(older)]) as get:
        result=d.fetch_foreign_daily('00700.HK',limit=5)
    assert len(result['rows'])==5 and result['history_complete']
    assert result['history_pages']==2
    assert ',2024-01-04,' in parse_qs(urlparse(get.call_args.args[0]).query)['param'][0]


@pytest.mark.parametrize('failure,reason', [
    (None,'source_unavailable_or_invalid'),
    (page([bar('2024-01-02'),bar('2024-01-03')]),'missing_page_overlap'),
    (page([bar('2024-01-04')]),'source_history_exhausted'),
    (page([bar('2024-01-03'),bar('2024-01-04',close=13)]),'inconsistent_page_basis'),
    (page([bar('2024-01-03'),bar('2024-01-08')]),'source_ignored_history_boundary')])
def test_incomplete_history_retains_valid_newer_data_and_reports_reason(failure,reason):
    with patch.object(d,'_read',side_effect=[page([bar('2024-01-04'),bar('2024-01-05')]),failure]) as get:
        result=d.fetch_foreign_daily('00700.HK',limit=5)
    assert not result['history_complete'] and result['coverage_reason']==reason
    assert len(result['rows'])==2 and get.call_count==2


@pytest.mark.parametrize('bad', [bar('2024-01-03',volume=-1),bar('2024-01-03',close=float('nan')),['bad','1','2','3','0','1'],['2024-01-03','10','11','9','8','100']])
def test_corrupt_page_is_never_partially_accepted(bad):
    assert d._parse_page(page([bar('2024-01-02'),bad]),'hk00700','day',ZoneInfo('Asia/Hong_Kong'),NOW,False) is None


def test_negative_forward_prices_truncate_at_contiguous_valid_boundary():
    result=d._parse_page(page([bar('2024-01-02'),bar('2024-01-03',close=-2),bar('2024-01-04'),bar('2024-01-05')],series='qfqday'),'hk00700','qfqday',ZoneInfo('Asia/Hong_Kong'),NOW,True)
    assert len(result[0])==2 and result[1]=='non_positive_adjusted_prices'
    with patch.object(d,'_read',return_value=page([bar('2024-01-03',close=-2),bar('2024-01-04'),bar('2024-01-05')],series='qfqday')):
        history=d.fetch_foreign_daily('00700.HK',limit=4,adjust='forward')
    assert not history['history_complete'] and history['coverage_reason']=='non_positive_adjusted_prices'


def test_exchange_timestamps_observe_us_dst_and_filter_unfinished_hk_day():
    zone=ZoneInfo('America/New_York')
    rows=d._parse_page(page([bar('2024-03-08'),bar('2024-03-11')]),'hk00700','day',zone,NOW,False)[0]
    assert [datetime.fromtimestamp(r['time'],ZoneInfo('UTC')).hour for r in rows]==[21,20]
    hk=ZoneInfo('Asia/Hong_Kong')
    rows=d._parse_page(page([bar('2026-11-05'),bar('2026-11-06')]),'hk00700','day',hk,datetime(2026,11,6,16,5,tzinfo=hk),False)[0]
    assert len(rows)==1


@pytest.mark.parametrize('key', [False,True])
def test_free_fallback_order_and_provenance(key):
    history={'rows':[{'time':int(NOW.timestamp())-86400,'open':1,'high':3,'low':1,'close':2,'volume':100}]*2,
             'history_complete':True,'coverage_reason':'requested_count_reached','volume_unit':'shares'}
    with patch.object(f,'_ftshare_credential_source',return_value='environment' if key else 'none'), \
         patch.object(f,'fetch_foreign_daily',return_value=deepcopy(history)) as free, \
         patch.object(f,'_fetch_candles_ftshare',return_value={'ok':False,'error':'capability_limited'}) as primary:
        result=f.fetch_candles('00700.HK',limit=2)
    assert result['ok'] and result['source']=='tencent_free' and result['volume_unit']=='shares'
    assert result['ftshare_key_configured'] is key
    assert primary.call_count == int(key)
    assert free.call_count==1
    assert ('fallback_from' in result) is key


def test_configured_primary_success_is_preserved():
    primary={'ok':True,'source':'ftshare','rows':[{'time':1},{'time':2}]}
    with patch.object(f,'_ftshare_credential_source',return_value='environment'),patch.object(f,'_fetch_candles_ftshare',return_value=primary),patch.object(f,'fetch_foreign_daily') as free:
        assert f.fetch_candles('00700.HK',limit=2)['source']=='ftshare'
        free.assert_not_called()


def test_wrong_identity_unsorted_and_duplicate_dates_fail_closed():
    for response in [page([bar('2024-01-02')],code='hk00005'),
                     page([bar('2024-01-03'),bar('2024-01-02')]),
                     page([bar('2024-01-02'),bar('2024-01-02')]),
                     {'code':1,'data':{'hk00700':{'day':[bar('2024-01-02')]}}}]:
        assert d._parse_page(response,'hk00700','day',ZoneInfo('Asia/Hong_Kong'),NOW,False) is None


def test_history_max_pages_is_bounded_when_source_returns_too_little():
    pages=[page([bar((datetime(2024,1,10)-timedelta(days=i)).date().isoformat()),bar((datetime(2024,1,11)-timedelta(days=i)).date().isoformat())]) for i in range(8)]
    with patch.object(d,'_read',side_effect=pages) as get:
        result=d.fetch_foreign_daily('00700.HK',limit=4000)
    assert get.call_count==8 and not result['history_complete']
    assert result['coverage_reason']=='page_limit'


def test_http_reads_are_bounded_and_failure_is_optional():
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,n):
            assert n==2_000_001
            return b'x'*n
    with patch.object(d,'urlopen',return_value=Response()) as get:
        assert d._read('https://web.ifzq.gtimg.cn/') is None
        assert get.call_args.kwargs['timeout']==6
    with patch.object(d,'urlopen',side_effect=OSError('offline')):
        assert d._read('https://web.ifzq.gtimg.cn/') is None


def test_minute_week_and_interval_multiple_do_not_enter_daily_fallback():
    with patch.object(f,'fetch_foreign_daily') as free:
        for interval,value in [('minute',1),('week',1),('day',2)]:
            assert f._free_foreign_candles_result('00700.HK',interval=interval,interval_value=value,limit=2,adjust='none') is None
        free.assert_not_called()


def test_codex_analysis_retains_volume_and_coverage_contract():
    from codex_runtime import analysis
    rows=d._parse_page(FIXTURE['nvda_raw'],'usNVDA.OQ','day',ZoneInfo('America/New_York'),NOW,False)[0]
    fetched={'ok':True,'symbol':'NVDA.US','rows':rows,'adjust':'none','source':'tencent_free',
             'volume_unit':'shares','volume_adjustment':'historical_session_shares',
             'history_complete':False,'coverage_reason':'source_history_exhausted','history_start':rows[0]['time']}
    with patch.object(analysis,'resolve_symbol',return_value=('NVDA.US','NVIDIA',None)),patch.object(analysis,'fetch_candles',return_value=fetched):
        result=analysis.analyze_symbol('NVDA.US',limit=6,indicators=[],metrics=[])
    assert result['ok'] and result['volume_unit']=='shares'
    assert not result['history_complete'] and result['coverage_reason']=='source_history_exhausted'


def test_dsh_chart_analysis_retains_source_warnings_and_volume_contract():
    import chart_service
    rows=d._parse_page(FIXTURE['nvda_raw'],'usNVDA.OQ','day',ZoneInfo('America/New_York'),NOW,False)[0]
    fetched={'ok':True,'symbol':'NVDA.US','rows':rows,'adjust':'none','source':'tencent_free',
             'source_url':d.SOURCE_URL,'volume_unit':'shares','history_complete':False,
             'coverage_reason':'source_history_exhausted','warnings':['only six sessions']}
    with patch('server._resolve_symbol_input',return_value=('NVDA.US','NVIDIA',None)),patch.object(chart_service,'fetch_candles',return_value=fetched):
        result=chart_service._http_analyze_kline({'symbol':'NVDA.US','limit':6,'indicators':[],'metrics':[]})
    assert result['ok'] and result['volume_unit']=='shares'
    assert not result['history_complete'] and result['source_url']==d.SOURCE_URL
    assert result['warnings']==['only six sessions']


def test_failed_public_source_keeps_primary_error_and_never_changes_market():
    with patch.object(f,'_ftshare_credential_source',return_value='none'), \
         patch.object(f,'fetch_foreign_daily',return_value=None), \
         patch.object(f,'_fetch_candles_ftshare',return_value={'ok':False,'error':'capability_limited','message':'anonymous denied'}), \
         patch.object(f,'fetch_stock_daily',side_effect=AssertionError('foreign must not use A-share source')):
        result=f.fetch_candles('00700.HK')
    assert result['error']=='capability_limited' and result['message']=='anonymous denied'


def test_cached_history_is_copied_before_exposing_mutable_rows():
    cached={'rows':[{'time':1,'close':2}], 'volume_unit':'shares'}
    with patch.object(d,'_cache_get',return_value=cached),patch.object(d,'_read') as read:
        result=d.fetch_foreign_daily('00700.HK')
        result['rows'][0]['close']=999
        assert cached['rows'][0]['close']==2
        read.assert_not_called()


def test_dsh_conversation_and_chart_session_keep_provider_contract():
    import asyncio
    import server
    rows=d._parse_page(FIXTURE['nvda_raw'],'usNVDA.OQ','day',ZoneInfo('America/New_York'),NOW,False)[0]
    fetched={'ok':True,'symbol':'NVDA.US','rows':rows,'adjust':'none','source':'tencent_free',
             'volume_unit':'shares','history_complete':False,'coverage_reason':'source_history_exhausted'}
    with patch.object(server,'_resolve_symbol_input',return_value=('NVDA.US','NVIDIA',None)),patch.object(server,'fetch_candles',return_value=fetched),patch.object(server,'publish_chart',return_value=('s'*32,'fixture')) as publish:
        result=asyncio.run(server.analyze_kline('NVDA.US',limit=6,indicators=[],metrics=[])).structuredContent
    assert result['ok'] and result['volume_unit']=='shares' and not result['history_complete']
    assert publish.call_args.args[0]['volume_unit']=='shares'
