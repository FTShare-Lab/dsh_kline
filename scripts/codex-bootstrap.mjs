import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { readFileSync, existsSync } from 'node:fs'

const root = new URL('../', import.meta.url)
const catalogs = Object.fromEntries(['desktop', 'cli'].map(mode => [mode,
  JSON.parse(readFileSync(new URL(`codex_runtime/catalog-${mode}.json`, root), 'utf8'))]))
const runtimeTool = {
  name: 'ft_kline_runtime_status', description: 'Check runtime preparation. The complete tool catalog is already available; retry the requested tool when ready.',
  inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true },
}

export function clientMode(params = {}, configured = 'auto') {
  if (configured === 'desktop' || configured === 'cli') return configured
  if (configured !== 'auto') throw new Error('FT_KLINE_CLIENT must be auto, desktop or cli')
  const ui = params.capabilities?.extensions?.['io.modelcontextprotocol/ui']
  return ui && Array.isArray(ui.mimeTypes) && ui.mimeTypes.includes('text/html;profile=mcp-app') ? 'desktop' : 'cli'
}

// Match the Python resource using packaged assets only. Host preloading must
// not depend on Python readiness or on a later catalog refresh.
export function chartResource() {
  // Python read_text() uses universal newlines, including Windows checkouts.
  // Apply the same conversion so preloaded and backend resources stay identical.
  const readText = path => readFileSync(new URL(path, root), 'utf8').replace(/\r\n?/g, '\n')
  let html = readText('view/kline.html')
  const vendor = readText('view/vendor/klinecharts.min.js').replaceAll('</script>', '<\\/script>')
  html = html.replace('<script id="klinecharts-vendor" src="./vendor/klinecharts.min.js"></script>', `<script id="klinecharts-vendor">${vendor}</script>`)
  const logo = new URL('view/ft-logo.jpg', root)
  if (existsSync(logo)) html = html.replaceAll('__FTV_LOGO_DATA__', `data:image/jpeg;base64,${readFileSync(logo).toString('base64')}`)
  const version = JSON.parse(readFileSync(new URL('package.json', root), 'utf8')).version
  const bridge = catalogs.desktop.bridge.replaceAll('__FT_KLINE_VERSION__', version)
  const marker = 'init().catch((error) => {'
  if (!html.includes(marker)) throw new Error('Missing chart initialization point')
  html = html.replace(marker, 'window.__FT_KLINE_APP__.ready.then(() => init()).then(() => window.__FT_KLINE_APP__.mounted()).catch((error) => {')
  return html.replace('</head>', `${bridge}</head>`)
}

