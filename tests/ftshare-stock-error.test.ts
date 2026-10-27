import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('function dataFetchFailureDetail('), html.indexOf('function clearDataFetchError('))
const copy: Record<string, string> = {
  noKeyStockData: 'Configure a free FTShare key for stock candles',
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
})

test('opening a stock preserves backend error context and does not prefetch minute bars', () => {
  const openSymbol = html.slice(html.indexOf('async function openSymbol('), html.indexOf('async function ', html.indexOf('async function openSymbol(') + 1))
  assert.match(openSymbol, /ftshare_key_configured: fetched\.ftshare_key_configured/)
  assert.doesNotMatch(openSymbol, /prefetchCandleData\(candleFetchArgs\(nextSymbol, \{ rangeKey: "5d" \}\)\)/)
  assert.doesNotMatch(html, /scheduleSymbolPrefetch\(results, q\);/)
  assert.doesNotMatch(html, /scheduleCommonIndexPrefetch\(\);/)
})
