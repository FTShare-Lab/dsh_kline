import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const renderSource = html.slice(html.indexOf('function setSearchResults('), html.indexOf('function loadSymbolDirectory('))
const directorySource = html.slice(html.indexOf('function loadSymbolDirectory('), html.indexOf('async function refreshSymbolDirectory('))
const searchSource = html.slice(html.indexOf('function scheduleSymbolSearch('), html.indexOf('async function openSymbol('))

function deferred() {
  let resolve!: (value: any) => void, reject!: (reason: any) => void
  const promise = new Promise<any>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function fixture() {
  const input = { value: '紫金' }
  const classes = new Set<string>()
  const results = { innerHTML: '', classList: { add: (name: string) => classes.add(name),
    remove: (name: string) => classes.delete(name), has: (name: string) => classes.has(name) } }
  const requests: Array<{ query: string; deferred: ReturnType<typeof deferred>; options: any }> = []
  const pendingTimers = new Map<number, () => void>()
  let nextTimer = 1
  const state: any = {
    document: { getElementById: (id: string) => ({ symbolSearchInput: input, searchResults: results } as any)[id] },
    window: { setTimeout: (fn: () => void) => { const id = nextTimer++; pendingTimers.set(id, fn); return id },
      clearTimeout: (id: number) => { pendingTimers.delete(id) } },
    symbolSearchResults: [], symbolSearchActiveIndex: -1, symbolSearchDebounceTimer: null, symbolSearchRequestId: 0,
    symbolSearchCache: new Map(), SYMBOL_SEARCH_CACHE_TTL_MS: 30_000,
    cachedSymbolSearch: () => state.localMatches, localMatches: [] as any[],
    mergeSearchResults: (remote: any[]) => remote.length ? remote : state.localMatches,
    scheduleSymbolPrefetch: () => {}, cacheSymbolSearch: () => {},
    normalizeSymbolInput: (query: string) => query.toUpperCase(),
    t: (key: string) => ({ searching: '搜索中…', searchUnavailable: '搜索暂不可用，请重试。', retry: '重试', noResults: '未找到标的' } as any)[key] || key,
    escapeHtml: (value: string) => value,
    callTool: (_name: string, args: any, options: any) => {
      const task = deferred(); requests.push({ query: args.query, deferred: task, options }); return task.promise
    },
  }
  const api: any = runInNewContext(renderSource + searchSource +
    ';({ search: searchSymbols, schedule: scheduleSymbolSearch, close: closeSearchResults })', state)
  return { api, state, input, results, requests, pendingTimers }
}

test('a failed search keeps its dropdown open with an inline retry and a bounded request', async () => {
  const f = fixture()
  const search = f.api.search('紫金')
  assert.match(f.results.innerHTML, /搜索中/)
  assert.equal(f.requests[0].options.timeoutMs, 5000)
  f.requests[0].deferred.reject(Error('network down'))
  await search
  assert.equal(f.results.classList.has('open'), true)
  assert.match(f.results.innerHTML, /搜索暂不可用/)
  assert.match(f.results.innerHTML, /data-search-retry/)
  assert.equal(f.state.symbolSearchResults.length, 0)
})

test('a failed remote search retains locally known symbol buttons', async () => {
  const f = fixture()
  f.state.localMatches = [{ symbol: '601899.XSHG', name: '紫金矿业' }]
  const search = f.api.search('紫金')
  f.requests[0].deferred.reject(Error('network down'))
  await search
  assert.match(f.results.innerHTML, /紫金矿业/)
  assert.match(f.results.innerHTML, /搜索暂不可用/)
  assert.equal(f.state.symbolSearchResults[0].symbol, '601899.XSHG')
})

test('locally known matches do not suppress an uncached exact-name search', async () => {
  const f = fixture()
  f.input.value = '腾讯'
  f.state.cachedSymbolSearch = () => [{ symbol: 'TME.US', name: '腾讯音乐' }]
  const search = f.api.search('腾讯')
  assert.equal(f.requests.length, 1)
  f.requests[0].deferred.resolve({ structuredContent: { ok: true,
    results: [{ symbol: '00700.HK', name: '腾讯控股' }] } })
  await search
  assert.match(f.results.innerHTML, /腾讯控股/)
})

test('search dropdown paints above the rows below its header', () => {
  assert.match(html, /\.symbol-search\s*\{[^}]*z-index:\s*60\s*;/)
  assert.match(html, /@container \(max-width: 760px\)[\s\S]*?\.symbol-search\s*\{\s*position:\s*relative\s*;/)
})

test('a changed or cleared input invalidates old responses before the debounce finishes', async () => {
  const f = fixture()
  const first = f.api.search('紫金')
  f.input.value = '贵州'
  f.api.schedule()
  f.requests[0].deferred.reject(Error('old failure'))
  await first
  assert.doesNotMatch(f.results.innerHTML, /搜索暂不可用/)
  assert.match(f.results.innerHTML, /搜索中/)
  const timer = [...f.pendingTimers.values()][0]
  timer()
  const second = f.requests[1]
  second.deferred.resolve({ structuredContent: { ok: true, results: [{ symbol: '600519.XSHG', name: '贵州茅台' }] } })
  await new Promise(resolve => setImmediate(resolve))
  assert.match(f.results.innerHTML, /贵州茅台/)
  assert.doesNotMatch(f.results.innerHTML, /紫金矿业/)
  f.input.value = ''
  f.api.schedule()
  assert.equal(f.results.classList.has('open'), false)
})

test('closing the dropdown prevents a pending response from reopening it', async () => {
  const f = fixture()
  const search = f.api.search('紫金')
  f.api.close()
  f.requests[0].deferred.resolve({ structuredContent: { ok: true, results: [{ symbol: '601899.XSHG', name: '紫金矿业' }] } })
  await search
  assert.equal(f.results.classList.has('open'), false)
  assert.equal(f.results.innerHTML, '')
})

test('the old v2 key is migrated only when it contains a version-3 directory', () => {
  const storage = new Map<string, string>()
  const state: any = { window: { localStorage: { getItem: (key: string) => storage.get(key),
    setItem: (key: string, value: string) => storage.set(key, value) } },
  SYMBOL_DIRECTORY_STORAGE_KEY: 'dsh-kline.symbol-directory.v3',
  LEGACY_SYMBOL_DIRECTORY_STORAGE_KEY: 'dsh-kline.symbol-directory.v2',
  symbolDirectory: [], symbolDirectoryExpiresAt: 0, symbolDirectoryMeta: {} }
  const load: any = runInNewContext(directorySource + ';loadSymbolDirectory', state)
  storage.set(state.LEGACY_SYMBOL_DIRECTORY_STORAGE_KEY, JSON.stringify({ version: 2, items: [{ symbol: 'BAD', name: '旧结构' }] }))
  load()
  assert.equal(state.symbolDirectory.length, 0)
  storage.set(state.LEGACY_SYMBOL_DIRECTORY_STORAGE_KEY, JSON.stringify({ version: 3, items: [{ symbol: '601899.XSHG', name: '紫金矿业' }] }))
  load()
  assert.equal(state.symbolDirectory[0].name, '紫金矿业')
  assert.equal(JSON.parse(storage.get(state.SYMBOL_DIRECTORY_STORAGE_KEY) || '{}').version, 3)
})

test('search HTTP timeout aborts the request instead of leaving Searching forever', async () => {
  const source = html.slice(html.indexOf('async function callTool('), html.indexOf('function sleep('))
  let aborted = false
  const context: any = { AbortController, encodeURIComponent, JSON, Error,
    window: { setTimeout, clearTimeout },
    sanitizeToolArguments: (value: any) => value,
    fetch: (_url: string, options: any) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => { aborted = true; reject(Error('aborted')) }, { once: true })
    }) }
  const call: any = runInNewContext(source + ';callTool', context)
  await assert.rejects(() => call('search_symbols', { query: '紫金' }, { timeoutMs: 10 }), /aborted/)
  assert.equal(aborted, true)
})
