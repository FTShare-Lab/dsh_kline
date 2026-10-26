import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const between = (start: string, end: string) => html.slice(html.indexOf(start), html.indexOf(end, html.indexOf(start)))
const hashSource = between('function candleSequenceHash(', 'function drawAgentSeriesLineCommands(')
const cropSource = between('function cropRowsForRange(', 'function aggregateRowsForInterval(')
const viewSource = between('function sourceRowsForCurrentInterval(', 'async function renderCurrentViewLocally(')
const fitSource = between('function fitChartToData(', 'function actionCandle(')
const rangeSource = between('function hasLocalRowsForRange(', 'async function setInterval(')
const rows = Array.from({ length: 120 }, (_, index) => ({
  time: (index + 1) * 86400, open: 30, high: 33, low: 29, close: 32, volume: 100 + index,
}))

function fixture(kind: string) {
  let barSpace = 0
  const state: any = {
    currentSymbol: 'TEST.X', currentName: '测试', currentInterval: 'day', sourceCandleInterval: 'day',
    sourceCandleIntervalValue: 1, sourceCandles: rows, currentCandles: rows, currentRangeKey: 'custom',
    currentAdjust: 'none', customRangeStart: '', customRangeEnd: '',
    localChartDataMeta: { source: 'ftshare' }, lastChartPayload: null,
    legacySequenceRowHashes: new Map(), lastAgentSeriesLines: [], lastAgentPriceBands: [], lastAgentPriceSticks: [],
    lastLines: [], lastMarks: [], lastHorizontalLines: [], lastAgentTrendLines: [], lastAgentChannels: [],
    lastAgentRectangles: [], lastAgentFibonacci: [], lastAgentPolylines: [], lastAgentAnnotations: [],
    buildLocalIndicatorCommands: () => [], activeIndicators: () => [], indicatorStateVersion: 1,
    INDICATOR_HISTORY_BUFFER_DAYS: 0, aggregateRowsForInterval: (value: any) => value.slice(),
    dateInputTimestamp: () => null, isIntradayRange: () => false, isFtshareIntradayUnavailable: () => false,
    RANGE_PRESETS: { '30d': { limit: 60 } }, candleFetchArgs: () => ({ limit: 240 }),
    syncTimeControls() {}, saveWorkspacePreferences() {},
    renderLocalChartWithFeedback: async () => {}, openSymbol: async () => assert.fail('range must not fetch a new candle source'),
    document: { getElementById: () => ({ clientWidth: 900, classList: { remove() {} }, parentElement: { style: { setProperty() {} } } }) },
    MIN_CHART_RENDER_WIDTH: 100, rightAxisGutterWidth: () => 48,
    scheduleChartOverlayRender: () => {},
    kchart: { setBarSpace: (value: number) => { barSpace = value }, setOffsetRightDistance() {} },
  }
  const api = runInNewContext(hashSource + cropSource + viewSource + fitSource + rangeSource
    + ';({hash:candleSequenceHash,view:rowsForCurrentView,build:buildLocalChartPayload,fit:fitChartToData,range:setRange})', state)
  const types: Record<string, string> = { line: 'DRAW_AGENT_SERIES_LINE', band: 'DRAW_AGENT_PRICE_BAND', sticks: 'DRAW_AGENT_PRICE_STICKS' }
  const command = { type: types[kind], id: `${kind}_` + 'a'.repeat(24), interval: 'day',
    bar_count: rows.length, row_hash: api.hash(rows) }
  state.lastChartPayload = { symbol: 'TEST.X', interval: 'day', adjust: 'none',
    chartCommands: [{ type: 'SET_CANDLES', rows }, command] }
  state[{ line: 'lastAgentSeriesLines', band: 'lastAgentPriceBands', sticks: 'lastAgentPriceSticks' }[kind]!].push(command)
  return { state, api, command, barSpace: () => barSpace }
}

for (const kind of ['line', 'band', 'sticks']) test(`${kind} retains exact candle basis across 120→30D→120 without changing object ID`, () => {
  const { state, api, command, barSpace } = fixture(kind)
  state.currentRangeKey = '30d'
  const windowRows = api.view()
  assert.equal(windowRows.length, 120)
  const local = api.build(windowRows, { fitToData: true })
  assert.equal(local.chartCommands[0].rows.length, 120)
  assert.equal(local.chartCommands.at(-1), command)
  assert.equal(local.data_meta.analysis_window.bars, 30)
  assert.equal(local.chartCommands[1].start, rows[90].time)
  api.fit()
  assert.ok(barSpace() > 15, `30D viewport should not fit all 120 bars: ${barSpace()}`)
  state.lastChartPayload = local
  state.currentRangeKey = 'custom'
  assert.equal(api.view().length, 120)
  assert.equal(api.build(api.view()).chartCommands.at(-1), command)
})

test('local redraw carries the TA-Lib result and calculation provenance, not browser formulas', () => {
  const { api } = fixture('line')
  const command = { type: 'SET_INDICATOR_SERIES', name: 'macd', data: { hist: {} } }
  const engine = { name: 'TA-Lib', wrapper_version: '0.8.2' }
  const payload = api.build(rows, {}, { calculation_engine: engine, chartCommands: [command] })
  assert.equal(payload.calculation_engine, engine)
  assert.ok(payload.chartCommands.includes(command))
})

test('changed OHLCV, another symbol, or absent sequence object cannot preserve old basis', () => {
  const { state, api, command } = fixture('sticks')
  state.currentRangeKey = '30d'
  state.sourceCandles = rows.map((row, index) => index === 20 ? { ...row, volume: 999 } : row)
  assert.equal(api.view().length, 30)
  assert.ok(!api.build(api.view()).chartCommands.includes(command))
  state.sourceCandles = rows
  state.currentSymbol = 'OTHER.X'
  assert.equal(api.view().length, 30)
  state.currentSymbol = 'TEST.X'
  state.lastAgentPriceSticks = []
  assert.equal(api.view().length, 30)
})

test('30D button uses the aligned 120-bar local basis even below the 240-bar warmup fetch threshold', async () => {
  const { state, api, command } = fixture('sticks')
  let redraws = 0
  state.renderLocalChartWithFeedback = async () => {
    redraws++
    const payload = api.build(api.view())
    assert.equal(payload.chartCommands[0].rows.length, 120)
    assert.equal(payload.chartCommands.at(-1), command)
  }
  await api.range('30d')
  assert.equal(redraws, 1)
  assert.equal(state.currentRangeKey, '30d')
})
