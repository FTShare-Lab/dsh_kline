import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const start = html.indexOf('const comparisonDateFormatters = new Map();')
const end = html.indexOf('function renderComparisonLegend(', start)
assert.ok(start >= 0 && end > start)
const context = { exchangeTimezone: 'Asia/Shanghai', isIntradayRange: () => false }
vm.runInNewContext(`${html.slice(start, end)}\nglobalThis.aligned = comparisonAlignedRows; globalThis.sharedBase = comparisonSharedBase; globalThis.zoneFor = comparisonTimezone;`, context)

const at = (iso) => Date.parse(iso) / 1000
const candle = (iso, close) => ({ time: at(iso), close })
const plain = (value) => JSON.parse(JSON.stringify(value))

test('daily comparison carries the last close across a short market closure', () => {
  const primary = [candle('2026-11-09T07:00:00Z', 100), candle('2026-11-10T07:00:00Z', 102), candle('2026-11-11T07:00:00Z', 101)]
  const series = { symbol: '000300.XSHG', exchange_timezone: 'Asia/Shanghai', rows: [candle('2026-11-09T07:00:00Z', 4000), candle('2026-11-11T07:00:00Z', 4100)] }
  const aligned = context.aligned(primary, series, 'Asia/Shanghai', false)
  assert.deepEqual(plain(aligned.map((point) => point?.value ?? null)), [100, 100, 102.5])
  assert.equal(aligned[1].sourceKey, '2026-11-09')
})

test('cross-market daily sessions align by local trading date', () => {
  const primary = [candle('2026-11-09T07:00:00Z', 100), candle('2026-11-10T07:00:00Z', 102)]
  const series = { symbol: 'SPY.US', exchange_timezone: 'America/New_York', rows: [candle('2026-11-09T21:00:00Z', 500), candle('2026-11-10T21:00:00Z', 525)] }
  assert.deepEqual(plain(context.aligned(primary, series, 'Asia/Shanghai', false).map((point) => point?.value ?? null)), [100, 105])
})

test('minute comparison requires the same timestamp', () => {
  context.isIntradayRange = () => true
  const primary = [candle('2026-11-09T01:30:00Z', 100), candle('2026-11-09T01:31:00Z', 101), candle('2026-11-09T01:32:00Z', 102)]
  const series = { symbol: '000300.XSHG', rows: [candle('2026-11-09T01:30:00Z', 4000), candle('2026-11-09T01:32:00Z', 4040)] }
  assert.deepEqual(plain(context.aligned(primary, series, 'Asia/Shanghai', true).map((point) => point?.value ?? null)), [100, null, 101])
})

test('US index aliases use New York trading dates without metadata', () => {
  assert.equal(context.zoneFor({ symbol: '100.DJIA' }), 'America/New_York')
  assert.equal(context.zoneFor({ symbol: '100.NDX' }), 'America/New_York')
})

test('multiple comparison lines use one shared zero-return date', () => {
  context.isIntradayRange = () => false
  const primary = [candle('2026-11-09T07:00:00Z', 100), candle('2026-11-10T07:00:00Z', 105), candle('2026-11-11T07:00:00Z', 110)]
  const first = { symbol: '000300.XSHG', rows: [candle('2026-11-09T07:00:00Z', 4000), candle('2026-11-10T07:00:00Z', 4100), candle('2026-11-11T07:00:00Z', 4200)] }
  const later = { symbol: '100.NDX', exchange_timezone: 'America/New_York', rows: [candle('2026-11-10T21:00:00Z', 20000), candle('2026-11-11T21:00:00Z', 21000)] }
  const base = context.sharedBase(primary, [first, later], 'Asia/Shanghai', false)
  assert.equal(base.time, primary[1].time)
  assert.deepEqual(plain(context.aligned(primary, first, 'Asia/Shanghai', false, base).map((point) => point?.value ?? null)), [105 * 4000 / 4100, 105, 105 * 4200 / 4100])
  assert.deepEqual(plain(context.aligned(primary, later, 'Asia/Shanghai', false, base).map((point) => point?.value ?? null)), [null, 105, 110.25])
})

test('comparison does not extend an old quote beyond five missing daily bars', () => {
  const primary = Array.from({ length: 8 }, (_, index) => candle(`2026-11-${String(index + 9).padStart(2, '0')}T07:00:00Z`, 100 + index))
  const series = { symbol: '100.NDX', exchange_timezone: 'America/New_York', rows: [candle('2026-11-09T21:00:00Z', 20000)] }
  assert.deepEqual(plain(context.aligned(primary, series, 'Asia/Shanghai', false).map((point) => point?.value ?? null)), [100, 100, 100, 100, 100, 100, null, null])
})
