import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const sourcePath = `${root}/view/kline.html`
const outputPath = `${root}/src/client/generated-view.ts`
const html = await readFile(sourcePath, 'utf8')
const packageJson = JSON.parse(await readFile(`${root}/package.json`, 'utf8'))

const style = html.match(/<style>([\s\S]*?)<\/style>/)?.[1]
const body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1]
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
const runtime = scripts.at(-1)?.[1]?.replaceAll('__DSH_KLINE_VERSION__', String(packageJson.version || '0.0.0'))

if (!style || !body || !runtime) throw new Error('view/kline.html does not contain the expected style, body, and runtime script')

const scopedStyle = style
  .replaceAll('html[data-theme="dark"][data-market="foreign"]', ':host([data-theme="dark"][data-market="foreign"])')
  .replaceAll('html[data-theme="dark"]', ':host([data-theme="dark"])')
  .replaceAll('html[data-market="foreign"]', ':host([data-market="foreign"])')
  .replaceAll('html, body', '__DSH_KLINE_DOCUMENT_ROOTS__')
  .replaceAll(':root', ':host')
  .replace(/\bbody\b/g, '.dsh-kline-view-body')
  .replace(/\bhtml\b/g, ':host')
  .replaceAll('__DSH_KLINE_DOCUMENT_ROOTS__', ':host, .dsh-kline-view-body')

const markup = body
  .replace(/<script[^>]*>[\s\S]*?<\/script>/g, '')
  .replaceAll('__FTV_LOGO_DATA__', '/dsh-kline/logo.jpg')

