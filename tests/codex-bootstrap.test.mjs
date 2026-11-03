import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PassThrough } from 'node:stream'
import { EventEmitter } from 'node:events'
import { clientMode, serve } from '../scripts/codex-bootstrap.mjs'

const desktop = { capabilities: { extensions: { 'io.modelcontextprotocol/ui': { mimeTypes: ['text/html;profile=mcp-app'] } } } }

test('auto mode requires the host HTML capability and honors an explicit override', () => {
  assert.equal(clientMode(desktop), 'desktop')
  assert.equal(clientMode({ clientInfo: { name: 'codex-cli' } }), 'cli')
  assert.equal(clientMode({ clientInfo: { name: 'some-desktop-name' } }), 'cli')
  assert.equal(clientMode(desktop, 'cli'), 'cli')
  assert.equal(clientMode({}, 'desktop'), 'desktop')
  assert.throws(() => clientMode({}, 'typo'))
})

test('a slow Python install cannot delay initialization; the same connection upgrades its catalog', async () => {
  const input = new PassThrough(), output = new PassThrough(), error = new PassThrough()
  const replies = [], forwarded = []
  output.on('data', data => replies.push(...String(data).trim().split('\n').map(JSON.parse)))
  const child = Object.assign(new EventEmitter(), { stdin: new PassThrough(), stdout: new PassThrough(), stderr: new PassThrough(), kill() { this.killed = true } })
  child.stdin.on('data', data => forwarded.push(...String(data).trim().split('\n').map(JSON.parse)))
  let selected
  const server = serve({ input, output, error, args: ['fake-server'], env: { FT_KLINE_CLIENT: 'auto' },
    spawnServer(_command, _args, options) { selected = options.env.FT_KLINE_CLIENT; return child } })
  const send = message => input.write(`${JSON.stringify({ jsonrpc: '2.0', ...message })}\n`)
  try {
    send({ id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', ...desktop } })
    assert.equal(replies[0].id, 1)
    assert.match(replies[0].result.instructions, /pass its current context_ref to analyze_kline/)
    assert.match(replies[0].result.instructions, /user_confirmed_candidate=true/)
    assert.equal(selected, 'desktop')
    send({ id: 2, method: 'tools/list' })
    assert.equal(replies.at(-1).result.tools[0].name, 'ft_kline_runtime_status')
    send({ id: 3, method: 'tools/call', params: { name: 'ft_kline_runtime_status' } })
    assert.equal(replies.at(-1).result.structuredContent.phase, 'preparing')
    send({ method: 'notifications/initialized' })
    assert.equal(forwarded.length, 1)
    child.stdout.write(`${JSON.stringify({ jsonrpc: '2.0', id: 'ft-kline-bootstrap-initialize', result: { capabilities: {} } })}\n`)
    assert.ok(replies.some(item => item.method === 'notifications/tools/list_changed'))
    assert.ok(replies.some(item => item.method === 'notifications/resources/list_changed'))
    assert.equal(forwarded.at(-1).method, 'notifications/initialized')
    send({ id: 4, method: 'tools/list' })
    assert.equal(forwarded.at(-1).id, 4)
    child.stdout.write(`${JSON.stringify({ jsonrpc: '2.0', id: 4, result: { tools: [{ name: 'analyze_kline' }] } })}\n`)
    assert.equal(replies.at(-1).result.tools[0].name, 'analyze_kline')
    child.emit('exit', 1)
    send({ id: 5, method: 'tools/call', params: { name: 'ft_kline_runtime_status' } })
    assert.equal(replies.at(-1).result.structuredContent.phase, 'failed')
    assert.equal(replies.at(-1).result.isError, true)
  } finally { server.shutdown() }
  assert.equal(child.killed, true)
})

test('a spawn failure remains inspectable without crashing the initialized connection', () => {
  const input = new PassThrough(), output = new PassThrough(), replies = []
  output.on('data', data => replies.push(...String(data).trim().split('\n').map(JSON.parse)))
  const server = serve({ input, output, spawnServer() { throw new Error('missing runtime') } })
  try {
    input.write('null\n')
    assert.equal(replies.at(-1).error.code, -32600)
    input.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {} }) + '\n')
    input.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'ft_kline_runtime_status' } }) + '\n')
    assert.equal(replies.at(-1).result.structuredContent.phase, 'failed')
  } finally { server.shutdown() }
})
