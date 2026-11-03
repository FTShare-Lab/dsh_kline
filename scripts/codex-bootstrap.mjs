import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

export function clientMode(params = {}, configured = 'auto') {
  if (configured === 'desktop' || configured === 'cli') return configured
  if (configured !== 'auto') throw new Error('FT_KLINE_CLIENT must be auto, desktop or cli')
  const ui = params.capabilities?.extensions?.['io.modelcontextprotocol/ui']
  return ui && Array.isArray(ui.mimeTypes) && ui.mimeTypes.includes('text/html;profile=mcp-app') ? 'desktop' : 'cli'
}

// This front door needs only Node. Python installation never blocks the MCP
// handshake or catalog: a small status tool is replaced with the real catalog
// on the same connection once the Python server has initialized.
export function serve({ input = process.stdin, output = process.stdout, error = process.stderr,
  command = process.execPath, args, env = process.env, spawnServer = spawn } = {}) {
  const send = value => output.write(`${JSON.stringify(value)}\n`)
  const reply = (id, result) => send({ jsonrpc: '2.0', id, result })
  const instructions = 'FT K-Line prepares its Python runtime automatically. While preparing, call ft_kline_runtime_status; do not report chart success. When ready, refresh tools/list on this same connection. Hosts advertising the MCP Apps HTML capability get interactive charts; other hosts get analysis only. For chart edits use get_chart_context -> prepare_chart_edit -> apply_chart_edit -> get_chart_edit_status. Candidates are read-only until the user explicitly selects one: preserve candidate_result_ref and candidate_number and set user_confirmed_candidate=true. Prepare separate drawings separately. Server commit, UI receipt and pixel verification are distinct. Never expose credentials or use a context_ref from another conversation.'
  let child, initialized = false, ready = false, failed = false, closed = false, mode = 'cli'
  const shutdown = () => {
    if (closed) return
    closed = true
    child?.kill()
    inputLines.close()
    process.removeListener('SIGTERM', shutdown)
    process.removeListener('SIGINT', shutdown)
  }
  const status = () => ({ ok: !failed, phase: failed ? 'failed' : ready ? 'ready' : 'preparing', client: mode,
    retryable: !failed, message: failed ? 'Runtime preparation failed. Check the private ft-kline/bootstrap.log and retry the connection after correcting the environment.'
      : ready ? 'Runtime ready. Refresh tools/list on this connection.' : 'Preparing Python dependencies automatically. Check this status again; chart tools appear when ready.' })
  const forward = message => child.stdin.write(`${JSON.stringify(message)}\n`)
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
        capabilities: { tools: { listChanged: true }, resources: { listChanged: true } },
        serverInfo: { name: 'ft-kline', version: env.FT_KLINE_VERSION || '0.6.1' }, instructions })
      try {
        child = spawnServer(command, args, { env: { ...env, FT_KLINE_CLIENT: mode }, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true })
      } catch { failed = true; return }
      child.stderr.on('data', chunk => error.write(chunk))
      child.stdin.on('error', () => { failed = true; ready = false })
      child.on('error', () => { failed = true; ready = false })
      child.on('exit', () => { failed = true; ready = false })
      createInterface({ input: child.stdout }).on('line', response => {
        let value
        try { value = JSON.parse(response) } catch { return }
        if (value.id === 'ft-kline-bootstrap-initialize') {
          if (value.error) { failed = true; return }
          forward({ jsonrpc: '2.0', method: 'notifications/initialized' })
          ready = true
          send({ jsonrpc: '2.0', method: 'notifications/tools/list_changed' })
          if (mode === 'desktop') send({ jsonrpc: '2.0', method: 'notifications/resources/list_changed' })
        } else send(value)
      })
      forward({ ...message, id: 'ft-kline-bootstrap-initialize' })
      return
    }
    if (message.method === 'tools/call' && message.params?.name === 'ft_kline_runtime_status') {
      reply(message.id, { content: [{ type: 'text', text: JSON.stringify(status()) }], structuredContent: status(), isError: failed })
    } else if (message.method === 'notifications/initialized') {
      // The front door initializes the child after its own handshake completes.
    } else if (ready) forward(message)
    else if (message.method === 'tools/list') reply(message.id, { tools: [{ name: 'ft_kline_runtime_status',
      description: 'Check automatic runtime preparation. When ready, refresh tools/list on this connection.',
      inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true } }] })
    else if (['resources/list', 'resources/templates/list'].includes(message.method)) reply(message.id, message.method === 'resources/list' ? { resources: [] } : { resourceTemplates: [] })
    else if (message.method === 'ping') reply(message.id, {})
    else if (message.id != null) send({ jsonrpc: '2.0', id: message.id, error: { code: -32002, message: status().message } })
  })
  inputLines.on('close', shutdown)
  process.on('SIGTERM', shutdown)
  process.on('SIGINT', shutdown)
  return { shutdown }
}
