import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
function source(start: string, end: string) {
  return html.slice(html.indexOf(start), html.indexOf(end, html.indexOf(start)))
}
const content = source('function workspaceHasContent(', 'function workspaceHasRateLimit(')
const recovery = source('function mergeSecurityWorkspace(', 'function clearSecurityWorkspaceRetry(')
const loader = source('async function loadSecurityWorkspace(', 'async function loadMarketPulse(')
const notice = source('function reloadIconMarkup(', 'function intelligenceItemsMarkup(')
const previous = () => ({ symbol: '000530.XSHE', source: { name: 'FTShare', updated_at: 'old timestamp' },
  news: [{ title: 'Previously loaded article' }], sections: { news: { state: 'available' } } })

test('news errors distinguish service, network, permission and SDK failures and offer an inline retry', () => {
  const context = { t: (key: string) => key, escapeHtml: String, securityWorkspaceLoading: false,
    insightEmptyMarkup: (title: string, hint: string, action: string) => `${title} ${hint} ${action}` }
  const render = runInNewContext(notice + '; workspaceSectionNotice', context)
  for (const [code, expected] of [
    ['upstream_error', 'workspaceUpstreamFailed'], ['upstream_unavailable', 'workspaceConnectionFailed'],
    ['capability_limited', 'workspaceAccessDenied'], ['rate_limited', 'workspaceRateLimited'],
    ['sdk_contract_mismatch', 'workspaceSdkMismatch'], ['request_rejected', 'workspaceRequestRejected'],
    ['unknown', 'workspaceRequestFailed'],
  ]) {
    const markup = render({ sections: { news: { state: 'error', errors: [{ code }] } } }, 'news')
    assert.ok(markup.includes(expected), code)
    assert.match(markup, /data-workspace-retry/)
    if (code !== 'upstream_unavailable') assert.ok(!markup.includes('workspaceConnectionFailed'))
  }
  context.securityWorkspaceLoading = true
  assert.match(render({ sections: { news: { state: 'error' } } }, 'news'), /disabled/)
})

test('failed news refresh retains articles and their original timestamp while fresh company data updates', () => {
  const merge = runInNewContext(content + recovery + '; mergeSecurityWorkspace')
  const old = previous()
  const incoming = { symbol: old.symbol, source: { name: 'FTShare', updated_at: 'new timestamp' }, news: [],
    overview: { description: 'New company profile' },
    sections: { news: { state: 'error', errors: [{ code: 'upstream_error' }] }, overview: { state: 'available' } } }
  const next = merge(old, incoming)
  assert.equal(next.news, old.news)
  assert.equal(next.overview.description, 'New company profile')
  assert.equal(next.sections.news.state, 'partial')
  assert.equal(next.sections.news.retained_at, 'old timestamp')
  assert.equal(incoming.sections.news.state, 'error')
  assert.equal(old.sections.news.state, 'available')
  const twice = merge(next, incoming)
  assert.equal(twice.sections.news.retained_at, 'old timestamp')
  const footerSource = source('function workspaceSourceText(', 'function syncSecurityNavigation(')
  const footer = runInNewContext(footerSource + '; workspaceSourceFooter', { t: String, escapeHtml: String })
  assert.match(footer(next, 'news'), /old timestamp/)
  assert.doesNotMatch(footer(next, 'news'), /new timestamp/)
})

test('successful empty results replace old news and data never crosses symbols', () => {
  const merge = runInNewContext(content + recovery + '; mergeSecurityWorkspace')
  const empty = { symbol: '000530.XSHE', news: [], sections: { news: { state: 'empty' } } }
  assert.equal(merge(previous(), empty).news.length, 0)
  const other = { symbol: '600519.XSHG', news: [], sections: { news: { state: 'error' } } }
  assert.equal(merge(previous(), other), other)
})

test('a partial company module shows retained data alongside the warning', () => {
  const render = runInNewContext(source('function companyModuleMarkup(', 'function companyWorkspaceMarkup(') + '; companyModuleMarkup', {
    workspaceSectionState: () => 'partial', workspaceSectionIsRateLimited: () => false,
    workspaceSectionNotice: () => '<p>Refresh failed; retained content</p>', escapeHtml: String,
  })
  const markup = render({}, 'overview', 'Company', () => '<p>Existing company profile</p>')
  assert.match(markup, /retained content/)
  assert.match(markup, /Existing company profile/)
})

