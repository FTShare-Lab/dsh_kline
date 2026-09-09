import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')

test('key-level plan turns support and resistance into five saveable reference cards', () => {
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
    ['support', 92], ['resistance', 108], ['breakout', 108], ['stop', 92], ['target', 116],
  ])
  assert.ok(entries.every((entry: any) => entry.name && entry.color))
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
