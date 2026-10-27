import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const zoomSource = html.slice(html.indexOf('function zoomChartViewport('), html.indexOf('function fitChartToData('))

test('viewport zoom changes bar spacing without changing candles or sequence drawing identity', () => {
  const rows = [1, 2, 3].map(time => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 1 }))
  const stick = { id: 'sticks_' + 'a'.repeat(24), bar_count: 3 }
  let barSpace = 8
  let overlayRenders = 0
  const state: any = {
    currentCandles: rows,
    lastAgentPriceSticks: [stick],
    scheduleChartOverlayRender: () => { overlayRenders++ },
    kchart: {
      getBarSpace: () => barSpace,
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
