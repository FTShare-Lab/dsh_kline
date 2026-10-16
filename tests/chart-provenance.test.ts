import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { TEST_PYTHON } from '../scripts/test-runtime.mjs'
import { runInNewContext } from 'node:vm'
import { sanitizeChartContext, sanitizeDataProvenance, observationKey } from '../src/chart-observation.ts'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const rows = [1, 2].map(time => ({ time, open: 31, high: 33, low: 30, close: 32, volume: 1 }))
function state(extra: any = {}): any {
  return { state: 'ready', symbol: 'TEST.X', interval: 'week', source_interval: 'day',
    candles: rows, drawings: [], data_provenance: { provider: 'ftshare', transformation: 'local_aggregation',
      aggregation: { timezone: 'Asia/Shanghai', completeness: 'complete', secret: 'test-secret' }, secret: 'test-secret' }, ...extra }
}
function collector() {
  const context: any = { activeSecurityTab: 'chart', currentSymbol: 'TEST.X', currentName: '测试',
    currentInterval: 'day', sourceCandleInterval: 'day', currentRangeKey: 'custom', currentAdjust: 'none',
    currentCandles: rows, lastChartPayload: { symbol: 'TEST.X', interval: 'day', data_meta: { source: 'ftshare' } },
    openingSymbol: false, kchart: {}, userDrawings: [], customLevels: [], analysisLevels: [], currentSelection: null,
    maVisible: false, vwapVisible: false, volVisible: true, macdVisible: false, kdjVisible: false,
    bollVisible: false, rsiVisible: false, atrVisible: false, chartDataStatus: 'delayed', volumeUnit: 'wan',
    exchangeTimezone: 'Asia/Shanghai', chartDataSource: 'ftshare' }
  const source = html.slice(html.indexOf('function captureChartContext('), html.indexOf('function refreshMirrorAxes('))
  const capture = runInNewContext(source + '; captureChartContext', context)
  return { context, read: () => sanitizeChartContext(capture('a'.repeat(32))) }
}

test('browser input provenance is additive, bounded, read-only, and independent of snapshot alignment', () => {
  const raw = state(), cleaned = sanitizeChartContext(raw)
  assert.deepEqual(cleaned.candles, rows)
  assert.equal(cleaned.source_snapshot_alignment, 'not_verified')
  assert.equal(cleaned.live_view_editable, false)
  assert.equal(cleaned.render_verified, false)
  assert.equal(cleaned.data_provenance.provider, 'ftshare')
  assert.equal(cleaned.data_provenance.aggregation.bucket, 'calendar_week_monday')
  assert.equal(cleaned.data_provenance.aggregation.timestamp, 'last_source_bar')
  assert.equal(cleaned.data_provenance.aggregation.order, 'aggregate_before_range_crop')
  assert.equal(cleaned.data_provenance.aggregation.completeness, 'not_verified')
  assert.ok(!JSON.stringify(cleaned).includes('test-secret'))
  const changed = state(); changed.data_provenance.provider = 'eastmoney_free'
  assert.notEqual(observationKey(raw), observationKey(changed))
  changed.data_provenance.secret = 'different-secret'
  assert.equal(observationKey(changed), observationKey({ ...changed, data_provenance: { ...changed.data_provenance, secret: null } }))
})

test('Node and Python apply the same whitelist, unknown fallback, interval relation and timezone rules', () => {
  const cases: any[] = [state(), state({ data_provenance: undefined }), state({ data_provenance: 'bad' }),
    ...['loading', 'not_chart', 'empty', 'error'].map(value => state({ state: value })),
    ...['minute', 'day', 'week', 'month', 'quarter', 'year'].map(interval => state({ interval, source_interval: interval,
      data_provenance: { provider: 'external', transformation: 'none' } })),
    ...['week', 'month', 'quarter', 'year'].map(interval => state({ interval })),
    state({ source_interval: 'minute' }), state({ source_interval: '' }),
    ...['https://example.test/?key=test-secret', 'mcp', { secret: 'test-secret' }, 'FTShare'].map(provider => state({
      data_provenance: { provider, transformation: 'local_aggregation', aggregation: { timezone: 'Asia/Shanghai' } } })),
    ...['UTC', 'America/New_York', 'Asia/Hong_Kong', 'Etc/GMT+8', '../test-secret', 'Invalid/Zone', null, {}].map(timezone => state({
      data_provenance: { provider: 'tencent_free', transformation: 'local_aggregation', aggregation: { timezone } } })),
    state({ data_provenance: { provider: 'builtin_free', transformation: 'none' } }),
    state({ data_provenance: { provider: 'ftshare', transformation: 'guessed', aggregation: [] } })]
  const expected = cases.map(sanitizeDataProvenance)
  const child = spawnSync(TEST_PYTHON, ['-c',
    'import json,sys; from tools.chart_context import sanitize_data_provenance; print(json.dumps([sanitize_data_provenance(s) for s in json.load(sys.stdin)]))'],
    { input: JSON.stringify(cases), encoding: 'utf8' })
  assert.equal(child.status, 0, child.stderr)
  assert.deepEqual(JSON.parse(child.stdout), expected)
  for (const [index, result] of expected.entries()) {
    assert.ok(!JSON.stringify(result).includes('test-secret'), String(index))
    if (cases[index].state !== 'ready') assert.deepEqual(result, { scope: 'browser_input_to_display', provider: 'unknown',
      source_interval: null, display_interval: null, transformation: 'unknown', aggregation: null })
  }
  assert.equal(expected[1].transformation, 'unknown') // older clients are not guessed
  assert.equal(expected[17].transformation, 'unknown') // minute input cannot claim daily aggregation
})

