import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import type { IncomingMessage, ServerResponse } from 'node:http'

export const name = 'dsh-kline-sidebar'
export const inject = ['webServer']

const RUNTIME_FILE = fileURLToPath(new URL('../.runtime/chart-session.json', import.meta.url))
const VENDOR_FILE = fileURLToPath(new URL('../view/vendor/klinecharts.min.js', import.meta.url))
const LOGO_FILE = fileURLToPath(new URL('../view/ft-logo.jpg', import.meta.url))
const MAX_SESSION_AGE_SECONDS = 7 * 60 * 60
const MAX_PROXY_BYTES = 8 * 1024 * 1024
const CHART_ACTIONS = new Set([
  'calc_range',
  'fetch_candles',
  'fetch_comparison_candles',
  'fetch_security_workspace',
  'market_ticker',
  'search_symbols',
  'symbol_directory',
])

interface WebServerContext {
  effect(callback: () => () => void, label: string): void
  webServer: {
    register(route: {
      kind: 'prefix'
      path: string
      handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>
    }): () => void
  }
}

export function apply(ctx: WebServerContext): void {
  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: '/dsh-kline',
    handler: serveRuntimeSession,
  }), 'dsh-kline: chart session route')
}

async function serveRuntimeSession(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const pathname = new URL(request.url ?? '/', 'http://localhost').pathname
  try {
    const session = await readLiveSession()
    if (!session) {
      sendJson(response, 200, { ok: false, error: 'chart_session_unavailable' }, request.method === 'HEAD')
      return
    }
    if (pathname === '/dsh-kline/session' && (request.method === 'GET' || request.method === 'HEAD')) {
      const { chart_url: _chartUrl, ...publicSession } = session
      sendJson(response, 200, publicSession, request.method === 'HEAD')
      return
    }
    if (pathname === '/dsh-kline/data' && (request.method === 'GET' || request.method === 'HEAD')) {
      await proxyJson(response, `${chartOrigin(session)}/api/session/${encodeURIComponent(session.session)}`, {
        method: request.method,
      })
      return
    }
    if (pathname === '/dsh-kline/vendor/klinecharts.min.js' && (request.method === 'GET' || request.method === 'HEAD')) {
      const body = await readFile(VENDOR_FILE)
      sendBytes(response, 200, body, 'text/javascript; charset=utf-8', request.method === 'HEAD')
      return
    }
    if (pathname === '/dsh-kline/logo.jpg' && (request.method === 'GET' || request.method === 'HEAD')) {
      const body = await readFile(LOGO_FILE)
      sendBytes(response, 200, body, 'image/jpeg', request.method === 'HEAD')
      return
    }
    if (pathname.startsWith('/dsh-kline/api/tools/') && request.method === 'POST') {
      const action = pathname.slice('/dsh-kline/api/tools/'.length).replaceAll('/', '')
      if (!CHART_ACTIONS.has(action)) {
        sendJson(response, 404, { ok: false, error: 'unsupported_chart_action' })
        return
      }
      const body = await readRequestBody(request)
      await proxyJson(response, `${chartOrigin(session)}/api/tools/${encodeURIComponent(action)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body.toString('utf8'),
      })
      return
    }
    if (pathname.startsWith('/dsh-kline/api/tools/')) {
      response.writeHead(405, { Allow: 'POST' })
      response.end()
      return
    }
    sendJson(response, 404, { ok: false, error: 'not_found' })
  } catch (error) {
    const code = error instanceof Error && 'code' in error ? String(error.code) : ''
    sendJson(
      response,
      code === 'ENOENT' ? 200 : 500,
      code === 'ENOENT'
        ? { ok: false, error: 'chart_session_unavailable' }
        : { ok: false, error: 'chart_session_manifest_failed' },
      request.method === 'HEAD',
    )
  }
}

interface RuntimeSession extends Record<string, unknown> {
  ok: true
  process_id: number
  session: string
  chart_url: string
  published_at: number
}

async function readLiveSession(): Promise<RuntimeSession | undefined> {
  const payload = JSON.parse(await readFile(RUNTIME_FILE, 'utf8')) as unknown
  return isLiveSession(payload) ? payload as RuntimeSession : undefined
}

function chartOrigin(session: RuntimeSession): string {
  return new URL(session.chart_url).origin
}

async function proxyJson(response: ServerResponse, url: string, init: RequestInit): Promise<void> {
  const upstream = await fetch(url, init)
  const body = Buffer.from(await upstream.arrayBuffer())
  if (body.length > MAX_PROXY_BYTES) {
    sendJson(response, 502, { ok: false, error: 'chart_response_too_large' })
    return
  }
  sendBytes(response, upstream.status, body, 'application/json; charset=utf-8')
}

async function readRequestBody(request: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += buffer.length
    if (size > MAX_PROXY_BYTES) throw new Error('request_too_large')
    chunks.push(buffer)
  }
  return Buffer.concat(chunks)
}

function isLiveSession(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  if (
    candidate.ok !== true
    || typeof candidate.session !== 'string'
    || typeof candidate.chart_url !== 'string'
    || typeof candidate.process_id !== 'number'
    || typeof candidate.published_at !== 'number'
    || !Number.isSafeInteger(candidate.process_id)
    || candidate.process_id <= 0
    || !Number.isSafeInteger(candidate.published_at)
    || candidate.published_at <= 0
    || Math.abs(Date.now() / 1000 - candidate.published_at) > MAX_SESSION_AGE_SECONDS
  ) return false
  try {
    const chartUrl = new URL(candidate.chart_url)
    if (chartUrl.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(chartUrl.hostname)) return false
  } catch {
    return false
  }
  try {
    process.kill(candidate.process_id, 0)
    return true
  } catch {
    return false
  }
}

function sendJson(response: ServerResponse, status: number, value: unknown, head = false): void {
  const body = Buffer.from(JSON.stringify(value))
  sendBytes(response, status, body, 'application/json; charset=utf-8', head)
}

function sendBytes(response: ServerResponse, status: number, body: Buffer, contentType: string, head = false): void {
  response.writeHead(status, {
    'Content-Type': contentType,
    'Content-Length': String(body.length),
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  })
  response.end(head ? undefined : body)
}
