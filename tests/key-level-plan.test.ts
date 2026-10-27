import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')

test('key-level plan shows each current price only once', () => {
  const source = html.slice(html.indexOf('function activeAutoLevels('), html.indexOf('function levelRowHtml('))
  const plan = runInNewContext(source + '; buildKeyLevelPlan', {
    currentSymbol: '600519.XSHG',
    currentCandles: [{ close: 100 }],
    analysisLevels: [
      { symbol: '600519.XSHG', side: 'support', price: 92 },
      { symbol: '600519.XSHG', side: 'resistance', price: 108 },
      { symbol: '600519.XSHG', side: 'resistance', price: 116 },
      { symbol: '000001.XSHG', side: 'support', price: 1 },
    ],
    t: (key: string) => key,
  })
  const entries = plan()
  assert.deepEqual(Array.from(entries, (entry: any) => [entry.kind, entry.price]), [
    ['support', 92], ['resistance', 108], ['target', 116],
  ])
  assert.ok(entries.every((entry: any) => entry.name && entry.color))
})

test('point panel has one reference list and draws a chosen price only once', () => {
  const panel = html.slice(html.indexOf('id="levelPopover"'), html.indexOf('id="alertMenuBtn"'))
  assert.match(panel, /id="keyLevelPlanCards"/)
  assert.doesNotMatch(panel, /id="analysisLevelList"|转我的/)
  assert.match(html, /data-key-plan-save="true"/)
  assert.match(html, /activeCustomLevels\(\)\.some\(\(item\) => item\.kind === "line"/)
})

test('outdated levels never fall back to current support or resistance', () => {
  const source = html.slice(html.indexOf('function activeAutoLevels('), html.indexOf('function levelRowHtml('))
  const plan = runInNewContext(source + '; buildKeyLevelPlan', {
    currentSymbol: '600519.XSHG', currentCandles: [{ close: 100 }],
    analysisLevels: [
      { symbol: '600519.XSHG', side: 'support', price: 105 },
      { symbol: '600519.XSHG', side: 'resistance', price: 95 },
      { symbol: '600519.XSHG', side: 'resistance', price: 110 },
      { symbol: '600519.XSHG', side: 'resistance', price: 110.2 },
      { symbol: '600519.XSHG', side: 'resistance', price: 120 },
    ],
    t: (key: string) => key,
  })
  assert.deepEqual(Array.from(plan(), (entry: any) => [entry.kind, entry.price]), [
    ['resistance', 110], ['target', 120],
  ])
})

test('a support crossed by a later low is not offered as a current level', () => {
  const source = html.slice(html.indexOf('function activeAutoLevels('), html.indexOf('function levelRowHtml('))
  const plan = runInNewContext(source + '; buildKeyLevelPlan', {
    currentSymbol: '002594.XSHE',
    currentCandles: [{ time: 1, low: 81, high: 86, close: 83 }, { time: 3, low: 78.49, high: 82, close: 81.42 }],
    analysisLevels: [{ symbol: '002594.XSHE', side: 'support', price: 80.11, time: 2 }],
    t: (key: string) => key,
  })
  assert.equal(plan().length, 0)
})

test('key-level data signature changes when an older candle is corrected', () => {
  const source = html.slice(html.indexOf('function keyLevelDataSignature('), html.indexOf('function toggleKeyLevelPlan('))
  const signature = runInNewContext(source + '; keyLevelDataSignature', {
    currentSymbol: '002594.XSHE', currentClearScope: () => '002594.XSHE|day|forward|ytd',
  })
  const rows = [{ time: 1, open: 80, high: 81, low: 79, close: 80 }, { time: 2, open: 80, high: 82, low: 80, close: 81 }]
  const first = signature(rows)
  rows[0].low = 78
  assert.notEqual(signature(rows), first)
  assert.match(html, /if \(keyLevelPlanExpanded && keyLevelPlanCurrentSignature[\s\S]*void analyzeKeyLevels\(\)/)
})

test('analysis candidates are hidden until the user saves a chosen level', () => {
  const start = html.indexOf('function normalizeAutoLevels(')
  const end = html.indexOf('function levelDisplayLabel(')
  const normalize = runInNewContext(html.slice(start, end) + '; normalizeAutoLevels', {
    MAX_CUSTOM_LEVELS: 60,
    LEVEL_COLOR_SEQUENCE: ['danger', 'success', 'warning', 'info'],
    allowedLevelColor: (value: unknown) => ['danger', 'success', 'warning', 'info'].includes(String(value)) ? String(value) : 'info',
    Date,
  })
  const [level] = normalize([{ symbol: '600519.XSHG', markerId: 'support-1', price: 92, side: 'support' }])
  assert.equal(level.visible, false)
  assert.match(html, /activeAutoLevels\(\)\.filter\(\(item\) => item\.visible\)/)
})

test('successful background refreshes never cover the live quote', () => {
  assert.match(html, /if \(state !== "failed"\) \{ dismissActivityNotice\(\); return; \}/)
  assert.match(html, /if \(!failed\) \{ dismissActivityNotice\(\); return; \}/)
  assert.match(html, /\.activity-notice \{ position: absolute; z-index: 30; right: 12px; bottom: 40px;/)
})

test('interactive chart tools use the plugin proxy rather than the host API', () => {
  assert.match(html, /fetch\(`\/dsh-kline\/api\/tools\/\$\{encodeURIComponent\(name\)\}`/)
  assert.doesNotMatch(html, /fetch\(`\/api\/tools\/\$\{encodeURIComponent\(name\)\}`/)
})

test('watchlist rows render last price and signed daily change', () => {
  const source = html.slice(html.indexOf('function quoteForWatchItem('), html.indexOf('function renderWatchlistSummary('))
  const render = runInNewContext(source + '; watchlistItemsMarkup', {
    watchlistQuotes: new Map([['600519.XSHG', { close: 1309.3, changePct: -0.51 }]]),
    watchlistSort: 'manual', selectedWatchSymbols: new Set(), currentSymbol: '',
    escapeHtml: (value: unknown) => String(value), formatTickerNumber: (value: number) => value.toFixed(2),
    t: (key: string) => key,
  })
  const markup = render([{ symbol: '600519.XSHG', name: '贵州茅台', groupId: 'default' }], true)
  assert.match(markup, /1309\.30/)
  assert.match(markup, /-0\.51%/)
  assert.match(markup, /watchlist-quote/)
})
