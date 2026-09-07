import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

// Exercise the actual generator's scoped browser lifetime without a DOM or
// network. This code is emitted verbatim into generated-view.ts.
const generator = readFileSync(new URL('../scripts/generate-client-view.mjs', import.meta.url), 'utf8')
const start = generator.indexOf('function createScopedWindow(')
const end = generator.indexOf('\n}\n`', start) + 2
assert.ok(start >= 0 && end > start)

test('disposed chart scopes save preferences then stop listeners and future timers', () => {
  let timers = 0, saves = 0, removes = 0, clears = 0
  const realWindow = {
    addEventListener() {}, removeEventListener() { removes++ },
    setTimeout() { return ++timers }, setInterval() { return ++timers },
    clearTimeout() { clears++ }, clearInterval() { clears++ },
  }
  const factory = runInNewContext(`(${generator.slice(start, end)})`, {window: realWindow, Event})
  const scope = factory({clientHeight: 800}, {}, {})
  assert.equal(scope.window.__DSH_KLINE_DISPOSED__, false)
  scope.window.addEventListener('beforeunload', () => saves++)
  scope.window.addEventListener('resize', () => {})
  scope.window.setTimeout(() => {}, 1)
  scope.window.setInterval(() => {}, 1)
  scope.dispose()
  assert.equal(saves, 1)
  assert.equal(removes, 2)
  assert.equal(clears, 2)
  assert.equal(scope.window.__DSH_KLINE_DISPOSED__, true)
  assert.equal(scope.window.setTimeout(() => {}, 1), undefined)
  assert.equal(scope.window.setInterval(() => {}, 1), undefined)
  assert.equal(timers, 2)
})

test('late error rendering is harmless after chart DOM removal', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const showError = html.slice(html.indexOf('function showError(msg)'), html.indexOf('\nfunction dataFetchFailureDetail'))
  const render = runInNewContext(`(${showError})`, {document: {getElementById: () => null}, window: {}})
  assert.doesNotThrow(() => render('request aborted'))
})
