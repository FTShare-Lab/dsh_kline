from types import SimpleNamespace
from unittest.mock import patch

import pytest
import tools.fetch as f


def fake_market(fail=None):
    calls = []
    def method(name):
        def call(**kwargs):
            calls.append((name, kwargs))
            if name == fail:
                raise RuntimeError('HTTP 429')
            if name == 'company_list':
                assert kwargs['stock_code'] == '600519'
                return [{'stock_name': '贵州茅台', 'company_profile': '真实公司简介',
                         'business_scope': '经营范围', 'main_business': '生产与销售',
                         'business_products': '主要产品', 'bk': '食品饮料', 'listing_date': '2001-08-27'}]
            if name == 'stock_holders':
                assert kwargs['stock_code'] == '600519.SH'
            return []
        return call
    names = ['company_list', 'income', 'stock_holders', 'balance', 'cashflow',
             'stock_holders_number', 'stock_pledge_detail', 'stock_share_chg', 'semantic_search_news']
    return SimpleNamespace(**{n: method(n) for n in names}), calls


@pytest.fixture(autouse=True)
def clear_cache():
    f._security_workspace_cache.clear()
    yield
    f._security_workspace_cache.clear()


def load(market, **kwargs):
    with patch.object(f, '_ftshare_market_api', return_value=market), \
         patch.object(f, 'ftshare_available', return_value=True), \
         patch.object(f, '_symbol_name', return_value='贵州茅台'), \
         patch.object(f.time, 'sleep'):
        return f.fetch_security_workspace('600519.XSHG', **kwargs)['security_workspace']


def test_company_code_and_profile_mapping():
    market, calls = fake_market()
    w = load(market)
    assert w['overview']['description'] == '真实公司简介'
    assert w['overview']['listing_date'] == '2001-08-27'
    details = {d['label']: d['value'] for d in w['overview']['details']}
    assert details['主营业务'] == '生产与销售'
    assert details['主要产品'] == '主要产品'
    assert details['所属板块'] == '食品饮料'
    assert w['sections']['overview']['state'] == 'available'
    assert w['sections']['financials']['state'] == 'empty'
    assert next(args for n, args in calls if n == 'income')['stock_code'] == '600519.SH'


@pytest.mark.parametrize('failed,section', [('company_list', 'overview'), ('income', 'financials'), ('semantic_search_news', 'news')])
def test_rate_limited_sections_retry_then_stop_the_remaining_burst(failed, section):
    market, calls = fake_market(failed)
    w = load(market)
    assert w['sections'][section]['state'] == 'error'
    assert w['sections'][section]['errors'][0]['code'] == 'rate_limited'
    assert [name for name, _ in calls].count(failed) == 3
    # A provider 429 is account-wide. Continuing with the remaining six
    # company endpoints merely amplifies the limit and gives the UI duplicate
    # error cards, so the rest of this single page load is cooled down.
    assert not any(name == 'stock_holders' for name, _ in calls)
    assert not f._security_workspace_cache
    if failed == 'income':
        assert w['overview']['description'] == '真实公司简介'


def test_partial_data_retained_and_refresh_bypasses_cache():
    market, calls = fake_market()
    load(market)
    count = len(calls)
    load(market)
    assert len(calls) == count
    load(market, refresh=True)
    assert len(calls) > count
    market.balance = lambda **_: (_ for _ in ()).throw(TimeoutError('timeout'))
    w = load(market, refresh=True)
    assert w['sections']['overview']['state'] == 'partial'
    assert w['overview']['description'] == '真实公司简介'


@pytest.mark.parametrize('symbol', ['000001.XSHG', '000300.SH', '100.HSI'])
def test_index_never_queries_company_or_bank(symbol):
    with patch.object(f, '_ftshare_market_api', side_effect=AssertionError('index must not query company endpoints')):
        w = f.fetch_security_workspace(symbol)['security_workspace']
    assert w['instrument_type'] == 'index'
    assert w['sections']['financials']['state'] == 'not_applicable'
    assert w['sections']['holders']['state'] == 'not_applicable'
    assert '指数' in w['overview']['description']
