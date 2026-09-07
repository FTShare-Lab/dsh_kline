import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const start = html.indexOf('function restoreCanvasHeight(')
const end = html.indexOf('function chartBaseHeight()', start)
const { restoreCanvasHeight, autoChartBaseHeight } = runInNewContext(
  `${html.slice(start, end)}; ({restoreCanvasHeight, autoChartBaseHeight})`,
  { CANVAS_BASE_MIN_HEIGHT: 280, CANVAS_BASE_MAX_HEIGHT: 1280 },
)

test('automatic height survives absent, null or invalid saved settings', () => {
  for (const value of [null, undefined, '', '560', NaN, Infinity, false]) {
    assert.equal(restoreCanvasHeight(value), null)
  }
})
test('genuine manual heights remain bounded and restorable', () => {
  assert.equal(restoreCanvasHeight(600), 600)
  assert.equal(restoreCanvasHeight(20), 280)
  assert.equal(restoreCanvasHeight(2000), 1280)
})
test('automatic main chart consumes remaining space without the old tall-window cap', () => {
  assert.equal(autoChartBaseHeight(1414, 349, 304), 761)
  assert.equal(autoChartBaseHeight(2414, 349, 304), 1761)
  assert.equal(autoChartBaseHeight(1414, 349, 0), 1065)
})
test('small windows or many indicators retain a readable minimum and permit scrolling', () => {
  assert.equal(autoChartBaseHeight(514, 349, 304), 280)
  assert.equal(autoChartBaseHeight(1000, 349, 704), 280)
})
