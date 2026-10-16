import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { ChartContextBroker } from './chart-context.ts'
import { ChartApplications } from './chart-applications.ts'
import { startFtshareSettingsBridge, type FtshareSettingsService } from './ftshare-settings-bridge.ts'

export const name = 'dsh-kline-sidebar'
export const inject = ['webServer']

const RUNTIME_DIR = runtimeDirectory()
const RUNTIME_FILE = join(RUNTIME_DIR, 'services', `${process.pid}.json`)
const SESSION_DIR = join(RUNTIME_DIR, 'sessions')
const VENDOR_FILE = fileURLToPath(new URL('../view/vendor/klinecharts.min.js', import.meta.url))
const LOGO_FILE = fileURLToPath(new URL('../view/ft-logo.jpg', import.meta.url))
const MAX_PROXY_BYTES = 8 * 1024 * 1024
const CHART_ACTIONS = new Set([
  'analyze_kline',
  'analyze_key_levels',
  'calc_range',
  'fetch_candles',
  'fetch_comparison_candles',
  'fetch_security_workspace',
  'fetch_market_pulse',
  'fetch_market_board_detail',
  'fetch_security_intelligence',
  'watchlist_get',
  'watchlist_save',
  'market_ticker',
  'search_symbols',
  'symbol_directory',
  'data_source_status',
  'configure_ftshare',
  'test_ftshare_connection',
])

interface WebServerContext {
  effect(callback: () => () => void, label: string): void
  inject?(deps: string[], callback: (ctx: WebServerContext) => void): unknown
  systemPrompt?: { context(input: {name: string; order: number; text: (context: any) => string}): () => void }
  ftshareSettings?: FtshareSettingsService
  webServer: {
    register(route: {
      kind: 'prefix'
      path: string
      handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>
    }): () => void
  }
}

export function apply(ctx: WebServerContext): void {
  const contexts = new ChartContextBroker(join(RUNTIME_DIR, 'views', String(process.pid)),()=>Date.now(),RUNTIME_DIR)
  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: '/dsh-kline',
    handler: (request, response) => serveRuntimeSession(request, response, contexts),
  }), 'dsh-kline: chart session route')
  ctx.inject?.(['systemPrompt'], scoped => {
    if (typeof scoped.systemPrompt?.context !== 'function') return
    scoped.effect(() => scoped.systemPrompt!.context({name: 'dsh-kline:current-view', order: 350,
      text: context => contexts.prompt(context)}), 'dsh-kline: current chart context')
  })
  ctx.inject?.(['ftshareSettings'], scoped => {
    if (!scoped.ftshareSettings?.apiKey) return
    const bridge = startFtshareSettingsBridge({settings: scoped.ftshareSettings, runtimeDirectory: RUNTIME_DIR})
    scoped.effect(() => () => { void bridge.dispose() }, 'dsh-kline: FTShare settings credential bridge')
  })
}

