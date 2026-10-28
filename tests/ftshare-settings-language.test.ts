import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('function ftshareResultMessage('), html.indexOf('function ftshareConfigErrorMessage('))

function message(data: unknown, language: 'zh' | 'en') {
  const copy: Record<string, Record<string, string>> = {
    zh: { ftshareProbeBoth: '日 K 和分钟 K 均可用。', ftshareProbeDailyPlan: '日 K 可用；当前套餐未开通分钟 K。', ftshareNoKeyConnection: 'FTShare 未配置 Key；沪深 A 股历史日 K 可尝试 BaoStock。' },
    en: { ftshareProbeBoth: 'Daily and minute bars are available.', ftshareProbeDailyPlan: 'Daily bars are available; minute bars are not included in the current plan.', ftshareProbeInvalidKey: 'API key validation failed. Check the key and try again.', ftshareProbeAuthRequired: 'Configure a valid API key and try again.', ftshareConfiguredSaved: 'Configured and saved; it will be reused after restart', ftshareNoKeyConnection: 'No FTShare key is configured; historical daily A-share bars can use BaoStock.' },
  }
  const context: any = { viewLanguage: language, t: (key: string) => copy[language][key] || key }
  const render: any = runInNewContext(source + '; ftshareResultMessage', context)
  return render(data)
}

test('FTShare connection results use structured capabilities, not the backend Chinese message', () => {
  const result = { ok: true, message: 'FTShare API Key 已保存并验证通过，当前日 K 与分钟 K 均可用。', capabilities: { daily: 'available', minute: 'available' } }
  assert.equal(message(result, 'en'), 'Daily and minute bars are available.')
  assert.equal(message(result, 'zh'), '日 K 和分钟 K 均可用。')
  assert.equal(message({ ...result, capabilities: { daily: 'available', minute: 'insufficient_quota' } }, 'en'), 'Daily bars are available; minute bars are not included in the current plan.')
  assert.equal(message({ ok: true, persistent: true, message: '配置已保存' }, 'en'), 'Configured and saved; it will be reused after restart')
})

test('English FTShare errors use error codes instead of exposing backend Chinese text', () => {
  const result = { ok: false, error: 'invalid_key', message: 'FTShare API Key 校验失败' }
  assert.equal(message(result, 'en'), 'API key validation failed. Check the key and try again.')
  assert.equal(message(result, 'zh'), result.message)
  assert.equal(message({ ok: false, error: 'auth_required', message: '未携带 API Key' }, 'en'), 'Configure a valid API key and try again.')
  assert.match(html, /if \(ftshareTestResultForLocale\) setFtshareTestStatus\(ftshareResultMessage\(ftshareTestResultForLocale\)/)
})

test('an unconfigured FTShare connection describes the separate BaoStock fallback', () => {
  const result = { ok: false, configured: false, error: 'rate_limited', message: 'FTShare 请求过于频繁' }
  assert.equal(message(result, 'en'), 'No FTShare key is configured; historical daily A-share bars can use BaoStock.')
  assert.equal(message(result, 'zh'), 'FTShare 未配置 Key；沪深 A 股历史日 K 可尝试 BaoStock。')
  assert.match(html, /ftshareStatusAnonymous: "未配置 API Key"/)
  assert.match(html, /ftshareHintAnonymous: "沪深 A 股历史日 K 可尝试 BaoStock/)
})
