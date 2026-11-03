import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PassThrough } from 'node:stream'
import { EventEmitter } from 'node:events'
import { setTimeout as delay } from 'node:timers/promises'
import { clientMode, serve } from '../scripts/codex-bootstrap.mjs'

const desktop = { capabilities: { extensions: { 'io.modelcontextprotocol/ui': { mimeTypes: ['text/html;profile=mcp-app'] } } } }
function fixture(options = {}) {
  const input = new PassThrough(), output = new PassThrough(), error = new PassThrough()
  const replies = [], forwarded = []
  output.on('data', data => replies.push(...String(data).trim().split('\n').map(JSON.parse)))
  const child = Object.assign(new EventEmitter(), { stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough(), kill() { this.killed = true } })
  child.stdin.on('data', data => forwarded.push(...String(data).trim().split('\n').map(JSON.parse)))
  const server = serve({ input, output, error, args: ['fake-server'], env: { FT_KLINE_CLIENT: 'auto' }, spawnServer() { return child }, ...options })
  const send = message => input.write(`${JSON.stringify({ jsonrpc: '2.0', ...message })}\n`)
  const initialize = (params = desktop) => send({ id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', ...params } })
  const ready = () => child.stdout.write(`${JSON.stringify({ jsonrpc: '2.0', id: 'ft-kline-bootstrap-initialize', result: { capabilities: {} } })}\n`)
  return { child, replies, forwarded, send, initialize, ready, close: server.shutdown }
}

test('host capability selects desktop; explicit mode still overrides it', () => {
  assert.equal(clientMode(desktop), 'desktop')
  assert.equal(clientMode({ clientInfo: { name: 'codex-cli' } }), 'cli')
  assert.equal(clientMode({ clientInfo: { name: 'unknown-desktop' } }), 'cli')
  assert.equal(clientMode(desktop, 'cli'), 'cli')
  assert.equal(clientMode({}, 'desktop'), 'desktop')
  assert.throws(() => clientMode({}, 'typo'))
})

test('a client caching its first catalog can call analyze_kline without refreshing tools', () => {
  const f = fixture()
  try {
    f.initialize()
    assert.equal(f.replies[0].result.capabilities.tools.listChanged, false)
    assert.match(f.replies[0].result.instructions, /pass its current context_ref to analyze_kline/)
    f.send({ id: 2, method: 'tools/list' })
    const initial = f.replies.at(-1).result.tools
    assert.ok(initial.some(t => t.name === 'analyze_kline'))
    assert.equal(initial.find(t => t.name === 'analyze_kline')._meta.ui.resourceUri, 'ui://ft-kline/chart-v3')
    assert.ok(initial.some(t => t.name === 'prepare_chart_edit'))
    assert.deepEqual(initial.find(t => t.name === 'ft_kline_app_action')._meta.ui.visibility, ['app'])
    f.send({ id: 3, method: 'tools/call', params: { name: 'analyze_kline', arguments: { symbol: '600036.XSHG' } } })
    assert.equal(f.forwarded.length, 1, 'no premature provider call')
    f.ready()
    assert.equal(f.forwarded.at(-1).id, 3, 'dispatch the original call once ready')
    assert.ok(!f.replies.some(r => r.method === 'notifications/tools/list_changed'))
    f.send({ id: 4, method: 'tools/list' })
    assert.deepEqual(f.replies.at(-1).result.tools, initial)
  } finally { f.close() }
  assert.equal(f.child.killed, true)
})

test('resource preloading works even when Python has not started', () => {
  const f = fixture()
  try {
    f.initialize()
    f.send({ id: 2, method: 'resources/list' })
    const resource = f.replies.at(-1).result.resources[0]
    f.send({ id: 3, method: 'resources/read', params: { uri: resource.uri } })
    assert.ok(f.replies.at(-1).result.contents[0].text.includes('ui/initialize'))
    assert.equal(f.forwarded.length, 1)
  } finally { f.close() }
})

test('a timed-out preparation call is rejected and never dispatches later', async () => {
  const f = fixture({ preparationWaitMs: 10 })
  try {
    f.initialize()
    f.send({ id: 2, method: 'tools/call', params: { name: 'apply_chart_edit', arguments: {} } })
    await delay(30)
    assert.equal(f.replies.at(-1).result.structuredContent.operation_dispatched, false)
    assert.equal(f.replies.at(-1).result.structuredContent.error, 'runtime_preparing')
    f.ready()
    assert.ok(!f.forwarded.some(r => r.id === 2))
  } finally { f.close() }
})

test('cancellation and disconnect remove queued calls before the backend becomes ready', () => {
  const f = fixture()
  try {
    f.initialize()
    f.send({ id: 2, method: 'tools/call', params: { name: 'analyze_kline', arguments: {} } })
    f.send({ method: 'notifications/cancelled', params: { requestId: 2 } })
    f.ready()
    assert.ok(!f.forwarded.some(r => r.id === 2))
  } finally { f.close() }
})

test('CLI has no drawing descriptors/resources and rejects drawing calls', () => {
  const f = fixture()
  try {
    f.initialize({})
    f.send({ id: 2, method: 'tools/list' })
    assert.ok(!f.replies.at(-1).result.tools.some(t => t.name === 'prepare_chart_edit'))
    assert.equal(f.replies.at(-1).result.tools.find(t => t.name === 'analyze_kline')._meta, undefined)
    f.send({ id: 3, method: 'resources/list' })
    assert.deepEqual(f.replies.at(-1).result.resources, [])
    f.send({ id: 4, method: 'tools/call', params: { name: 'prepare_chart_edit', arguments: {} } })
    assert.equal(f.replies.at(-1).error.code, -32602)
  } finally { f.close() }
})

test('spawn failure leaves a stable catalog and a clear failure status', () => {
  const f = fixture({ spawnServer() { throw new Error('missing runtime') } })
  try {
    f.initialize()
    f.send({ id: 2, method: 'tools/list' })
    assert.ok(f.replies.at(-1).result.tools.some(t => t.name === 'analyze_kline'))
    f.send({ id: 3, method: 'tools/call', params: { name: 'ft_kline_runtime_status' } })
    assert.equal(f.replies.at(-1).result.structuredContent.phase, 'failed')
    f.send({ id: 4, method: 'tools/call', params: { name: 'analyze_kline', arguments: {} } })
    assert.equal(f.replies.at(-1).result.structuredContent.error, 'runtime_unavailable')
  } finally { f.close() }
})
