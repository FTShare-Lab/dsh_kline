import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('function initializeAnalysisWindow('), html.indexOf('async function init()'))
function fixture(restored = false) {
  const state: any = { window: { __DSH_KLINE_RESTORED__: restored }, currentRangeKey: 'ytd',
    customRangeStart: '', customRangeEnd: '', dateInputValue: (value: number) => String(value) }
  const initialize = runInNewContext(source + '; initializeAnalysisWindow', state)
  return { state, initialize }
}
const candles = { type: 'SET_CANDLES', rows: [{time:100}, {time:200}] }

test('fresh daily and larger analyses show their supplied window instead of a default preset', () => {
  for (const interval of ['day', 'week', 'month', 'quarter', 'year']) {
    const { state, initialize } = fixture()
    const payload: any = { interval, count: 20, chartCommands: [candles] }
    initialize(payload)
    assert.equal(payload.range_key, 'custom')
    assert.equal(state.currentRangeKey, 'custom')
    assert.equal(state.customRangeStart, '100')
    assert.equal(state.customRangeEnd, '200')
    assert.deepEqual(payload.chartCommands, [candles])
  }
})

test('restored views and explicit browser ranges are not overridden', () => {
  for (const [restored, range_key] of [[true, undefined], [false, '30d'], [true, 'custom']] as const) {
    const { state, initialize } = fixture(restored)
    const payload = { interval: 'day', range_key, chartCommands: [candles] }
    initialize(payload)
    assert.equal(payload.range_key, range_key)
    assert.equal(state.currentRangeKey, 'ytd')
  }
})

test('minute presentation, launchers, local redraws and invalid rows keep their current range', () => {
  for (const extra of [{interval:'minute'}, {workspace_mode:'launcher'}, {local_render:true},
    {chartCommands:[]}, {chartCommands:[{type:'SET_CANDLES',rows:[{time:NaN},{time:200}]}]}]) {
    const { state, initialize } = fixture()
    const payload: any = { interval:'day',chartCommands:[candles], ...extra }
    initialize(payload)
    assert.equal(payload.range_key, undefined)
    assert.equal(state.currentRangeKey, 'ytd')
  }
})

test('legacy annual YTD correction and drawing-only cache misses retain the exact snapshot window', () => {
  for (const extra of [{interval:'year',range_key:'ytd'}, {interval:'day',drawing_only:true}]) {
    const { initialize } = fixture(extra.interval === 'year')
    const payload: any = {...extra,chartCommands:[candles]}
    initialize(payload)
    assert.equal(payload.range_key,'custom')
  }
  assert.match(html,/initializeAnalysisWindow\(payload\);/)
})

test('window summary reports actual plotted rows and clears when no chart remains', () => {
  const row: any = {hidden:true,textContent:''}
  const meta: any = {title:''}
  const state: any = {document:{getElementById:(id:string)=>id==='chartMetaWindow'?row:meta},viewLanguage:'zh',
    currentCandles:[{time:100},{time:200}],fmtCandleTimestamp:(value:any)=>String(value.time)}
  const renderSource = html.slice(html.indexOf('function renderChartWindow('),html.indexOf('function renderChartMeta('))
  const render = runInNewContext(renderSource + '; renderChartWindow',state)
  render()
  assert.equal(row.textContent,'图表数据：2 根 · 100 — 200')
  assert.equal(row.hidden,true)
  assert.equal(meta.title,row.textContent)
  state.viewLanguage = 'en'; render()
  assert.equal(row.textContent,'Chart data: 2 bars · 100 — 200')
  assert.equal(meta.title,row.textContent)
  state.currentCandles = []; render()
  assert.equal(row.hidden,true)
  assert.equal(row.textContent,'')
  assert.equal(meta.title,'')
  assert.match(html,/renderChartMeta\(candle = currentCandles.at\(-1\)\) \{\s*renderChartWindow\(\);/)
})
