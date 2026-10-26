import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const between = (start: string, end: string) => html.slice(html.indexOf(start), html.indexOf(end, html.indexOf(start)))
const requestSource = between('async function requestTaIndicatorCommands(', 'function sourceRowsForCurrentInterval(')
const renderSource = between('async function renderCurrentViewLocally(', 'async function renderLocalChartWithFeedback(')
const rows = [1, 2, 3].map(index => ({ time: index * 86400, open: 30, high: 31, low: 29, close: 30 + index, volume: 100 }))

function fixture(callTool: (name: string, args: any) => Promise<any>) {
  const state: any = {
    callTool, taIndicatorCache: new Map(), localIndicatorRequestId: 0,
    indicatorConfig: { maPeriods: [5, 20], volumeMa: 5, bollPeriod: 20, bollStd: 2, rsiPeriod: 14, atrPeriod: 14 },
    activeIndicators: () => ['ma', 'macd', 'atr'],
    candleSequenceHash: (value: any[]) => `hash:${value.map(row => `${row.time}/${row.close}`).join(',')}`,
    currentSymbol: 'TEST.X', currentInterval: 'day', currentRangeKey: '30d', currentAdjust: 'none', indicatorStateVersion: 1,
    rowsForCurrentView: () => rows, sourceRowsForCurrentInterval: () => rows,
    buildLocalChartPayload: (_rows: any, _options: any, result: any) => result,
    handleToolResult: async (_result: any) => {},
  }
  const api = runInNewContext(requestSource + renderSource
    + ';({request:requestTaIndicatorCommands,render:renderCurrentViewLocally})', state)
  return { state, api }
}

function accepted(args: any) {
  return { structuredContent: { ok: true, source_hash: args.expected_hash, loaded_bars: args.rows.length,
    calculation_engine: { name: 'TA-Lib', wrapper_version: '0.8.2' },
    chartCommands: args.indicators.map((name: string) => ({ type: 'SET_INDICATOR_SERIES', name, data: {} })) } }
}

test('browser requests pinned TA-Lib series on exact loaded rows and caches by full source identity', async () => {
  const calls: any[] = []
  const { api } = fixture(async (name, args) => { calls.push({ name, args }); return accepted(args) })
  const first = await api.request(rows)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].name, 'calculate_chart_indicators')
  assert.deepEqual([...calls[0].args.indicators], ['ma', 'macd', 'atr'])
  assert.equal(calls[0].args.rows, rows)
  assert.equal(first.calculation_engine.wrapper_version, '0.8.2')
  await api.request(rows)
  assert.equal(calls.length, 1)
  await api.request(rows.map((row, index) => index === 1 ? { ...row, close: 99 } : row))
  assert.equal(calls.length, 2)
})

test('browser rejects failed, wrong-source or wrong-version calculations without legacy fallback', async () => {
  for (const failure of [
    (args: any) => ({ isError: true, structuredContent: { ok: false, error: 'offline' } }),
    (args: any) => ({ structuredContent: { ...accepted(args).structuredContent, source_hash: 'wrong' } }),
    (args: any) => ({ structuredContent: { ...accepted(args).structuredContent,
      calculation_engine: { wrapper_version: 'other' } } }),
  ]) {
    const { api } = fixture(async (_name, args) => failure(args))
    await assert.rejects(() => api.request(rows))
  }
  assert.ok(!html.includes('function localEmaTdx('))
  assert.ok(!html.includes('function buildLocalIndicatorCommands('))
})

test('a response arriving after the browser switches symbol cannot replace the new view', async () => {
  let resolve: (value: any) => void = () => {}
  const received: any[] = []
  const { api, state } = fixture(async (_name, args) => new Promise(done => { resolve = () => done(accepted(args)) }))
  state.handleToolResult = async (value: any) => { received.push(value) }
  const pending = api.render()
  await Promise.resolve()
  state.currentSymbol = 'OTHER.X'
  resolve(null)
  assert.equal(await pending, false)
  assert.equal(received.length, 0)
})
