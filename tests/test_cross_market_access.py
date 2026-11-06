import io
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from tools import fetch as f


@pytest.mark.parametrize('symbol,method', [('00700.HK', '_fetch_hk_candles'), ('AAPL.US', '_fetch_us_daily_candles')])
@pytest.mark.parametrize('failure,code,attempts', [
    ('HTTP 403 route_not_allowed 当前套餐无权访问该接口', 'capability_limited', 1),
    ('HTTP 403 route_not_allowed', 'capability_limited', 1),
    ('HTTP 401 missing API Key', 'auth_required', 1),
    ('HTTP 429 rate limited', 'rate_limited', 1),
    ('HTTP 400 symbols are not A-share stocks', 'request_rejected', 1),
    ('HTTP 503 upstream failed', 'upstream_error', 2),
])
def test_foreign_market_errors_never_fall_back_to_mainland_candles(symbol, method, failure, code, attempts):
    with ExitStack() as stack:
        for name, value in [('ftshare_available', True), ('_ftshare_credential_source', 'none'),
                            ('_recent_candle_cache', None), ('_cached_candle_fallback', None),
                            ('_free_index_candles_result', None), ('_free_foreign_candles_result', None), ('_ftshare_market_api', object())]:
            stack.enter_context(patch.object(f, name, return_value=value))
        stack.enter_context(patch.dict('os.environ', {'FTSHARE_API_KEY': ''}))
        stack.enter_context(patch.object(f.time, 'sleep'))
        generic = stack.enter_context(patch.object(f, '_fetch_generic_history', side_effect=AssertionError('must not change markets')))
        primary = stack.enter_context(patch.object(f, method, side_effect=RuntimeError(failure)))
        result = f.fetch_candles(symbol)
    generic.assert_not_called()
    assert primary.call_count == attempts
    assert result['error_code'] == code
    assert result['ftshare_key_configured'] is False
    assert 'API Key 有效' not in result['message']
    if code == 'capability_limited':
        assert '匿名' in result['message']


@pytest.mark.parametrize('symbol', ['BRK.B.US', 'BRK.B.NYSE'])
def test_us_share_class_is_preserved_for_the_dedicated_provider(symbol):
    from unittest.mock import Mock
    market = Mock()
    market.eastmoney_us_stock_daily_ohlc.return_value = []
    f._fetch_us_daily_candles(market, symbol, 5)
    assert market.eastmoney_us_stock_daily_ohlc.call_args.kwargs['stock_code'] == 'BRK.B'


@pytest.mark.parametrize('query,symbol', [
    ('特斯拉', 'TSLA.US'), ('TSLA', 'TSLA.US'), ('Meta', 'META.US'), ('奈飞', 'NFLX.US'),
    ('亚马逊', 'AMZN.US'), ('伯克希尔', 'BRK.B.US'), ('港交所', '00388.HK'),
    ('香港交易所', '00388.HK'), ('美团', '03690.HK'), ('携程', '09961.HK'),
])
def test_fresh_keyless_search_has_common_bilingual_foreign_symbols(query, symbol):
    with patch.object(f, '_read_symbol_directory_cache', return_value=None), \
         patch.object(f, '_ftshare_market_api', side_effect=AssertionError('search must stay offline')), \
         patch.object(f, 'urlopen', side_effect=AssertionError('search must stay offline')):
        f._symbol_search_cache.clear()
        result = f.search_symbols(query)
    assert symbol in {item['symbol'] for item in result['results']}


def test_public_us_directory_reads_both_listing_files_and_skips_test_issues():
    nasdaq = b'Symbol|Security Name|Test Issue\nTSLA|Tesla|N\nZTEST|Test security|Y\nFile Creation Time: 20261105||\n'
    other = b'ACT Symbol|Security Name|Test Issue\nBRK.B|Berkshire B|N\nBAD/SYM|Bad format|N\n'
    with patch.object(f, 'urlopen', side_effect=[io.BytesIO(nasdaq), io.BytesIO(other)]) as get:
        items = f._fetch_public_us_symbol_directory()
    assert {item['symbol'] for item in items} == {'TSLA.US', 'BRK.B.US'}
    assert [call.args[0].full_url for call in get.call_args_list] == list(f._US_DIRECTORY_URLS)
    assert all(call.kwargs['timeout'] == 10 for call in get.call_args_list)