function loadContext(old: any, request: () => Promise<any>) {
  const tab = { workspace: old, workspaceLoading: false }
  const context = {
    currentSymbol: '000530.XSHE', currentName: '冰山冷热', securityWorkspaceData: old,
    securityWorkspaceLoading: false, securityWorkspaceRequestId: 0,
    securityWorkspaceRequestTokens: new Map(), prefetchedWorkspaces: new Map(), workspacePrefetchTasks: new Map(),
    workspaceTabForSymbol: () => tab, freshPrefetchedWorkspace: () => null,
    renderSecurityWorkspace() {}, renderMarketTicker() {}, reportSize() {}, showActivityNotice() {}, finishActivityNotice() {},
    workspaceHasRateLimit: () => false, clearSecurityWorkspaceRetry() {}, t: String,
    console: { warn() {}, info() {} }, callMarketTool: request,
  }
  const load = runInNewContext(content + recovery + loader + '; loadSecurityWorkspace', context)
  return { load, context, tab }
}

test('transport failure is recorded on first load instead of being swallowed', async () => {
  const { load, context, tab } = loadContext(null, async () => { throw Object.assign(new Error('backend timed out'), { code: 'backend_timeout' }) })
  await load('000530.XSHE', '冰山冷热')
  assert.equal(context.securityWorkspaceData.sections.news.errors[0].code, 'backend_timeout')
  assert.equal(tab.workspace.sections.news.state, 'error')
  assert.equal(tab.workspaceLoading, false)
  assert.equal(context.securityWorkspaceLoading, false)
})

test('failed refresh preserves existing news, and inline retry bypasses cached failure and recovers', async () => {
  const calls: any[] = []
  const { load, context } = loadContext(previous(), async () => { throw new TypeError('Failed to fetch') })
  await load('000530.XSHE', '冰山冷热', true)
  assert.equal(context.securityWorkspaceData.sections.news.state, 'partial')
  assert.equal(context.securityWorkspaceData.sections.news.retained, true)
  assert.equal(context.securityWorkspaceData.news[0].title, 'Previously loaded article')
  context.prefetchedWorkspaces.set('000530.XSHE', {})
  context.callMarketTool = async (...args: any[]) => {
    calls.push(args)
    return { ok: true, security_workspace: { ...previous(), news: [{ title: 'Recovered' }] } }
  }
  const retry = runInNewContext(recovery + '; retrySecurityWorkspace', { ...context, loadSecurityWorkspace: load })
  await retry()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'fetch_security_workspace')
  assert.equal(calls[0][1].refresh, true)
  assert.equal(context.prefetchedWorkspaces.size, 0)
  assert.equal(context.securityWorkspaceData.news[0].title, 'Recovered')
  assert.equal(context.securityWorkspaceData.sections.news.retained, undefined)
})

test('reload visibly replaces a previous error, disables the button and retains loaded articles', () => {
  const panels = Object.fromEntries(['newsWorkspacePanel', 'companyWorkspacePanel'].map(id => [id, {
    innerHTML: '', attributes: {} as Record<string, string>,
    setAttribute(name: string, value: string) { this.attributes[name] = value },
  }]))
  const failed = { ...previous(), news: [], sections: { news: { state: 'error', errors: [{ code: 'upstream_error', http_status: 502 }] } } }
  const state = { securityWorkspaceLoading: true, currentSecurityWorkspace: () => failed,
    document: { getElementById: (id: string) => panels[id] },
    syncSecurityNavigation() {}, renderMarketTicker() {}, renderMarketWorkspace() {}, renderDragonWorkspace() {}, renderSecurityIntelligence() {},
    workspaceSourceFooter: () => '', companyWorkspaceMarkup: () => '', escapeHtml: String, t: String,
  }
  const markup = source('function insightEmptyMarkup(', 'function intelligenceItemsMarkup(')
  const render = runInNewContext(markup + source('function renderSecurityWorkspace(', 'function workspaceHasContent(') + '; renderSecurityWorkspace', state)
  render()
  assert.match(panels.newsWorkspacePanel.innerHTML, /workspaceReloading/)
  assert.match(panels.newsWorkspacePanel.innerHTML, /reload-icon/)
  assert.match(panels.newsWorkspacePanel.innerHTML, /disabled/)
  assert.equal(panels.newsWorkspacePanel.attributes['aria-busy'], 'true')
  assert.doesNotMatch(panels.newsWorkspacePanel.innerHTML, /HTTP 502/)
  state.securityWorkspaceLoading = false
  render()
  assert.match(panels.newsWorkspacePanel.innerHTML, /HTTP 502/)
  assert.match(panels.newsWorkspacePanel.innerHTML, /workspaceUpstreamFailed/)
  assert.doesNotMatch(panels.newsWorkspacePanel.innerHTML, /workspaceConnectionFailed|disabled/)
  state.currentSecurityWorkspace = () => previous() as any
  state.securityWorkspaceLoading = true
  render()
  assert.match(panels.newsWorkspacePanel.innerHTML, /Previously loaded article/)
  assert.match(panels.newsWorkspacePanel.innerHTML, /workspaceReloading/)
})

