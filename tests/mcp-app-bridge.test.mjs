import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'

import { PROJECT_ROOT, testPythonExecutable } from '../scripts/test-runtime.mjs'

function bridgeSource() {
  const result = spawnSync(testPythonExecutable(), ['-c', 'from codex_runtime.mcp_app import _bridge; print(_bridge())'], {
    cwd: PROJECT_ROOT,
    encoding: 'utf8',
    shell: false,
  })
  assert.equal(result.status, 0, result.stderr)
  const match = result.stdout.match(/<script>\s*([\s\S]*?)\s*<\/script>/)
  assert.ok(match, 'MCP App bridge should be a standalone script')
  return match[1]
}

test('MCP App uses the chart result included in ui/initialize before waiting for notifications', async () => {
  const listeners = new Map()
  const sent = []
  const firstPayload = {
    context_ref: 'current-dialogue-only-context',
    chart_session: 'initial-chart-session',
    chartCommands: [{ type: 'SET_CANDLES', rows: [] }],
  }
  let window
  const emit = data => listeners.get('message')({ source: parent, data })
  const parent = {
    postMessage(message) {
      sent.push(message)
      if (message.method === 'ui/initialize') {
        queueMicrotask(() => emit({
          jsonrpc: '2.0', id: message.id,
          result: {
            hostContext: { locale: 'zh-CN' },
            toolResult: { structuredContent: firstPayload },
          },
        }))
      }
    },
  }
  const document = {
    readyState: 'complete',
    createElement: () => ({ dataset: {} }),
    getElementById: () => null,
    querySelector: () => null,
    addEventListener: () => assert.fail('ready document must initialize immediately'),
  }
  window = {
    parent,
    fetch: async () => ({ ok: true }),
    addEventListener(type, listener) { listeners.set(type, listener) },
  }
  const context = {
    window,
    document,
    navigator: { language: 'en-US' },
    crypto: { randomUUID: () => 'test-app-instance' },
    Response: class {},
    console,
    setTimeout: () => 1,
    clearTimeout: () => {},
    queueMicrotask,
  }
  await import('node:vm').then(({ runInNewContext }) => runInNewContext(bridgeSource(), context))
  const readiness = await window.__FT_KLINE_APP__.ready

  assert.equal(window.__DSH_CHART_SESSION__, firstPayload)
  assert.equal(readiness[1], firstPayload)
  assert.ok(sent.some(message => message.method === 'ui/notifications/initialized'))
})
