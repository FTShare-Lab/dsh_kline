import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const start = html.indexOf('function selectionBannerMarkup(')
const end = html.indexOf('\nfunction updateSelectionBanner', start)
assert.ok(start >= 0 && end > start)
const rangeStatsStart = html.indexOf('function renderRangeStatsCard(')
const rangeStatsEnd = html.indexOf('\nfunction renderTables', rangeStatsStart)
assert.ok(rangeStatsStart >= 0 && rangeStatsEnd > rangeStatsStart)
const rangePositionStart = html.indexOf('function chartPointForCandle(')
const rangePositionEnd = html.indexOf('\nfunction renderIntradaySessionGuides', rangePositionStart)
assert.ok(rangePositionStart >= 0 && rangePositionEnd > rangePositionStart)

test('candle selection banner presents aligned market fields as a vertical definition list', () => {
  const markup = runInNewContext(`(${html.slice(start, end)})`, {
    currentName: '沪深300ETF', currentSymbol: '510300.XSHG', currentInterval: 'day', sourceCandleInterval: 'day',
    t: (key: string) => key === 'day' ? '日线' : key,
    fmtCandleTimestamp: () => '2026-09-15', fmt: (value: number) => value.toFixed(2),
    fmtVolumeWan: () => '69,734万', escapeHtml: (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
  })({kind: 'candle', candle: {index: 245, open: 4.54, high: 4.57, low: 4.51, close: 4.52, volume: 697340000}})
  assert.match(markup, /<dl class="selection-candle-values">/)
  assert.match(markup, /<div class="selection-candle-value"><dt>时间<\/dt><dd>2026-09-15<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>开盘<\/dt><dd>4\.54<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>收盘<\/dt><dd>4\.52<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>最高<\/dt><dd>4\.57<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>最低<\/dt><dd>4\.51<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>涨幅<\/dt><dd>--<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>成交量<\/dt><dd>69,734万<\/dd><\/div>/)
  assert.match(markup, /<div class="selection-candle-value"><dt>成交额<\/dt><dd>--<\/dd><\/div>/)
})

test('selection banner escapes a quoted security name before rendering', () => {
  const markup = runInNewContext(`(${html.slice(start, end)})`, {
    currentName: '<img>', currentSymbol: 'TEST.US', currentInterval: 'day', sourceCandleInterval: 'day',
    t: (key: string) => key, fmtCandleTimestamp: () => '2026-09-15', fmt: () => '1.00', fmtVolumeWan: () => '1万',
    escapeHtml: (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
  })({kind: 'candle', candle: {index: 0, open: 1, high: 1, low: 1, close: 1, volume: 1}})
  assert.match(markup, /&lt;img>/)
  assert.doesNotMatch(markup, /<img>/)
})

test('range selection uses a compact one-line summary instead of candle metrics', () => {
  const markup = runInNewContext(`(${html.slice(start, end)})`, {
    currentName: '招商银行', currentSymbol: '600036.XSHG', currentInterval: 'year', sourceCandleInterval: 'day',
    t: (key: string) => key, fmtCandleTimestamp: (value: number) => value === 1 ? '2020-12-31' : '2022-12-30',
    escapeHtml: (value: string) => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
  })({kind: 'range', range: {start_time: 1, end_time: 2, bars: 3}})
  assert.match(markup, /selection-range-copy/)
  assert.match(markup, /招商银行.*2020-12-31 → 2022-12-30 · 3 根 K 线/)
  assert.doesNotMatch(markup, /selection-candle-values/)
})

test('range statistics render into the chart card with compact formatted details', () => {
  const card = { hidden: true, innerHTML: '' }
  const renderRangeStatsCard = runInNewContext(`(${html.slice(rangeStatsStart, rangeStatsEnd)})`, {
    document: { getElementById: () => card },
    currentName: '上证指数', currentSymbol: '000001.XSHG', currentInterval: 'day', sourceCandleInterval: 'day',
    viewLanguage: 'zh', t: (key: string) => key === 'day' ? '日线' : key,
    rt: (key: string) => ({ statistics: '区间统计', startTime: '开始时间', endTime: '结束时间', volume: '成交量', return: '区间涨跌', amplitude: '振幅', drawdown: '最大回撤', bars: 'K线数', averageVolume: '均量' }[key] || key),
    fmt: (value: number) => value.toFixed(2),
    fmtVolumeWan: () => '5,425,243万',
    fmtCandleTimestamp: (value: number) => value === 1 ? '2026-08-05' : '2026-08-17',
    positionRangeStatsCard: () => {},
    escapeHtml: (value: string) => value,
  })
  renderRangeStatsCard({
    return_pct: 4.2, amplitude_pct: 8.1, max_drawdown: { max_drawdown_pct: -2.3 },
    bars: 8, duration_days: 11, up_bars: 5, down_bars: 3,
    open: 10.2, close: 10.63, high: 10.9, low: 10.1,
    start_time: 1, end_time: 2, max_up_streak: 3, max_down_streak: 2, total_volume: 54252430000, avg_volume: 54252430000,
  })

  assert.equal(card.hidden, false)
  assert.match(card.innerHTML, /上证指数/)
  assert.match(card.innerHTML, /日线 · 区间统计/)
  assert.match(card.innerHTML, /开始时间[\s\S]*2026-08-05/)
  assert.match(card.innerHTML, /结束时间[\s\S]*2026-08-17/)
  assert.match(card.innerHTML, /区间涨跌[\s\S]*\+4\.20%/)
  assert.match(card.innerHTML, /最大回撤[\s\S]*-2\.30%/)
  assert.match(card.innerHTML, /成交量[\s\S]*5,425,243万/)
  assert.match(card.innerHTML, /range-stats-dismiss/)
  assert.doesNotMatch(card.innerHTML, /开盘|收盘|最高|最低|日历天|连涨/)
})

test('range statistics card follows the selected range and stays inside the chart', () => {
  const card = { hidden: false, offsetWidth: 220, offsetHeight: 150, style: {} as Record<string, string> }
  const wrap = { clientWidth: 800, clientHeight: 500 }
  const positionRangeStatsCard = runInNewContext(`${html.slice(rangePositionStart, rangePositionEnd)}\npositionRangeStatsCard`, {
    document: {
      getElementById: () => card,
      querySelector: () => wrap,
    },
    kchart: {
      convertToPixel: (points: Array<{ timestamp: number }>) => points.map(({ timestamp }) => (
        timestamp === 1000 ? { x: 270, y: 400 } : { x: 530, y: 380 }
      )),
    },
    rangePickStart: { candle: { time: 1, close: 10 } },
    rangePickEnd: { candle: { time: 2, close: 11 } },
    Math,
  })

  positionRangeStatsCard()
  assert.equal(card.style.left, '290px')
  assert.equal(card.style.top, '218px')
  assert.equal(card.style.transform, 'none')
})