test('actual collector distinguishes native week, daily fetch and local week; intraday UI label is not a transform', () => {
  const { context, read } = collector()
  assert.equal(read().data_provenance.transformation, 'none')
  context.sourceCandleInterval = 'week'; context.currentInterval = 'week'; context.lastChartPayload.interval = 'week'
  assert.equal(read().data_provenance.source_interval, 'week')
  assert.equal(read().data_provenance.transformation, 'none')
  context.sourceCandleInterval = 'day'; context.currentInterval = 'day'; context.lastChartPayload.interval = 'day'
  assert.equal(read().data_provenance.transformation, 'none')
  context.currentInterval = 'week'; context.lastChartPayload.interval = 'week'; context.lastChartPayload.local_render = true
  assert.equal(read().data_provenance.transformation, 'local_aggregation')
  context.lastChartPayload.local_render = false
  assert.equal(read().data_provenance.transformation, 'unknown') // no inference from unequal labels alone
  context.sourceCandleInterval = 'minute'; context.currentInterval = 'day'; context.lastChartPayload.interval = 'day'
  context.lastChartPayload.interval_value = 5
  context.sourceCandleIntervalValue = 5
  assert.equal(read().ui_interval, 'day'); assert.equal(read().interval, 'minute')
  assert.equal(read().data_provenance.transformation, 'none')
  delete context.lastChartPayload.data_meta
  assert.equal(read().data_provenance.provider, 'unknown') // not the global FTShare badge
  context.lastChartPayload.symbol = 'OTHER.X'
  assert.equal(read().state, 'loading'); assert.equal(read().data_provenance.provider, 'unknown')
})

test('new candle metadata cannot inherit the previous provider; drawing-only payload cannot replace source provenance', () => {
  const start = html.indexOf('    if (!structured.local_render) {', html.indexOf('async function handleToolResult('))
  const end = html.indexOf('    const previousSymbol', start)
  const context: any = { structured: { interval: 'week', chartCommands: [{ type: 'SET_CANDLES', rows }] },
    sourceCandles: [], sourceCandleInterval: 'day', localChartDataMeta: { source: 'ftshare' } }
  runInNewContext(html.slice(start, end), context)
  assert.equal(context.localChartDataMeta, null); assert.equal(context.sourceCandleInterval, 'week')
  context.structured = { interval: 'day', chartCommands: [] }
  context.localChartDataMeta = { source: 'external' }
  runInNewContext(html.slice(start, end), context)
  assert.equal(context.localChartDataMeta.source, 'external'); assert.equal(context.sourceCandleInterval, 'week')
})

test('workspace restoration preserves input provider metadata together with source rows and interval', async () => {
  const remember = html.slice(html.indexOf('function rememberWorkspaceTab('), html.indexOf('async function selectWorkspaceTab('))
  const select = html.slice(html.indexOf('async function selectWorkspaceTab('), html.indexOf('async function closeWorkspaceTab('))
  const context: any = { currentSymbol: 'TEST.X', currentName: '测试', currentRangeKey: 'custom', currentInterval: 'week',
    sourceCandles: rows, sourceCandleInterval: 'day', localChartDataMeta: { source: 'external' }, workspaceTabs: [],
    activeWorkspaceTabId: '', workspaceTabId: () => 'TEST.X', renderWorkspaceTabs() {}, saveWorkspacePreferences() {},
    securityWorkspaceData: {}, securityWorkspaceLoading: false, securityIntelligenceData: {}, securityIntelligenceLoading: false,
    activeSecurityTab: 'chart', activeCompanyTab: 'overview', clearRangePick() {}, securityWorkspaceRequestId: 0,
    securityIntelligenceRequestId: 0, syncTimeControls() {}, rememberAnalysisCommands() {},
    handleToolResult() { assert.equal(context.localChartDataMeta.source, 'external') } }
  const functions = runInNewContext(remember + select + '; ({rememberWorkspaceTab,selectWorkspaceTab})', context)
  functions.rememberWorkspaceTab({ symbol: 'TEST.X', interval: 'week', adjust: 'forward', local_render: true })
  context.currentAdjust = 'backward'
  context.localChartDataMeta = { source: 'ftshare' }; context.activeWorkspaceTabId = 'OTHER.X'
  await functions.selectWorkspaceTab('TEST.X')
  assert.equal(context.sourceCandleInterval, 'day'); assert.deepEqual(context.sourceCandles, rows)
  assert.equal(context.localChartDataMeta.source, 'external')
  assert.equal(context.currentAdjust, 'forward')
})
