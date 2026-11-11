import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const zoomSource = html.slice(html.indexOf('function zoomChartViewport('), html.indexOf('function fitChartToData('))
const gutterSource = html.slice(html.indexOf('function syncRightAxisGutter('), html.indexOf('function refreshPercentAxis('))

test('price-axis width changes preserve the chart viewport', () => {
  const calls: string[] = []
  const style = { setProperty: (_name: string, value: string) => calls.push(`gutter:${value}`) }
  const wrap = { style }
  const state: any = {
    document: { getElementById: () => ({ parentElement: wrap }) },
    getComputedStyle: () => ({ getPropertyValue: () => '52' }),
    rightAxisGutterWidth: () => 65,
    currentCandles: [{}, {}],
    kchart: { setStyles: () => calls.push('styles'), resize: () => calls.push('resize') },
    chartStyles: () => ({}),
    window: { requestAnimationFrame: (callback: () => void) => callback() },
    scheduleChartOverlayRender: () => calls.push('overlay'),
    fitChartToData: () => assert.fail('axis label width must not reset the visible date range'),
  }
  runInNewContext(gutterSource + ';syncRightAxisGutter()', state)
  assert.deepEqual(calls, ['gutter:65px', 'styles', 'resize', 'overlay'])
})

test('viewport zoom changes bar spacing without changing candles or sequence drawing identity', () => {
  const rows = [1, 2, 3].map(time => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 1 }))
  const stick = { id: 'sticks_' + 'a'.repeat(24), bar_count: 3 }
  let barSpace = 8
  let overlayRenders = 0
  const focused: Array<{times: number[], adjustZoom: boolean}> = []
  const state: any = {
    currentCandles: rows,
    currentSymbol: 'TEST.X', currentInterval: 'day', lastFocusedDrawing: null,
    document: {getElementById: () => ({clientWidth: 400})}, MIN_CHART_RENDER_WIDTH: 100,
    lastAgentPriceSticks: [stick],
    activeAutoPreviewTimes: () => [1, 3],
    focusAutoPreview: (times: number[], options: {adjustZoom: boolean}) => { focused.push({times, adjustZoom: options.adjustZoom}); return true },
    scheduleChartOverlayRender: () => { overlayRenders++ },
    kchart: {
      getBarSpace: () => barSpace,
      getVisibleRange: () => ({from: 0, to: 2}),
      setBarSpace: (value: number) => { barSpace = value },
      applyNewData: () => assert.fail('viewport zoom must not reload candles'),
    },
  }
  const zoom = runInNewContext(zoomSource + ';zoomChartViewport', state)
  assert.equal(zoom(1), true)
  assert.equal(barSpace, 12)
  assert.equal(zoom(-1), true)
  assert.equal(barSpace, 8)
  assert.equal(overlayRenders, 2)
  assert.deepEqual(focused, [{times: [1, 3], adjustZoom: false}, {times: [1, 3], adjustZoom: false}])
  assert.equal(state.currentCandles, rows)
  assert.equal(state.lastAgentPriceSticks[0], stick)
  assert.match(html, /id="chartZoomInBtn"/)
  assert.match(html, /id="chartZoomOutBtn"/)
  assert.match(html, /chartZoomInBtn"\)\.addEventListener\("click", \(\) => zoomChartViewport\(1\)\)/)
})

test('viewport zoom rejects missing chart and stops at bounded bar widths', () => {
  let barSpace = 50
  const state: any = {
    currentCandles: [{}, {}],
    currentSymbol: 'TEST.X', currentInterval: 'day', lastFocusedDrawing: null,
    activeAutoPreviewTimes: () => null,
    kchart: { getBarSpace: () => barSpace, setBarSpace: (value: number) => { barSpace = value } },
    scheduleChartOverlayRender: () => {},
  }
  const zoom = runInNewContext(zoomSource + ';zoomChartViewport', state)
  assert.equal(zoom(1), false)
  assert.equal(barSpace, 50)
  assert.equal(zoom(-1), true)
  assert.equal(barSpace, 33)
  state.kchart = null
  assert.equal(zoom(1), false)
})

test('viewport zoom keeps the previously visible date centered without an active drawing', () => {
  const rows = [1, 2, 3, 4, 5].map(time => ({time}))
  const calls: string[] = []
  let barSpace = 8
  const state: any = {
    currentCandles: rows,
    currentSymbol: 'TEST.X', currentInterval: 'day', lastFocusedDrawing: null,
    activeAutoPreviewTimes: () => null,
    focusAutoPreview: (times: number[], options: {adjustZoom: boolean}) => calls.push(`${times[0]}:${options.adjustZoom}`),
    kchart: {
      getBarSpace: () => barSpace,
      getVisibleRange: () => ({from: 1, to: 3}),
      setBarSpace: (value: number) => { barSpace = value },
    },
    scheduleChartOverlayRender: () => {},
  }
  const zoom = runInNewContext(zoomSource + ';zoomChartViewport', state)
  assert.equal(zoom(1), true)
  assert.equal(barSpace, 12)
  assert.deepEqual(calls, ['3:false'])
})

test('active drawing zoom stops before its anchors leave the viewport', () => {
  const rows = Array.from({length: 40}, (_, index) => ({time: index + 1}))
  let barSpace = 20
  const calls: string[] = []
  const state: any = {
    currentCandles: rows,
    currentSymbol: 'TEST.X', currentInterval: 'day',
    lastFocusedDrawing: {symbol: 'TEST.X', interval: 'day', times: [10, 30]},
    activeAutoPreviewTimes: () => null,
    focusAutoPreview: (times: number[]) => calls.push(times.join(',')),
    document: {getElementById: () => ({clientWidth: 700})}, MIN_CHART_RENDER_WIDTH: 100,
    kchart: {getBarSpace: () => barSpace, getVisibleRange: () => ({from: 5, to: 35}),
      setBarSpace: (value: number) => {barSpace = value}},
    scheduleChartOverlayRender: () => {},
  }
  const zoom = runInNewContext(zoomSource + ';zoomChartViewport', state)
  assert.equal(zoom(1), false)
  assert.equal(barSpace, 20)
  assert.deepEqual(calls, [])
  barSpace = 12
  assert.equal(zoom(1), true)
  assert.equal(barSpace, 18)
  assert.deepEqual(calls, ['10,30'])
})
