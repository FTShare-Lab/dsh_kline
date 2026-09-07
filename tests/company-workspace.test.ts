import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const notice = html.slice(html.indexOf('function workspaceSectionNotice('), html.indexOf('function renderSecurityWorkspace('))
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
