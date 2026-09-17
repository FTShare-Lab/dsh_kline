import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')

test('settings default theme and language to following the host', () => {
  assert.match(html, /id="themeToggle"[\s\S]*?<option value="host"/)
  assert.match(html, /id="languageToggle"[\s\S]*?<option value="host"/)
  assert.match(html, /version: 12/)
  assert.match(html, /language: languagePreference/)
  assert.match(html, /theme: userThemeOverride \|\| "host"/)
  assert.match(html, /function hostLanguage\(\)/)
  assert.match(html, /function hostTheme\(\)/)
  assert.match(html, /observeHostPreferences\(\)/)
})

test('FTShare setup explains automatic credential sources without rendering secrets', () => {
  assert.match(html, /id="ftshareAdapterHint"/)
  assert.match(html, /credentialSource = provider\.credential_source/)
  assert.match(html, /ftshareStatusEnvironment/)
  assert.match(html, /ftshareStatusExternalFile/)
  assert.match(html, /ftshareHintEnvironment/)
  assert.match(html, /clearButton\.disabled = !canClear/)
  assert.doesNotMatch(html, /ftshareApiKeyInput\.value\s*=/)
})