// Some hosts snapshot tools once. Publish one complete catalog throughout the
// connection instead of temporarily publishing only the preparation-status tool.
export function serve({ input = process.stdin, output = process.stdout, error = process.stderr,
  command = process.execPath, args, env = process.env, spawnServer = spawn, preparationWaitMs = 5000 } = {}) {
  const send = value => output.write(`${JSON.stringify(value)}\n`)
  const reply = (id, result) => send({ jsonrpc: '2.0', id, result })
  let child, initialized = false, ready = false, failed = false, closed = false, mode = 'cli'
  const pending = new Map()
  const status = () => ({ ok: !failed, phase: failed ? 'failed' : ready ? 'ready' : 'preparing', client: mode,
    retryable: !failed, message: failed ? 'Runtime preparation failed. Check ft-kline/bootstrap.log, correct the environment and reconnect.'
      : ready ? 'Runtime ready. Call analyze_kline directly; no tool-list refresh is needed.'
        : 'Preparing Python dependencies. The tool catalog is complete. Retry the requested tool after preparation; no chart operation has been dispatched.' })
  const unavailable = id => reply(id, { content: [{ type: 'text', text: status().message }],
    structuredContent: { ...status(), ok: false, error: failed ? 'runtime_unavailable' : 'runtime_preparing', operation_dispatched: false }, isError: true })
  const cancelPending = id => {
    const request = pending.get(id)
    if (request) { clearTimeout(request.timer); pending.delete(id) }
  }
  const fail = () => {
    failed = true; ready = false
    for (const id of pending.keys()) { cancelPending(id); unavailable(id) }
  }
  const forward = message => child.stdin.write(`${JSON.stringify(message)}\n`)
  const shutdown = () => {
    if (closed) return
    closed = true
    for (const id of pending.keys()) cancelPending(id)
    child?.kill()
    inputLines.close()
    process.removeListener('SIGTERM', shutdown)
    process.removeListener('SIGINT', shutdown)
  }
  const inputLines = createInterface({ input })
  inputLines.on('line', line => {
    let message
    try { message = JSON.parse(line) } catch { send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Invalid JSON' } }); return }
    if (!message || typeof message !== 'object' || Array.isArray(message) || message.jsonrpc !== '2.0') {
      send({ jsonrpc: '2.0', id: null, error: { code: -32600, message: 'Invalid JSON-RPC message' } }); return
    }
    if (message.method === 'initialize' && !initialized) {
      try { mode = clientMode(message.params, env.FT_KLINE_CLIENT || 'auto') }
      catch (e) { send({ jsonrpc: '2.0', id: message.id, error: { code: -32602, message: e.message } }); return }
      initialized = true
      reply(message.id, { protocolVersion: message.params?.protocolVersion || '2025-11-25',
        capabilities: { tools: { listChanged: false }, resources: { listChanged: false } },
        serverInfo: { name: 'ft-kline', version: catalogs[mode].version },
        instructions: `The complete FT K-Line tool catalog is available from startup. If a call reports runtime_preparing, retry that tool once ready; never report chart success or replay an unknown edit. No tools/list refresh is needed. ${catalogs[mode].instructions}` })
      try { child = spawnServer(command, args, { env: { ...env, FT_KLINE_CLIENT: mode }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true }) }
      catch { fail(); return }
      child.stderr.on('data', chunk => error.write(chunk))
      child.stdin.on('error', fail)
      child.on('error', fail)
      child.on('exit', fail)
      createInterface({ input: child.stdout }).on('line', response => {
        let value
        try { value = JSON.parse(response) } catch { return }
        if (value.id === 'ft-kline-bootstrap-initialize') {
          if (value.error) { fail(); return }
          forward({ jsonrpc: '2.0', method: 'notifications/initialized' })
          ready = true
          for (const [id, request] of pending) { cancelPending(id); forward(request.message) }
        } else if (!['notifications/tools/list_changed', 'notifications/resources/list_changed'].includes(value.method)) send(value)
      })
      forward({ ...message, id: 'ft-kline-bootstrap-initialize' })
      return
    }
    if (message.method === 'ping') { reply(message.id, {}); return }
    if (!initialized) { if (message.id != null) send({ jsonrpc: '2.0', id: message.id, error: { code: -32002, message: 'Initialize the server first' } }); return }
    if (message.method === 'tools/list') reply(message.id, { tools: [...catalogs[mode].tools, runtimeTool] })
    else if (message.method === 'resources/list') reply(message.id, { resources: catalogs[mode].resources })
    else if (message.method === 'resources/templates/list') reply(message.id, { resourceTemplates: [] })
    else if (message.method === 'resources/read') {
      const resource = catalogs[mode].resources.find(item => item.uri === message.params?.uri)
      if (!resource) { send({ jsonrpc: '2.0', id: message.id, error: { code: -32602, message: 'Unknown resource' } }); return }
      try { reply(message.id, { contents: [{ uri: resource.uri, mimeType: resource.mimeType, text: chartResource(), _meta: resource._meta }] }) }
      catch { send({ jsonrpc: '2.0', id: message.id, error: { code: -32603, message: 'Chart resource is unavailable' } }) }
    } else if (message.method === 'tools/call' && message.params?.name === runtimeTool.name) {
      reply(message.id, { content: [{ type: 'text', text: JSON.stringify(status()) }], structuredContent: status(), isError: failed })
    } else if (message.method === 'notifications/initialized') {
      // Initialize the child only after its own handshake completes.
    } else if (message.method === 'notifications/cancelled') {
      if (pending.has(message.params?.requestId)) cancelPending(message.params.requestId)
      else if (ready) forward(message)
    } else if (message.method === 'tools/call' && !catalogs[mode].tools.some(tool => tool.name === message.params?.name)) {
      send({ jsonrpc: '2.0', id: message.id, error: { code: -32602, message: 'Unknown tool for this host mode' } })
    } else if (ready) forward(message)
    else if (message.method === 'tools/call' && !failed) {
      if (pending.has(message.id)) return
      const timer = setTimeout(() => { pending.delete(message.id); unavailable(message.id) }, preparationWaitMs)
      pending.set(message.id, { message, timer })
    } else if (message.method === 'tools/call') unavailable(message.id)
    else if (message.id != null) send({ jsonrpc: '2.0', id: message.id, error: { code: -32601, message: 'Unsupported method' } })
  })
  inputLines.on('close', shutdown)
  process.on('SIGTERM', shutdown)
  process.on('SIGINT', shutdown)
  return { shutdown }
}