test('news and company page refresh dispatch only one forced information request', async () => {
  for (const page of ['news', 'company']) {
    let complete!: () => void
    let calls = 0
    const request = new Promise<void>(resolve => { complete = resolve })
    const state = { activeSecurityTab: page, securityWorkspaceLoading: false,
      currentSymbol: '000530.XSHE', currentName: '冰山冷热', chartDataRefreshInFlight: false,
      renderMarketDataStatus() {}, renderMarketTicker() {}, setChartStatus() {}, t: String,
      window: { setTimeout() {} },
      retrySecurityWorkspace: () => { calls++; return request },
      loadMarketTicker: () => { throw Error('info retry must not wait for ticker') },
      openSymbol: () => { throw Error('info retry must not replace chart') },
    }
    const refresh = runInNewContext(source('async function refreshMarketData(', 'function marketRefreshButtonMarkup(') + '; refreshMarketData', state)
    const pending = refresh()
    assert.equal(state.chartDataRefreshInFlight, true)
    await refresh()
    assert.equal(calls, 1)
    complete()
    await pending
    assert.equal(state.chartDataRefreshInFlight, false)
  }
})

test('tool deadline releases a hung MCP host even when fetch ignores AbortSignal', async () => {
  let expire!: () => void
  let finish!: (value: any) => void
  let cleared = false
  const request = new Promise(resolve => { finish = resolve })
  const call = runInNewContext(source('async function callTool(', 'function sleep(') + '; callTool', {
    sanitizeToolArguments: (args: any) => args, AbortController, fetch: () => request,
    window: { setTimeout(callback: () => void) { expire = callback; return 1 }, clearTimeout() { cleared = true } },
  })
  const pending = call('fetch_security_workspace', { symbol: '000530.XSHE' }, { timeoutMs: 45000 })
  expire()
  await assert.rejects(pending, (error: any) => error.code === 'backend_timeout')
  assert.equal(cleared, true)
  finish({ ok: true, json: async () => ({ ok: true }) })
  // A late host response must not turn the rejected request into a success.
  await assert.rejects(pending, (error: any) => error.code === 'backend_timeout')
})

test('the deadline covers decoding a response body, not just receiving headers', async () => {
  let expire!: () => void
  const call = runInNewContext(source('async function callTool(', 'function sleep(') + '; callTool', {
    sanitizeToolArguments: (args: any) => args, AbortController,
    fetch: async () => ({ ok: true, json: () => new Promise(() => {}) }),
    window: { setTimeout(callback: () => void) { expire = callback; return 1 }, clearTimeout() {} },
  })
  const pending = call('fetch_security_workspace', {}, { timeoutMs: 45000 })
  expire()
  await assert.rejects(pending, (error: any) => error.code === 'backend_timeout')
})

test('workspace requests bypass caches with a finite deadline and no duplicate automatic retry', async () => {
  const calls: any[] = []
  const { load, context } = loadContext(null, async (...args: any[]) => {
    calls.push(args)
    return { ok: true, security_workspace: previous() }
  })
  context.prefetchedWorkspaces.set('000530.XSHE', previous())
  await load('000530.XSHE', '冰山冷热', true)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].refresh, true)
  assert.equal(calls[0][2], 1)
  assert.equal(calls[0][3].timeoutMs, 45000)
  assert.equal(context.prefetchedWorkspaces.size, 0)
})

