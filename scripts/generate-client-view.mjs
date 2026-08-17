import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const sourcePath = `${root}/view/kline.html`
const outputPath = `${root}/src/client/generated-view.ts`
const html = await readFile(sourcePath, 'utf8')

const style = html.match(/<style>([\s\S]*?)<\/style>/)?.[1]
const body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1]
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
const runtime = scripts.at(-1)?.[1]

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

const VIEW_STYLE = ${JSON.stringify(scopedStyle)}
const VIEW_MARKUP = ${JSON.stringify(markup)}

export function mountKlineView(root, payload) {
  const host = root.host
  root.innerHTML = \`<style>\${VIEW_STYLE}</style><div class="dsh-kline-view-body">\${VIEW_MARKUP}</div>\`
  const body = root.querySelector('.dsh-kline-view-body')
  const lifecycle = createScopedWindow(host, payload)
  const window = lifecycle.window
  const document = createScopedDocument(root, host, body)
  const fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith('/api/tools/')) {
      return globalThis.fetch('/dsh-kline/api/tools/' + input.slice('/api/tools/'.length), init)
    }
    return globalThis.fetch(input, init)
  }

${runtime}

  return () => {
    lifecycle.dispose()
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

function createScopedWindow(host, payload) {
  const realWindow = globalThis.window
  const local = new Map([['__DSH_CHART_SESSION__', payload]])
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
        const id = target.setInterval(handler, timeout, ...args)
        intervals.add(id)
        return id
      }
      if (property === 'clearInterval') return id => {
        intervals.delete(id)
        target.clearInterval(id)
      }
      if (property === 'setTimeout') return (handler, timeout, ...args) => {
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
