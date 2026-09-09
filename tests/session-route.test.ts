import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { randomBytes } from 'node:crypto'
import { mkdir, mkdtemp, rm, writeFile, unlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const testRuntime = await mkdtemp(join(tmpdir(), 'dsh-kline-session-test-'))
process.env.DSH_KLINE_RUNTIME_DIR = testRuntime
const { apply } = await import('../src/index.ts')
after(async () => { await rm(testRuntime, { recursive: true, force: true }) })

test('each Harness uses only its own live MCP locator, never a sibling or stale service', async () => {
  const directory = join(testRuntime, 'services')
  await mkdir(directory, {recursive:true})
  const owned = join(directory, `${process.pid}.json`)
  const sibling = join(directory, `${process.pid + 10000000}.json`)
  const calls: string[] = []
  const upstream = createServer((request, response) => {
    assert.equal(request.headers['x-dsh-kline-token'], 'a'.repeat(32))
    calls.push(request.url ?? '')
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ok:true, source:'owned-service'}))
  })
  await new Promise<void>(resolve => upstream.listen(0, '127.0.0.1', resolve))
  let handler: any
  apply({effect: callback => {callback()}, webServer:{register: route => {handler = route.handler; return () => {}}}})
  const server = createServer((request, response) => {void handler(request, response)})
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const endpoint = `http://127.0.0.1:${(server.address() as any).port}/dsh-kline/api/tools/data_source_status`
  const document = {ok:true, process_id:process.pid, host_process_id:process.pid, session:'',
    service_url:`http://127.0.0.1:${(upstream.address() as any).port}`, service_token:'a'.repeat(32), published_at:Math.floor(Date.now()/1000)}
  const request = async () => (await fetch(endpoint, {method:'POST', body:'{}'})).json()
  try {
    await writeFile(sibling, JSON.stringify({...document, host_process_id:process.pid + 10000000}), {mode:0o600,flag:'wx'})
    assert.equal((await request()).error, 'chart_session_unavailable')
    await writeFile(owned, JSON.stringify(document), {mode:0o600,flag:'wx'})
    assert.equal((await request()).source, 'owned-service')
    // A test profile publishing/stopping must not replace the main locator.
    await writeFile(sibling, JSON.stringify({...document, process_id:-1}))
    assert.equal((await request()).source, 'owned-service')
    // Misaddressed and dead owner records must fail closed, not borrow another profile.
    await writeFile(owned, JSON.stringify({...document, host_process_id:process.pid + 1}))
    const failed = await request()
    assert.equal(failed.error, 'chart_session_unavailable')
    assert.match(failed.message, /当前 DSH/)
    assert.equal(failed.service_token, undefined)
    await writeFile(owned, JSON.stringify({...document, process_id:-1}))
    assert.equal((await request()).error, 'chart_session_unavailable')
    // MCP restart on the same host replaces only that host's locator.
    await writeFile(owned, JSON.stringify(document))
    assert.equal((await request()).source, 'owned-service')
    assert.equal(calls.length, 3)
  } finally {
    await Promise.all([owned,sibling].map(path => unlink(path).catch(() => {})))
    for (const instance of [server,upstream]) {
      instance.closeAllConnections()
      await new Promise<void>(resolve => instance.close(() => resolve()))
    }
  }
})

test('chart routes require an explicit token and never expose service credentials', async () => {
  let handler: any
  apply({ effect: callback => { callback() }, webServer: { register: route => { handler = route.handler; return () => {} } } })
  const server = createServer((request, response) => { void handler(request, response) })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${(server.address() as any).port}`
  const tokenA = randomBytes(24).toString('base64url'), tokenB = randomBytes(24).toString('base64url')
  const directory = join(testRuntime, 'sessions')
  await mkdir(directory, {recursive: true})
  const paths = [tokenA, tokenB].map(token => join(directory, `${token}.json`))
  try {
    for (const [index, path] of paths.entries()) {
      await writeFile(path, JSON.stringify({ok: true, session: [tokenA, tokenB][index],
        symbol: ['A', 'B'][index], service_token: 'private-secret', process_id: -1,
        payload: {symbol: ['A', 'B'][index]}}), {mode: 0o600, flag: 'wx'})
    }
    assert.equal((await (await fetch(`${origin}/dsh-kline/data`)).json()).error, 'chart_session_required')
    assert.equal((await (await fetch(`${origin}/dsh-kline/data?session=..%2Fchart-session`)).json()).error, 'chart_session_required')
    const missing = await (await fetch(`${origin}/dsh-kline/data?session=${randomBytes(24).toString('base64url')}`)).json()
    assert.match(missing.message, /快照已不可用/)
    // Saved payloads are available after their original process has exited.
    assert.equal((await (await fetch(`${origin}/dsh-kline/data?session=${tokenA}`)).json()).payload.symbol, 'A')
    assert.equal((await (await fetch(`${origin}/dsh-kline/data?session=${tokenB}`)).json()).payload.symbol, 'B')
    const publicSession = await (await fetch(`${origin}/dsh-kline/session?session=${tokenA}`)).json()
    assert.equal(publicSession.symbol, 'A')
    assert.equal(publicSession.service_token, undefined)
    assert.equal(publicSession.payload, undefined)
    assert.equal((await fetch(`${origin}/dsh-kline/data?session=${tokenA}`, {method: 'POST'})).status, 405)
  } finally {
    await Promise.all(paths.map(path => unlink(path)))
    server.closeAllConnections()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
})
