import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('function dataFetchFailureDetail('), html.indexOf('function clearDataFetchError('))
const copy: Record<string, string> = {
  noKeyStockData: 'Configure a free FTShare key for stock candles',
  freeStockUnavailable: 'BaoStock did not return candles. Retry later.',
  ftshareMinuteKeyRequired: 'Minute bars require a key.',
  ftshareProbeRateLimited: 'Too many requests. Try again later.',
  ftshareProbePlanLimited: 'Not included in this plan.',
  ftshareProbeAuthRequired: 'Configure a valid key.',
}
const detail: any = runInNewContext(source + '; dataFetchFailureDetail', {
  t: (key: string) => copy[key] || key,
  viewLanguage: 'en',
  isIntradayRange: () => false,
})

test('chart errors distinguish no key, configured rate limit and plan limits', () => {
  assert.equal(detail({ code: 'rate_limited', ftshare_key_configured: false }), copy.noKeyStockData)
  assert.equal(detail({ code: 'rate_limited', ftshare_key_configured: true }), copy.ftshareProbeRateLimited)
  assert.equal(detail({ code: 'capability_limited', ftshare_key_configured: true }), copy.ftshareProbePlanLimited)
  assert.equal(detail({ code: 'free_stock_unavailable', ftshare_key_configured: false }), copy.freeStockUnavailable)
  const minuteDetail: any = runInNewContext(source + '; dataFetchFailureDetail', {
    t: (key: string) => copy[key] || key,
    viewLanguage: 'en',
    isIntradayRange: () => true,
  })
  assert.equal(minuteDetail({ code: 'auth_required', ftshare_key_configured: false }), copy.ftshareMinuteKeyRequired)
})

test('market tool preserves no-key context from the service for chart errors', async () => {
  const toolSource = html.slice(html.indexOf('function sleep('), html.indexOf('/* ---------- state ---------- */'))
  const callMarketTool: any = runInNewContext(toolSource + '; callMarketTool', {
    callTool: async () => ({ structuredContent: {
      ok: false, error: 'rate_limited', error_code: 'rate_limited',
      message: 'FTShare rate limit', ftshare_key_configured: false,
    } }),
    window: { setTimeout },
  })
  await assert.rejects(callMarketTool('fetch_candles', { symbol: '600519.XSHG' }), (error: any) => {
    assert.equal(error.code, 'rate_limited')
    assert.equal(error.ftshare_key_configured, false)
    assert.equal(detail(error), copy.noKeyStockData)
    return true
  })
})

test('opening a stock preserves backend error context and does not prefetch minute bars', () => {
  const openSymbol = html.slice(html.indexOf('async function openSymbol('), html.indexOf('async function ', html.indexOf('async function openSymbol(') + 1))
  assert.match(openSymbol, /ftshare_key_configured: fetched\.ftshare_key_configured/)
  assert.doesNotMatch(openSymbol, /prefetchCandleData\(candleFetchArgs\(nextSymbol, \{ rangeKey: "5d" \}\)\)/)
  assert.doesNotMatch(html, /scheduleSymbolPrefetch\(results, q\);/)
  assert.doesNotMatch(html, /scheduleCommonIndexPrefetch\(\);/)
})
