import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer, type RequestListener } from 'node:http'
import { Socket } from 'node:net'
import { requestChartHttp, ChartHttpError } from '../src/chart-http.ts'
import { probeChartService, type ServiceLocator } from '../src/chart-service-status.ts'

async function serve(handler: RequestListener) {
  const server = createServer(handler)
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  return { url: `http://127.0.0.1:${(server.address() as { port: number }).port}`,
    close: async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())) } }
}
const options = { timeoutMs: 1000, maxBytes: 1024 }

test('backend health and POST transport avoid global fetch and socket QoS, preserving auth and body', async () => {
  const backend = await serve((req, res) => {
    if (req.url === '/healthz') return void res.end(JSON.stringify({ ok: true, service: 'dsh_kline_chart', instance_id: 'I', process_id: 42, host_process_id: 43 }))
    assert.equal(req.method, 'POST'); assert.equal(req.headers['x-dsh-kline-token'], 'a'.repeat(32))
    let body = ''; req.on('data', chunk => body += chunk); req.on('end', () => { res.statusCode = 201; res.end(body) })
  })
  const originalFetch = globalThis.fetch
  const originalTos = Object.getOwnPropertyDescriptor(Socket.prototype, 'setTypeOfService')
  let tosCalls = 0
  globalThis.fetch = () => { throw Error('The host native fetch must not run') }
  Object.defineProperty(Socket.prototype, 'setTypeOfService', { configurable: true, value() {
    tosCalls++; throw Object.assign(Error('setTypeOfService EINVAL'), { code: 'EINVAL', syscall: 'setTypeOfService' })
  } })
  try {
    await probeChartService({ service_url: backend.url, instance_id: 'I', process_id: 42, host_process_id: 43 } as ServiceLocator)
    const result = await requestChartHttp(backend.url + '/api/tools/data_source_status', { ...options, method: 'POST',
      headers: { 'X-DSH-Kline-Token': 'a'.repeat(32), 'Content-Type': 'application/json' }, body: '{"test":true,"symbol":"南京医药"}' })
    assert.equal(result.status, 201); assert.equal(result.body.toString(), '{"test":true,"symbol":"南京医药"}'); assert.equal(tosCalls, 0)
  } finally {
    globalThis.fetch = originalFetch
    if (originalTos) Object.defineProperty(Socket.prototype, 'setTypeOfService', originalTos)
    else Reflect.deleteProperty(Socket.prototype, 'setTypeOfService')
    await backend.close()
  }
})

test('reset connections reject safely and a subsequent request succeeds', async () => {
  const backend = await serve((req, res) => { if (req.url === '/reset') req.socket.destroy(); else res.end('ok') })
  try {
    await assert.rejects(requestChartHttp(backend.url + '/reset', options), (e: unknown) => e instanceof ChartHttpError && e.reason === 'unreachable')
    assert.equal((await requestChartHttp(backend.url, options)).body.toString(), 'ok')
  } finally { await backend.close() }
})

test('response size and whole-body deadlines stay bounded', async () => {
  const backend = await serve((req, res) => {
    if (req.url === '/slow') { res.writeHead(200); res.write('partial'); return }
    res.end('x'.repeat(2000))
  })
  try {
    await assert.rejects(requestChartHttp(backend.url, options), (e: unknown) => e instanceof ChartHttpError && e.reason === 'too_large')
    await assert.rejects(requestChartHttp(backend.url + '/slow', { ...options, timeoutMs: 40 }), (e: unknown) => e instanceof ChartHttpError && e.reason === 'timeout')
  } finally { await backend.close() }
})

test('private transport rejects external destinations and does not follow redirects with its token', async () => {
  for (const url of ['https://127.0.0.1/', 'http://example.com/', 'http://user:password@127.0.0.1/'])
    await assert.rejects(requestChartHttp(url, options), (e: unknown) => e instanceof ChartHttpError && e.reason === 'invalid_url')
  const backend = await serve((_req, res) => { res.writeHead(302, { Location: 'https://example.com/' }); res.end('redirect') })
  try { assert.equal((await requestChartHttp(backend.url, options)).status, 302) }
  finally { await backend.close() }
})
