import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { randomBytes } from 'node:crypto'
import { mkdir, writeFile, unlink } from 'node:fs/promises'
import { apply } from '../src/index.ts'

test('chart routes require an explicit token and never expose service credentials', async () => {
  let handler: any
  apply({ effect: callback => { callback() }, webServer: { register: route => { handler = route.handler; return () => {} } } })
  const server = createServer((request, response) => { void handler(request, response) })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${(server.address() as any).port}`
  const tokenA = randomBytes(24).toString('base64url'), tokenB = randomBytes(24).toString('base64url')
  const directory = new URL('../.runtime/sessions/', import.meta.url)
  await mkdir(directory, {recursive: true})
  const paths = [tokenA, tokenB].map(token => new URL(`${token}.json`, directory))
  try {
    for (const [index, path] of paths.entries()) {
      await writeFile(path, JSON.stringify({ok: true, session: [tokenA, tokenB][index],
        symbol: ['A', 'B'][index], service_token: 'private-secret', process_id: -1,
        payload: {symbol: ['A', 'B'][index]}}), {mode: 0o600, flag: 'wx'})
    }
    assert.equal((await (await fetch(`${origin}/dsh-kline/data`)).json()).error, 'chart_session_required')
    assert.equal((await (await fetch(`${origin}/dsh-kline/data?session=..%2Fchart-session`)).json()).error, 'chart_session_required')
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
