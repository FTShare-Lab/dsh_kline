import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')

test('normal chart source and its distinct update time live in settings, not a permanent chart row', () => {
  const status = { hidden: false, textContent: '', innerHTML: '' }
  const settings = { innerHTML: '' }
  const title = { textContent: '' }
  const context: any = {
    document: { getElementById: (id: string) => ({ marketDataStatus: status, settingsSourceStatus: settings, settingsCurrentChartTitle: title })[id] },
    viewLanguage: 'zh', chartDataStatus: 'closed', chartDataStale: false, chartDataRangeFallback: '',
    chartDataSource: 'ftshare', chartDataSourceUrl: '', chartDataUpdatedAt: 123, currentSymbol: 'TEST.X',
    marketDataSourceMarkup: () => '<a>FTShare</a>', formatTickerUpdatedAt: () => '17:49',
    escapeHtml: (value: string) => value, t: (key: string) => ({ sourceConnected: '已连接', marketUpdated: '更新', beijingTime: '北京时间', retrying: '刷新失败' } as any)[key] || key,
  }
  const settingsSource = html.slice(html.indexOf('function renderSettingsSource('), html.indexOf('function setFtshareConfigStatus('))
  const statusSource = html.slice(html.indexOf('function renderMarketDataStatus('), html.indexOf('function scheduleChartDataRetry('))
  const api: any = runInNewContext(settingsSource + statusSource + ';({ renderMarketDataStatus })', context)
  api.renderMarketDataStatus()
  assert.equal(status.hidden, true)
  assert.equal(status.textContent, '')
  assert.match(settings.innerHTML, /FTShare<\/a> · 已连接 · 更新 北京时间 17:49/)
  assert.equal(title.textContent, '当前图数据')
  context.chartDataStale = true
  api.renderMarketDataStatus()
  assert.equal(status.hidden, false)
  assert.equal(status.textContent, '刷新失败')
})

test('footer identifies the index quote time and owns the single refresh action', () => {
  const track: any = { innerHTML: '', classList: { toggle() {} }, scrollWidth: 0 }
  const meta: any = { innerHTML: '', clientWidth: 100 }
  const bar: any = { clientWidth: 800, classList: { add() {}, remove() {} } }
  const shell: any = { classList: { add() {} } }
  const context: any = {
    document: { getElementById: (id: string) => ({ marketTickerTrack: track, marketTickerMeta: meta, marketTicker: bar, viewShell: shell })[id] },
    marketTickerItems: [{ symbol: '000001.XSHG', name: '上证指数', market: 'CN', close: 3658, change_pct: -1.5 }],
    marketTickerUpdatedAt: 456, marketTickerStatus: 'closed', marketTickerStale: false, chartDataRefreshInFlight: false,
    t: (key: string) => ({ marketIndices: '主要指数', marketUpdated: '更新', beijingTime: '北京时间', refresh: '刷新', closed: '收盘', openIndexChart: '查看 {name} K 线图' } as any)[key] || key,
    escapeHtml: (value: string) => value, formatTickerUpdatedAt: () => '18:36', formatTickerNumber: (value: number) => String(value),
    tickerStatusLabel: () => '收盘', reportSize() {}, window: { requestAnimationFrame(callback: () => void) { callback() } },
  }
  const source = html.slice(html.indexOf('function marketRefreshButtonMarkup('), html.indexOf('async function loadMarketTicker('))
  const render: any = runInNewContext(source + '; renderMarketTicker', context)
  render()
  assert.match(meta.innerHTML, /主要指数 · 18:36/)
  assert.match(meta.innerHTML, /id="refreshMarketDataBtn"/)
  assert.doesNotMatch(meta.innerHTML, /FTShare|支持接入其他数据源/)
  assert.equal((html.match(/id=\\?"refreshMarketDataBtn\\?"/g) || []).length, 1, 'refresh button is rendered only in the footer')
})
