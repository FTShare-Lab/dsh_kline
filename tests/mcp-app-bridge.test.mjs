import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

const bridge = readFileSync(new URL('../adapters/mcp-app-bridge.js', import.meta.url), 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))

function harness() {
  const posted = [], events = {}, attrs = {}, classes = new Set(), timers = new Map(), rendered = []
  let sequence = 0
  const button = { disabled: false, title: '', textContent: '',
    setAttribute: (name, value) => { attrs[name] = value },
    classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name) } },
  }
  const on = (name, fn) => { (events[name] ||= []).push(fn) }
  const parent = { postMessage(message) { posted.push(message) } }
  const window = { parent, addEventListener: on,
    fetch: () => { throw new Error('No DSH HTTP request permitted') },
    handleToolResult: async result => { rendered.push(result) },
  }
  const document = { readyState: 'loading', documentElement: { dataset: {}, lang: 'zh', scrollHeight: 640 },
    createElement: () => ({ dataset: {}, lang: '' }),
    addEventListener: on, getElementById: () => button,
  }
  vm.runInNewContext(bridge, { window, document, console, Response,
    setTimeout(fn) { timers.set(++sequence, fn); return sequence },
    clearTimeout(id) { timers.delete(id) },
  })
  const emit = (message, source = parent) => events.message.forEach(fn => fn({ source, data: { jsonrpc: '2.0', ...message } }))
  const reply = (request, result) => emit({ id: request.id, result })
  const click = () => events.click[0]({ target: { closest: () => button } })
  const initialize = async (modes = ['inline', 'fullscreen']) => {
    events.DOMContentLoaded[0]()
    assert.equal(posted.at(-1).method, 'ui/initialize')
    reply(posted.at(-1), { hostContext: { displayMode: 'inline', availableDisplayModes: modes } })
    await flush()
  }
  return { window, document, button, attrs, classes, posted, emit, reply, click, initialize, timers, rendered }
}

test('waits for host initialization and actual tool payload before mounting the shared view', async () => {
  const h = harness()
  let ready = false
  h.window.__DSH_KLINE_MCP_APPS__.ready.then(() => { ready = true })
  await h.initialize()
  assert.equal(ready, false)
  h.emit({ method: 'ui/notifications/tool-result', params: { structuredContent: { chartCommands: [], symbol: 'X' } } })
  await flush()
  assert.equal(ready, true)
  assert.equal(h.window.__DSH_CHART_SESSION__.symbol, 'X')
  await h.window.__DSH_KLINE_MCP_APPS__.mounted()
  h.emit({ method: 'ui/notifications/tool-result', params: { structuredContent: { chartCommands: [], symbol: 'Y' } } })
  assert.equal(h.rendered[0].structuredContent.symbol, 'Y')
})

test('icon toggles fullscreen and inline using standard MCP Apps mode results', async () => {
  const h = harness()
  await h.initialize()
  const first = h.click()
  assert.equal(h.posted.at(-1).method, 'ui/request-display-mode')
  assert.equal(h.posted.at(-1).params.mode, 'fullscreen')
  h.reply(h.posted.at(-1), { mode: 'fullscreen' })
  await first
  assert.equal(h.attrs['aria-expanded'], 'true')
  assert.ok(h.classes.has('active'))
  assert.equal(h.button.textContent, '')
  const second = h.click()
  assert.equal(h.posted.at(-1).params.mode, 'inline')
  h.reply(h.posted.at(-1), { mode: 'inline' })
  await second
  assert.equal(h.attrs['aria-expanded'], 'false')
})

test('host preferences update independently of chart-local overrides', async () => {
  const h = harness()
  await h.initialize()
  const host = h.window.__DSH_KLINE_MCP_APPS__.hostElement
  h.emit({ method: 'ui/notifications/host-context-changed', params: { theme: 'dark', locale: 'zh-CN' } })
  assert.equal(host.dataset.theme, 'dark')
  assert.equal(host.lang, 'zh-CN')
  h.document.documentElement.dataset.theme = 'light'
  assert.equal(host.dataset.theme, 'dark')
  h.emit({ method: 'ui/notifications/host-context-changed', params: { theme: 'light', locale: 'en-US' } })
  assert.equal(host.dataset.theme, 'light')
  assert.equal(host.lang, 'en-US')
})

test('unsupported host disables expand without breaking chart actions', async () => {
  const h = harness()
  await h.initialize(['inline'])
  assert.equal(h.button.disabled, true)
  const requested = h.window.fetch('/dsh-kline/api/tools/market_ticker', { body: '{"symbols":["000001.XSHG"]}' })
  await flush()
  const request = h.posted.at(-1)
  assert.equal(request.method, 'tools/call')
  assert.equal(request.params.name, 'chart_action')
  assert.equal(request.params.arguments.action, 'market_ticker')
  h.reply(request, { structuredContent: { ok: true, items: [] } })
  const response = await requested
  assert.equal(response.status, 200)
  assert.equal((await response.json()).structuredContent.ok, true)
})

test('foreign window messages cannot resolve calls or replace chart payloads', async () => {
  const h = harness()
  await h.initialize()
  const requested = h.window.__DSH_KLINE_MCP_APPS__.callTool('calc_range', {})
  await flush()
  const request = h.posted.at(-1)
  h.emit({ id: request.id, result: { forged: true } }, {})
  h.emit({ method: 'ui/notifications/tool-result', params: { chartCommands: [], forged: true } }, {})
  assert.equal(h.window.__DSH_CHART_SESSION__, undefined)
  h.reply(request, { ok: true })
  assert.equal((await requested).forged, undefined)
})

test('request rejection does not falsely mark the icon expanded; native path also toggles', async () => {
  const h = harness()
  await h.initialize()
  const failed = h.click()
  h.emit({ id: h.posted.at(-1).id, error: { message: 'Host denied expansion' } })
  await failed
  assert.equal(h.attrs['aria-expanded'], 'false')
  assert.match(h.button.title, /denied/)
  h.window.openai = { requestDisplayMode: async ({ mode }) => ({ mode }) }
  await h.click()
  assert.equal(h.attrs['aria-expanded'], 'true')
})

test('tool requests time out and teardown clears pending calls', async () => {
  const h = harness()
  await h.initialize()
  const timedOut = h.window.__DSH_KLINE_MCP_APPS__.callTool('market_ticker', {})
  await flush()
  const rejection = assert.rejects(timedOut, /timed out/)
  Array.from(h.timers.values()).at(-1)()
  await rejection
  const pending = h.window.__DSH_KLINE_MCP_APPS__.callTool('search_symbols', {})
  await flush()
  const closed = assert.rejects(pending, /App closed/)
  h.emit({ id: 'close', method: 'ui/resource-teardown' })
  await closed
  assert.equal(h.window.__DSH_KLINE_DISPOSED__, true)
})
