import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('function marketDataSourcePresentation('), html.indexOf('function marketDataSourceMarkup('))

test('BaoStock daily history is attributed to its own source in both languages', () => {
  for (const [language, label] of [['zh', 'BaoStock 免费历史行情'], ['en', 'BaoStock free history']] as const) {
    const present: any = runInNewContext(source + '; marketDataSourcePresentation', {
      viewLanguage: language,
      t: (key: string) => key,
      safeSourceUrl: (url: string) => url,
      FTSHARE_SDK_URL: '', FTSHARE_MCP_URL: '',
    })
    const result = present('baostock_free')
    assert.equal(result.label, label)
    assert.equal(result.url, 'https://www.baostock.com/')
  }
})