const generated = `// @ts-nocheck
// Generated from view/kline.html by scripts/generate-client-view.mjs.
import { mergeHorizontalLineSnapshot } from './horizontal-lines'
import { createChartContextPublisher } from './chart-context'
import { collectDrawingFeedback } from '../drawing-feedback'
import { drawingSourceKey } from '../chart-observation'
export const PACKAGE_VERSION = ${JSON.stringify(packageJson.version)}

const VIEW_STYLE = ${JSON.stringify(scopedStyle)}
const VIEW_MARKUP = ${JSON.stringify(markup)}

export function mountKlineView(root, payload, dependencies = {}) {
  if (payload?.view_source_guard) throw new Error('当前图来源凭证不能作为普通图表入口渲染。')
  if (payload?.drawing_guard) throw new Error('绘图准备结果尚未应用，不能通过普通图表入口绕过状态检查。')
  const host = root.host
  const storagePrefix = 'dsh-kline:conversation:' + encodeURIComponent(dependencies.conversationId || '')
  const viewKey = storagePrefix + ':view'
  let restored = false
  try {
    const saved = JSON.parse(globalThis.localStorage.getItem(viewKey) || 'null')
    const drawingUpdate = mergeHorizontalLineSnapshot(payload, saved)
    if (drawingUpdate) { payload = drawingUpdate; restored = true }
    // A launcher deliberately has no selected instrument. It must never be
    // replaced by a saved chart payload, even when the host temporarily
    // reuses the previous conversation scope for its New Session screen.
    const confirmedRestore = payload?._live_chart_session === dependencies.chartSession && payload?._live_application_pending === false
      && saved?.payload?._live_chart_session === dependencies.chartSession && saved?.payload?._live_application_pending === false
    if (!drawingUpdate && payload?.workspace_mode !== 'launcher' && (saved?.session === dependencies.chartSession || confirmedRestore) && Array.isArray(saved.payload?.chartCommands)) {
      payload = saved.payload
      restored = true
    }
  } catch {}
  if (payload?.drawing_guard || payload?.view_source_guard || payload?._live_application_pending) throw new Error('缓存中的绘图候选尚未确认，不能直接渲染。')
  const controller = new AbortController()
  dependencies.restored = restored
  dependencies.saveView = next => {
    if (controller.signal.aborted || next?._live_application_pending) return
    dependencies.onIdentity?.(next.symbol, next.name)
    try { globalThis.localStorage.setItem(viewKey, JSON.stringify({ session: dependencies.chartSession, payload: next })) } catch {}
  }
  dependencies.storage = {
    getItem: key => globalThis.localStorage.getItem(key === 'dsh-kline.workspace.v1' ? storagePrefix + ':workspace' : key),
    setItem: (key, value) => {
      if (!controller.signal.aborted) globalThis.localStorage.setItem(key === 'dsh-kline.workspace.v1' ? storagePrefix + ':workspace' : key, value)
    },
    removeItem: key => globalThis.localStorage.removeItem(key === 'dsh-kline.workspace.v1' ? storagePrefix + ':workspace' : key),
  }
  root.innerHTML = \`<style>\${VIEW_STYLE}</style><div class="dsh-kline-view-body">\${VIEW_MARKUP}</div>\`
  const body = root.querySelector('.dsh-kline-view-body')
  const lifecycle = createScopedWindow(host, payload, dependencies)
  const window = lifecycle.window
  window.__DSH_KLINE_INITIAL_CHART_SESSION__ = dependencies.chartSession
  const document = createScopedDocument(root, host, body)
  const fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith('/api/tools/')) {
      return globalThis.fetch('/dsh-kline/api/tools/' + input.slice('/api/tools/'.length), { ...init, signal: controller.signal })
    }
    return globalThis.fetch(input, init)
  }
  const contextPublisher = createChartContextPublisher({
    conversationId: dependencies.ownerConversationId,
    capture: () => captureChartContext(lastChartPayload?._live_chart_session || dependencies.chartSession),
    isActive: () => !controller.signal.aborted && host.isConnected && globalThis.document.visibilityState !== 'hidden'
      && (dependencies.isVisible?.() ?? true),
    apply: (next, token) => applyLiveDrawingCommands(next, token),
    confirm: token => confirmLiveDrawingApplication(token),
    captureSource: () => captureLiveChartSource(),
    bindSource: (token, previous) => bindLiveChartSource(token, previous),
    confirmSource: (token, confirmed) => confirmLiveChartSource(token, confirmed),
    onSourceStatus: status => renderLiveSourceStatus(status),
    onPublished: publication => { window.__DSH_KLINE_OBSERVATION__ = publication; renderDrawingWorkbench?.() },
    feedback: () => collectDrawingFeedback(lastChartPayload, captureChartContext(lastChartPayload?._live_chart_session || dependencies.chartSession), kchart),
  })
  window.__DSH_KLINE_DRAWING_FEEDBACK__ = (next, previous, phase) => collectDrawingFeedback(next,
    captureChartContext(lastChartPayload?._live_chart_session || dependencies.chartSession), kchart, previous, phase)
  window.__DSH_KLINE_REPORT_CONTEXT__ = contextPublisher.notify
  window.__DSH_KLINE_SOURCE_KEY__ = drawingSourceKey
  window.__DSH_KLINE_RETRY_SOURCE__ = contextPublisher.retrySource
  dependencies.onContextPublisher?.(contextPublisher)

${runtime}

  return () => {
    contextPublisher.dispose()
    lifecycle.dispose()
    controller.abort()
    root.innerHTML = ''
  }
}

function createScopedDocument(root, host, body) {
  const realDocument = globalThis.document
  return new Proxy(realDocument, {
    get(target, property) {
      if (property === 'documentElement') return host
      if (property === 'body') return body
      if (property === 'activeElement') return root.activeElement
      if (property === 'getElementById') return id => root.getElementById(id)
      if (property === 'querySelector') return selector => root.querySelector(selector)
      if (property === 'querySelectorAll') return selector => root.querySelectorAll(selector)
      if (property === 'addEventListener') return (...args) => root.addEventListener(...args)
      if (property === 'removeEventListener') return (...args) => root.removeEventListener(...args)
      const value = Reflect.get(target, property, target)
      return typeof value === 'function' ? value.bind(target) : value
    },
  })
}

function createScopedWindow(host, payload, dependencies) {
  const realWindow = globalThis.window
  const local = new Map([['__DSH_CHART_SESSION__', payload]])
  local.set('localStorage', dependencies.storage)
  local.set('__DSH_KLINE_RESTORED__', dependencies.restored)
  local.set('__DSH_KLINE_SAVE_VIEW__', dependencies.saveView)
  local.set('__DSH_KLINE_DISPOSED__', false)
  local.set('__DSH_KLINE_INTERFACE__', dependencies.interfaceMode)
  if (dependencies.klinecharts) {
    local.set('klinecharts', dependencies.klinecharts)
    local.set('__FTV_KLINECHARTS_VENDOR__', { started: true, source: 'client_dependency' })
  }
  const listeners = []
  const intervals = new Set()
  const timeouts = new Set()
  const proxy = new Proxy(realWindow, {
    get(target, property) {
      if (local.has(property)) return local.get(property)
      if (property === 'innerHeight') return host.clientHeight || target.innerHeight
      if (property === 'addEventListener') return (type, listener, options) => {
        listeners.push([type, listener, options])
        target.addEventListener(type, listener, options)
      }
      if (property === 'removeEventListener') return (type, listener, options) => target.removeEventListener(type, listener, options)
      if (property === 'setInterval') return (handler, timeout, ...args) => {
        if (local.get('__DSH_KLINE_DISPOSED__')) return undefined
        const id = target.setInterval(handler, timeout, ...args)
        intervals.add(id)
        return id
      }
      if (property === 'clearInterval') return id => {
        intervals.delete(id)
        target.clearInterval(id)
      }
      if (property === 'setTimeout') return (handler, timeout, ...args) => {
        if (local.get('__DSH_KLINE_DISPOSED__')) return undefined
        const id = target.setTimeout(handler, timeout, ...args)
        timeouts.add(id)
        return id
      }
      if (property === 'clearTimeout') return id => {
        timeouts.delete(id)
        target.clearTimeout(id)
      }
      const value = Reflect.get(target, property, target)
      return typeof value === 'function' ? value.bind(target) : value
    },
    set(_target, property, value) {
      local.set(property, value)
      return true
    },
  })
  return {
    window: proxy,
    dispose() {
      local.set('__DSH_KLINE_DISPOSED__', true)
      for (const [type, listener] of listeners) {
        if (type === 'beforeunload') {
          try { listener(new Event('beforeunload')) } catch {}
        }
      }
      for (const [type, listener, options] of listeners) realWindow.removeEventListener(type, listener, options)
      for (const id of intervals) realWindow.clearInterval(id)
      for (const id of timeouts) realWindow.clearTimeout(id)
    },
  }
}
`

await writeFile(outputPath, generated)
