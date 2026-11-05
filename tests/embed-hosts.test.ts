import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runInNewContext } from 'node:vm'
import { klineHostDataset, sameSymbol, symbolKey } from '../src/client/embed.ts'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const view = readFileSync(resolve(root, 'view/kline.html'), 'utf8')
const entry = readFileSync(resolve(root, 'src/client/index.tsx'), 'utf8')
const generator = readFileSync(resolve(root, 'scripts/generate-client-view.mjs'), 'utf8')

/** `#id` / `.class` in a chrome rule must still exist in the generated view markup. */
function markupHas(selector: string): boolean {
  const attribute = selector.startsWith('#') ? `id="${selector.slice(1)}"` : `class="${selector.slice(1)}"`
  return view.includes(attribute)
}

test('the sidebar mount adds no embedding attribute at all', () => {
  assert.deepEqual(klineHostDataset(), {})
  assert.deepEqual(klineHostDataset({}), {})
  assert.deepEqual(klineHostDataset({ embedded: false, chrome: 'full' }), {})
})

test('a host panel asks for exactly the embedding attributes it needs', () => {
  assert.deepEqual(klineHostDataset({ embedded: true, chrome: 'chart' }), { 'data-embedded': '', 'data-chrome': 'chart' })
  assert.deepEqual(klineHostDataset({ embedded: true, chrome: 'chart-search' }), { 'data-embedded': '', 'data-chrome': 'chart-search' })
  assert.deepEqual(klineHostDataset({ embedded: true }), { 'data-embedded': '' })
})

test('slots and canvas stay optional: the plugin still requires only sessions', () => {
  assert.match(entry, /export const inject = \['sessions'\]/)
  assert.doesNotMatch(entry, /export const inject = \[[^\]]*'slots'/)
  assert.doesNotMatch(entry, /export const inject = \[[^\]]*'canvas'/)
})

test('the chrome sheet only matches host attributes, and keeps the chart page', () => {
  for (const mode of ['chart', 'chart-search']) {
    for (const hidden of [':host([data-chrome="' + mode + '"]) #securityNav', ':host([data-chrome="' + mode + '"]) #marketTicker', ':host([data-chrome="' + mode + '"]) #watchlistRail']) {
      assert.ok(view.includes(hidden), `missing rule: ${hidden}`)
    }
  }
  assert.ok(view.includes(':host([data-chrome="chart"]) .workspace-bar'), 'chart mode hides the whole workspace bar')
  assert.ok(view.includes(':host([data-chrome="chart-search"]) .brand'), 'chart-search hides the brand')
  assert.ok(view.includes(':host([data-chrome="chart-search"]) .header-controls'), 'chart-search hides only the header controls')
  assert.ok(!/\[data-chrome="(?:chart|chart-search)"\][^{]*\.symbol-search/.test(view), 'the symbol search must stay visible')
  for (const selector of ['#securityNav', '#marketTicker', '#watchlistRail', '.workspace-bar', '.brand', '.header-controls']) {
    assert.ok(markupHas(selector), `view markup no longer carries ${selector}`)
  }
  for (const kept of ['#klineChart', '.timebar', '.toolbar', '#chartWorkspacePanel']) {
    assert.ok(markupHas(kept), `${kept} belongs to the chart page and must exist`)
    assert.ok(!/data-chrome="(?:chart|chart-search)"\][^{]*\s\$\{kept\}/.test(view), `${kept} must not be hidden by the chrome sheet`)
  }
})

test('an embedded chart anchors its dialogs to the panel', () => {
  assert.ok(view.includes(':host([data-embedded]) .group-dialog-backdrop'))
  assert.ok(view.includes(':host([data-embedded]) .welcome-backdrop'))
})

test('the view installs its host bridge only for an embedded mount', () => {
  // The bridge is what a React host talks to; a sidebar view must not create it.
  assert.match(view, /if \(embedded\) \{\s*window\.__DSH_KLINE_EMBED__ = \{/)
  assert.ok(view.includes('window.__DSH_KLINE_EMBED__ = {'))
  // Host facts reach the runtime through the dependency bridge, not attributes.
  assert.ok(generator.includes("'__DSH_KLINE_EMBEDDED__'"))
  assert.ok(generator.includes("'__DSH_KLINE_THEME__'"))
  assert.ok(generator.includes('dependencies.onReady'))
})

test('the embedded flag is script-scoped, never a free variable at the bridge', () => {
  // A `const embedded` inside init() shadows nothing, but leaves the bridge
  // below reading an undeclared name — the mount then dies with
  // "embedded is not defined" before the host ever hears it is ready.
  const runtime = view.slice(view.lastIndexOf('<script>') + '<script>'.length, view.lastIndexOf('</script>'))
  const declaration = 'const embedded = Boolean(window.__DSH_KLINE_EMBEDDED__)'
  const declaredAt = runtime.indexOf(declaration)
  const initAt = runtime.indexOf('async function init()')
  const bridgeAt = runtime.lastIndexOf('if (embedded) {')
  assert.ok(declaredAt >= 0, 'the runtime must declare the embedded flag')
  assert.ok(declaredAt < initAt, 'the declaration belongs above init(), at script scope')
  assert.equal(runtime.split(declaration).length - 1, 1, 'exactly one declaration; a second inside init() would shadow it')
  assert.ok(bridgeAt > initAt, 'the host bridge is a top-level branch after init()')
})

test('equivalent exchange aliases and bare chart inputs keep one identity', () => {
  assert.equal(symbolKey('600519.SH'), '600519.XSHG')
  assert.equal(symbolKey(' 000001.xshe '), '000001.XSHE')
  for (const [left, right] of [
    ['600519', '600519.SH'], ['SH600519', '600519.XSHG'],
    ['000001.SZ', '000001.XSHE'], ['BJ920000', '920000.BJSE'],
    ['700', '00700.HK'], ['700.HKG', '00700.HK'],
    ['v', 'V.US'], ['V.NYSE', 'V.US'], ['AAPL.NASDAQ', 'AAPL.US'],
  ]) {
    assert.ok(sameSymbol(left, right), `${left} and ${right}`)
    assert.ok(sameSymbol(right, left), `${right} and ${left}`)
  }
})

test('different markets, ticker prefixes and share classes must trigger a symbol change', () => {
  for (const [left, right] of [
    ['000001.XSHG', '000001.XSHE'], ['000001.SH', '000001.SZ'],
    ['000001', '000001.XSHG'], ['000001.HK', '000001.XSHE'],
    ['V.US', 'VZ.US'], ['BRK.US', 'BRK.B.US'], ['BRK.A.US', 'BRK.B.US'],
    ['007.HK', '00700.HK'], ['600519', '600520'],
    ['', ''], ['   ', '600519'], [undefined, '600519'],
  ]) {
    assert.ok(!sameSymbol(left, right), `${left} and ${right}`)
    assert.ok(!sameSymbol(right, left), `${right} and ${left}`)
  }
})

test('bare and exchange-qualified host inputs agree with actual chart routing', () => {
  const start = view.indexOf('function normalizeSymbolInput(')
  const end = view.indexOf('function directoryEntryForSymbol(', start)
  const normalize = runInNewContext(view.slice(start, end) + '; normalizeSymbolInput')
  for (const input of ['600519', '000001', '920000', 'SH600519', 'SZ000001', 'BJ920000',
    '600519.SH', '000001.XSHG', '000001.SZ', '920000.BJ', '700', '700.HKG', '00700.HK', 'v', 'VZ.US']) {
    assert.equal(symbolKey(input), normalize(input), input)
  }
})