async function serveRuntimeSession(request: IncomingMessage, response: ServerResponse, contexts: ChartContextBroker): Promise<void> {
  const url = new URL(request.url ?? '/', 'http://localhost')
  const pathname = url.pathname
  try {
    if (pathname === '/dsh-kline/recovery' && request.method === 'GET') {
      try {
        const recovery = await new ChartApplications(RUNTIME_DIR).recover(url.searchParams.get('conversation') ?? '')
        sendJson(response, 200, recovery)
      } catch { sendJson(response, 200, {ok:false,error:'confirmed_chart_recovery_unavailable'}) }
      return
    }
    if (pathname === '/dsh-kline/context') {
      if (request.method !== 'POST') { sendJson(response, 405, {ok:false,error:'method_not_allowed'}); return }
      if (request.headers['content-type']?.split(';')[0] !== 'application/json'
        || request.headers.origin && new URL(request.headers.origin).host !== request.headers.host) {
        sendJson(response, 403, {ok:false,error:'invalid_context_origin'}); return
      }
      try {
        const result = await contexts.publish(JSON.parse((await readRequestBody(request)).toString('utf8')))
        sendJson(response, 200, result)
      } catch {
        sendJson(response, 400, {ok:false,error:'context_publication_rejected'})
      }
      return
    }
    // Static browser assets must remain available before the first chart session exists.
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
    // Never infer a chart from the global latest publication. The browser
    // obtains this opaque reference from the owning conversation's result.
    if (pathname === '/dsh-kline/session' || pathname === '/dsh-kline/data') {
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        sendJson(response, 405, { ok: false, error: 'method_not_allowed' })
        return
      }
      const token = url.searchParams.get('session') ?? ''
      if (!/^[A-Za-z0-9_-]{32}$/.test(token)) {
        sendJson(response, 200, { ok: false, error: 'chart_session_required' })
        return
      }
      const saved = JSON.parse(await readFile(join(SESSION_DIR, `${token}.json`), 'utf8')) as RuntimeSession & { payload: unknown }
      if (saved.session !== token || saved.ok !== true) throw new Error('invalid_chart_snapshot')
      if (pathname === '/dsh-kline/data') {
        sendJson(response, 200, { ok: true, session: token, payload: saved.payload }, request.method === 'HEAD')
      } else {
        sendJson(response, 200, { ok: true, session: token, symbol: saved.symbol, name: saved.name, published_at: saved.published_at }, request.method === 'HEAD')
      }
      return
    }
    const session = await readLiveSession()
    if (!session) {
      sendJson(response, 200, unavailableService(), request.method === 'HEAD')
      return
    }
    if (pathname.startsWith('/dsh-kline/api/tools/') && request.method === 'POST') {
      const action = pathname.slice('/dsh-kline/api/tools/'.length).replaceAll('/', '')
      if (!CHART_ACTIONS.has(action)) {
        sendJson(response, 404, { ok: false, error: 'unsupported_chart_action' })
        return
      }
      const body = await readRequestBody(request)
      await proxyJson(response, `${serviceOrigin(session)}/api/tools/${encodeURIComponent(action)}`, {
        method: 'POST',
        headers: { ...chartServiceHeaders(session), 'Content-Type': 'application/json' },
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
        ? (pathname === '/dsh-kline/data' || pathname === '/dsh-kline/session'
          ? { ok: false, error: 'chart_session_unavailable', message: '这张图表的快照已不可用，请在当前对话重新分析该标的。' }
          : unavailableService())
        : { ok: false, error: 'chart_session_manifest_failed' },
      request.method === 'HEAD',
    )
  }
}

function unavailableService() {
  return { ok: false, error: 'chart_session_unavailable', message: '当前 DSH 的行情服务尚未就绪，请稍后重试；若持续失败，请重启 dsh web。' }
}

interface RuntimeSession extends Record<string, unknown> {
  ok: true
  process_id: number
  session: string
  service_url: string
  service_token: string
  published_at: number
}

export function runtimeDirectory(env: NodeJS.ProcessEnv = process.env): string {
  const explicit = String(env.DSH_KLINE_RUNTIME_DIR || '').trim()
  if (explicit) return resolve(explicit)
  if (process.platform === 'win32') {
    const local = String(env.LOCALAPPDATA || env.APPDATA || '').trim()
    return join(local || join(homedir(), 'AppData', 'Local'), 'dsh_kline', 'runtime')
  }
  const cache = String(env.XDG_CACHE_HOME || '').trim()
  return join(cache || join(homedir(), '.cache'), 'dsh_kline', 'runtime')
}

function chartServiceHeaders(session: RuntimeSession): Record<string, string> {
  return { 'X-DSH-Kline-Token': session.service_token }
}

async function readLiveSession(): Promise<RuntimeSession | undefined> {
  const payload = JSON.parse(await readFile(RUNTIME_FILE, 'utf8')) as unknown
  return isLiveSession(payload) ? payload as RuntimeSession : undefined
}

function serviceOrigin(session: RuntimeSession): string {
  return new URL(session.service_url).origin
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
    || candidate.host_process_id !== process.pid
    || typeof candidate.session !== 'string'
    || typeof candidate.service_url !== 'string'
    || typeof candidate.service_token !== 'string'
    || typeof candidate.process_id !== 'number'
    || typeof candidate.published_at !== 'number'
    || !Number.isSafeInteger(candidate.process_id)
    || candidate.process_id <= 0
    || candidate.service_token.length < 32
    || !Number.isSafeInteger(candidate.published_at)
    || candidate.published_at <= 0
  ) return false
  try {
    const serviceUrl = new URL(candidate.service_url)
    if (serviceUrl.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(serviceUrl.hostname)) return false
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