test('failed requests and retained content have distinct timestamp labels', () => {
  const render = runInNewContext(source('function workspaceSourceText(', 'function syncSecurityNavigation(') + '; workspaceSourceFooter', { t: String, escapeHtml: String })
  const failed = { ...previous(), sections: { news: { state: 'error' } } }
  assert.match(render(failed, 'news'), /workspaceLastAttempt/)
  const retained = { ...previous(), sections: { news: { state: 'partial', retained: true, retained_at: 'previous success' } } }
  assert.match(render(retained, 'news'), /workspaceLastSuccess: previous success/)
  assert.doesNotMatch(render(retained, 'news'), /workspaceLastAttempt/)
})

test('company data cannot turn a news failure into a successful news notification', async () => {
  const notices: any[] = []
  const { load, context } = loadContext(null, async () => ({ ok: true, security_workspace: {
    symbol: '000530.XSHE', news: [], overview: { description: 'Company data exists' },
    sections: { news: { state: 'error', errors: [{ code: 'upstream_error' }] }, overview: { state: 'available' } },
  } }))
  Object.assign(context, { activeSecurityTab: 'news', finishActivityNotice: (...args: any[]) => notices.push(args) })
  await load('000530.XSHE', '冰山冷热', true)
  assert.deepEqual(notices, [['workspaceLoadFailed', true]])
})

test('company refresh reports company results even when news is unavailable', async () => {
  const notices: any[] = []
  const { load, context } = loadContext(null, async () => ({ ok: true, security_workspace: {
    symbol: '000530.XSHE', news: [], overview: { description: 'Company data exists' },
    sections: { news: { state: 'error' }, overview: { state: 'available' } },
  } }))
  Object.assign(context, { activeSecurityTab: 'company', finishActivityNotice: (...args: any[]) => notices.push(args) })
  await load('000530.XSHE', '冰山冷热', true)
  assert.deepEqual(notices, [['workspaceCompanyUpdated', false]])
})

test('a pending prefetch has a deadline and reports its failure without starting another request', async () => {
  let reject!: (error: Error) => void
  const pending = new Promise((_, fail) => { reject = fail })
  const calls: any[] = []
  const { load, context } = loadContext(null, (...args: any[]) => { calls.push(args); return pending })
  const prefetch = runInNewContext(recovery + source('async function prefetchSecurityWorkspace(', 'async function prefetchSymbolData(') + '; prefetchSecurityWorkspace', context)
  const warmed = prefetch('000530.XSHE', '冰山冷热')
  const loaded = load('000530.XSHE', '冰山冷热')
  reject(Object.assign(new Error('prefetch timed out'), { code: 'backend_timeout' }))
  await Promise.all([warmed, loaded])
  assert.equal(calls.length, 1)
  assert.equal(calls[0][3].timeoutMs, 45000)
  assert.equal(context.securityWorkspaceData.sections.news.errors[0].code, 'backend_timeout')
  assert.equal(context.securityWorkspaceLoading, false)
  assert.equal(context.prefetchedWorkspaces.size, 0)
})

test('the footer busy state follows the selected page instead of a background news request', () => {
  const context = { activeSecurityTab: 'news', securityWorkspaceLoading: true, chartDataRefreshInFlight: false, t: String, escapeHtml: String }
  const icon = source('function reloadIconMarkup(', 'function workspaceReloadButton(')
  const render = runInNewContext(icon + source('function marketRefreshButtonMarkup(', 'function renderMarketTicker(') + '; marketRefreshButtonMarkup', context)
  assert.match(render(), /disabled/)
  context.activeSecurityTab = 'chart'
  assert.doesNotMatch(render(), /disabled/)
  context.activeSecurityTab = 'news'
  context.securityWorkspaceLoading = false
  assert.doesNotMatch(render(), /disabled/)
  assert.match(source('function renderSecurityWorkspace(', 'function workspaceHasContent('), /renderMarketTicker\(\)/)
})
