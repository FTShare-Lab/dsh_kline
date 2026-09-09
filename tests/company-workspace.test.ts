import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const notice = html.slice(html.indexOf('function workspaceSectionNotice('), html.indexOf('function renderSecurityWorkspace('))
test('security navigation exposes five direct pages with a separate market view', () => {
  const navStart = html.indexOf('<nav class="security-nav"')
  const nav = html.slice(navStart, html.indexOf('</nav>', navStart))
  assert.match(nav, /data-security-tab="market">市场<\/button>/)
  assert.match(nav, /data-security-tab="chart">图表<\/button>/)
  assert.match(nav, /data-security-tab="sector">板块<\/button>/)
  assert.match(nav, /data-security-tab="news">资讯<\/button>/)
  assert.match(nav, /data-security-tab="company">公司<\/button>/)
  assert.ok(!html.includes('data-security-tab="overview"'))
  assert.ok(!html.includes('data-security-tab="financials"'))
  assert.ok(!html.includes('data-security-tab="holders"'))
  assert.ok(!html.includes('data-company-tab='))
  assert.ok(!html.includes('securityNewsCount'))
  assert.ok(html.includes('fetch_market_pulse') && html.includes('fetch_security_intelligence'))
  assert.ok(nav.indexOf('data-security-tab="market"') < nav.indexOf('data-security-tab="chart"'))
  assert.match(html, /if \(tab === "market" && !marketPulseData && !marketPulseLoading\) \{\s*loadMarketPulse\(\)/)
  assert.match(html, /if \(activeSecurityTab === "sector"\) loadSecurityIntelligence\(currentSymbol, currentName\)/)
  assert.match(html, /companyWorkspaceMarkup\(data\)/)
})
test('market and sector pages have separate data responsibilities', () => {
  const market = html.slice(html.indexOf('function renderMarketWorkspace()'), html.indexOf('function renderSecurityIntelligence()'))
  const sector = html.slice(html.indexOf('function renderSecurityIntelligence()'), html.indexOf('function renderSecurityWorkspace()'))
  const loader = html.slice(html.indexOf('async function loadMarketPulse('), html.indexOf('function setSecurityTab('))
  assert.match(market, /marketPulseData/)
  assert.match(market, /marketOverview/)
  assert.match(market, /marketDirections/)
  assert.doesNotMatch(sector, /marketPulseData/)
  assert.doesNotMatch(sector, /marketOverview/)
  assert.match(sector, /currentIndustry/)
  assert.match(sector, /peerStocks/)
  assert.match(sector, /relatedEtfs/)
  assert.match(loader, /callMarketTool\("fetch_market_pulse", \{ refresh \}\)/)
  assert.match(loader, /callMarketTool\("fetch_security_intelligence", \{ symbol, name, refresh \}\)/)
})
test('market page groups actionable indices by region and sector empty states stay specific', () => {
  const market = html.slice(html.indexOf('function marketIndexGroupsMarkup('), html.indexOf('const INDUSTRY_ETF_REFERENCES'))
  const sector = html.slice(html.indexOf('function renderSecurityIntelligence()'), html.indexOf('function renderSecurityWorkspace()'))
  assert.match(market, /const order = \{ CN: 0, HK: 1, US: 2 \}/)
  assert.match(market, /market-index-card \$\{tone\}/)
  assert.match(market, /data-ticker-symbol/)
  assert.doesNotMatch(market, /market-index-region/)
  assert.match(sector, /peerStocksUnavailable/)
  assert.match(sector, /industryFlowUnavailable/)
  assert.doesNotMatch(sector, /marketPulse\"\)\)<\/h3>/)
})
test('section notices distinguish errors, empty results, unsupported and index data without extra buttons', () => {
  const render = runInNewContext(notice + '; workspaceSectionNotice', {
    t: (key: string) => key, insightEmptyMarkup: (title: string, hint = '') => title + ' ' + hint,
  })
  for (const [state, code, expected] of [
    ['error', 'rate_limited', 'workspaceRateLimited'], ['error', 'auth_required', 'workspaceAuthRequired'],
    ['partial', 'upstream_error', 'workspacePartial'], ['empty', '', 'companyEmpty'],
    ['unsupported', '', 'workspaceUnsupported'], ['not_applicable', '', 'workspaceNotApplicable'],
  ]) {
    const result = render({ sections: { overview: { state, errors: [{ code }] } } }, 'overview')
    assert.ok(result.includes(expected))
    assert.ok(!result.includes('<button'))
  }
  assert.ok(!html.includes('data-workspace-retry'))
})
test('industry labels do not render a fake placeholder value in the sector workspace', () => {
  const source = html.slice(html.indexOf('function intelligenceItemsMarkup('), html.indexOf('function intelligenceSectionMarkup('))
  const markup = runInNewContext(source + '; intelligenceItemsMarkup', {
    escapeHtml: (value: unknown) => String(value),
  })
  const industry = markup([{ title: '食品饮料', value: '', detail: '' }])
  assert.match(industry, /食品饮料/)
  assert.doesNotMatch(industry, />--</)
  const flow = markup([{ title: '有色金属', value: '32.25', change: '3.04%', detail: '20260908' }])
  assert.match(flow, /32\.25 · 3\.04%/)
})
test('board visual grammar renders relative bars and related ETF entry points', () => {
  assert.match(html, /function intelligenceRankMarkup\(/)
  assert.match(html, /intelligence-flow-fill/)
  assert.match(html, /\.intelligence-rank-list \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(html, /\.intelligence-rank-item \{ display: grid; grid-template-columns: 18px minmax\(0, 1fr\) auto/)
  assert.match(html, /function relatedEtfsForIndustry\(/)
  assert.match(html, /data-related-etf-symbol/)
  assert.match(html, /银行ETF/)
})
test('market workspace exposes local direction and leaderboard controls only when data exists', () => {
  const market = html.slice(html.indexOf('function marketSegmentMarkup('), html.indexOf('function renderSecurityIntelligence()'))
  assert.match(market, /data-market-\$\{kind\}/)
  assert.match(market, /marketSegmentMarkup\("direction"/)
  assert.match(market, /marketSegmentMarkup\("ranking"/)
  assert.match(market, /hot_concepts/)
  assert.match(market, /rankings\[marketRankingMode\]/)
  assert.match(market, /market-leaderboard/)
  assert.match(market, /data-ticker-symbol/)
})
test('market values and percentage changes use one directional color rule', () => {
  const source = html.slice(html.indexOf('function intelligenceItemsMarkup('), html.indexOf('const INDUSTRY_ETF_REFERENCES'))
  assert.match(source, /function intelligenceTone\(item\)/)
  assert.match(source, /market-index-price \$\{tone\}/)
  assert.match(source, /market-leader-price \$\{tone\}/)
  assert.match(html, /\.market-index-price\.up, \.market-leader-price\.up \{ color: var\(--up\); \}/)
})
test('watchlist reconciliation preserves additions from a conflicting conversation', () => {
  const source = html.slice(html.indexOf('function normalizeWatchlistPayload('), html.indexOf('async function syncWatchlistFromService('))
  const merge = runInNewContext(source + '; mergeWatchlistStates', {
    WATCHLIST_MAX_GROUPS: 12, WATCHLIST_MAX_ITEMS: 48,
  })
  const merged = merge(
    { revision: 4, updated_at: 20, groups: [{ id: 'default', name: '默认分组' }], items: [{ symbol: '600519.XSHG', name: '贵州茅台', groupId: 'default' }] },
    { revision: 3, updated_at: 10, groups: [{ id: 'default', name: '默认分组' }, { id: 'etf', name: 'ETF' }], items: [{ symbol: '510300.XSHG', name: '沪深300ETF', groupId: 'etf' }] },
  )
  assert.deepEqual(Array.from(merged.items, (item: any) => item.symbol), ['600519.XSHG', '510300.XSHG'])
  assert.equal(merged.groups.some((group: any) => group.id === 'etf'), true)
})
test('basic company profile counts as content even without news or financials', () => {
  const check = runInNewContext(html.slice(html.indexOf('function workspaceHasContent('), html.indexOf('async function loadSecurityWorkspace(')) + '; workspaceHasContent')
  assert.equal(check({ overview: { description: 'Company profile' } }), true)
  assert.equal(check({ overview: { listing_date: '2001-08-27' } }), true)
  assert.equal(check({ overview: { description: '--' } }), false)
})
for (const retry of [false, true]) test(`shared refresh updates information only on manual refresh (retry=${retry})`, async () => {
  const calls: any[] = []
  const state = { chartDataRefreshInFlight: false, currentSymbol: 'A', currentName: 'A name',
    renderMarketDataStatus() {}, setChartStatus() {}, t: (s: string) => s, window: { setTimeout() {} },
    async loadMarketTicker() {},
    async openSymbol(symbol: string, name: string, options: any) { calls.push({ symbol, options }) },
    async loadSecurityWorkspace(symbol: string, name: string, refresh: boolean) { calls.push({ symbol, refresh }) },
  }
  const refresh = runInNewContext(html.slice(html.indexOf('async function refreshMarketData('), html.indexOf('function renderMarketTicker(')) + '; refreshMarketData', state)
  await refresh(retry)
  assert.equal(calls.length, retry ? 1 : 2)
  assert.equal(calls[0].options.refresh, !retry)
  assert.equal(calls[0].options.skipWorkspace, !retry)
  if (!retry) assert.equal(calls[1].refresh, true)
  assert.equal(state.chartDataRefreshInFlight, false)
})