def test_public_us_directory_rejects_wrong_response_instead_of_claiming_complete():
    with patch.object(f, 'urlopen', return_value=io.BytesIO(b'<html>temporary error</html>')):
        with pytest.raises(ValueError, match='unexpected columns'):
            f._fetch_public_us_symbol_directory()


@pytest.mark.parametrize('sdk_available', [False, True])
def test_public_directories_refresh_without_a_working_sdk_and_are_searchable_from_cache(sdk_available):
    saved = []
    with patch.object(f, 'ftshare_available', return_value=sdk_available), \
         patch.object(f, '_ftshare_market_api', side_effect=AssertionError('no SDK required')), \
         patch.object(f, '_read_symbol_directory_cache', return_value=None), \
         patch.object(f, '_fetch_hk_symbol_directory', return_value=[{'symbol': '00002.HK', 'name': 'CLP', 'market': 'HK'}]), \
         patch.object(f, '_fetch_public_us_symbol_directory', return_value=[{'symbol': 'ADBE.US', 'name': 'Adobe', 'market': 'US'}]), \
         patch.object(f, '_write_symbol_directory_cache', side_effect=lambda value: saved.append(value) or True):
        result = f.symbol_directory(force_refresh=True)
    assert result['coverage']['HK']['complete']
    assert result['coverage']['US']['complete']
    assert result['source'] == 'public_directories'
    with patch.object(f, '_read_symbol_directory_cache', return_value=saved[0]):
        f._symbol_search_cache.clear()
        assert f.search_symbols('Adobe')['results'][0]['symbol'] == 'ADBE.US'


def test_directory_merge_keeps_seed_aliases_with_provider_names_and_is_stable():
    provider = [{'symbol': 'TSLA.US', 'name': 'Tesla Inc.', 'market': 'US'}]
    seed = [{'symbol': 'TSLA.US', 'name': '特斯拉', 'market': 'US', 'aliases': '特斯拉 Tesla'}]
    merged = f._merge_symbol_directory(provider, seed)
    assert merged[0]['name'] == 'Tesla Inc.'
    assert '特斯拉' in merged[0]['aliases']
    assert f._merge_symbol_directory(merged, seed) == merged


def test_fresh_mainland_only_cache_does_not_pin_missing_foreign_directories_for_a_day():
    cached = {'version': 5, 'expires_at': time.time() + 86400, 'items': [], 'coverage': {'CN': {'complete': True}}}
    with patch.object(f, '_read_symbol_directory_cache', return_value=cached), \
         patch.object(f, 'ftshare_available', return_value=False), \
         patch.object(f, '_fetch_hk_symbol_directory', return_value=[{'symbol': '00388.HK', 'name': 'HKEX', 'market': 'HK'}]) as hk, \
         patch.object(f, '_fetch_public_us_symbol_directory', return_value=[{'symbol': 'TSLA.US', 'name': 'Tesla', 'market': 'US'}]) as us, \
         patch.object(f, '_write_symbol_directory_cache', return_value=True):
        result = f.symbol_directory()
    hk.assert_called_once()
    us.assert_called_once()
    assert result['coverage']['HK']['complete'] and result['coverage']['US']['complete']


def test_public_directory_outage_keeps_cached_foreign_symbols():
    cached = {'version': 5, 'expires_at': 0, 'items': [{'symbol': 'ADBE.US', 'name': 'Adobe', 'market': 'US'}]}
    with patch.object(f, '_read_symbol_directory_cache', return_value=cached), \
         patch.object(f, 'ftshare_available', return_value=False), \
         patch.object(f, '_fetch_hk_symbol_directory', side_effect=OSError('offline')), \
         patch.object(f, '_fetch_public_us_symbol_directory', side_effect=OSError('offline')), \
         patch.object(f, '_write_symbol_directory_cache', return_value=True):
        result = f.symbol_directory()
    assert any(item['symbol'] == 'ADBE.US' for item in result['items'])
    assert result['stale'] is True
