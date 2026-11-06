// Keep the host's MCP connection alive while Python is prepared or restarted.
// No deferred/expired call or in-flight operation is replayed after a failure.
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import { readFileSync, mkdirSync, writeFileSync, renameSync, appendFileSync, statSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { defaultStateDirectory } from './run-dsh-kline.mjs'

const catalog = JSON.parse(readFileSync(new URL('../config/dsh-tool-catalog.json', import.meta.url), 'utf8'))
const runtimeTool = { name: 'dsh_kline_runtime_status', description: 'Check Python preparation or recovery. The complete tool catalog is available from startup; retry the requested tool when ready. Never replay an operation with an unknown outcome.',
  inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true } }

export function serve({ input = process.stdin, output = process.stdout, error = process.stderr,
  command = process.execPath, args, env = process.env, spawnServer = spawn,
  preparationWaitMs = 5000, retryDelayMs = 1000, maxRetryDelayMs = 30000, handshakeTimeoutMs = 20 * 60 * 1000 } = {}) {
  const hostPid = /^[1-9]\d*$/.test(env.DSH_KLINE_HOST_PID || '') ? env.DSH_KLINE_HOST_PID : String(process.ppid)
  const directory = join(defaultStateDirectory(env), 'logs')
  const logPath = join(directory, `backend-${hostPid}.log`)
  const statusPath = join(directory, `backend-${hostPid}.json`)
  let child, lines, init, retryTimer, handshakeTimer, closed = false, ready = false, failures = 0, lastError
  const queued = new Map(), inFlight = new Map()
  const send = value => { if (!closed) output.write(`${JSON.stringify(value)}\n`) }
  const reply = (id, result) => send({ jsonrpc: '2.0', id, result })
  const protocolError = (id, code, message) => send({ jsonrpc: '2.0', id, error: { code, message } })
  const status = () => ({ ok: ready, phase: ready ? 'ready' : lastError ? 'recovering' : 'preparing',
    error: ready ? undefined : lastError || 'runtime_preparing', retryable: !closed,
    host_process_id: Number(hostPid), launcher_process_id: process.pid, log_path: logPath })
  const persist = () => {
    try {
      mkdirSync(directory, { recursive: true, mode: 0o700 })
      const temporary = `${statusPath}.${process.pid}.tmp`
      writeFileSync(temporary, JSON.stringify({ ...status(), updated_at: Date.now() }), { mode: 0o600 })
      renameSync(temporary, statusPath)
    } catch { /* A diagnostic failure must not close the protocol connection. */ }
  }
  const log = chunk => {
    error.write(chunk)
    try {
      mkdirSync(directory, { recursive: true, mode: 0o700 })
      try { if (statSync(logPath).size + Buffer.byteLength(chunk) > 1024 * 1024) { rmSync(`${logPath}.previous`, {force:true}); renameSync(logPath, `${logPath}.previous`) } } catch {}
      appendFileSync(logPath, chunk, { mode: 0o600 })
    } catch { /* stderr remains available when the cache is not writable. */ }
  }
  const unavailable = (id, dispatched = false) => reply(id, {
    content: [{ type: 'text', text: dispatched
      ? '后端连接中断，操作结果未知。请先核对当前状态，不要自动重放操作。'
      : ready ? '后端已恢复，请重新发起操作。' : 'Python 正在准备或恢复。此操作尚未执行，请就绪后重试。' }],
    structuredContent: { ...status(), ok: false, error: dispatched ? 'runtime_connection_lost' : lastError || 'runtime_preparing',
      operation_dispatched: dispatched, outcome_unknown: dispatched }, isError: true,
  })
  const cancelQueued = id => {
    const item = queued.get(id)
    if (item) { clearTimeout(item.timer); queued.delete(id) }
  }
  const forward = message => {
    if (message.id != null && message.method) inFlight.set(message.id, message)
    child.stdin.write(`${JSON.stringify(message)}\n`)
  }
  const terminate = generation => {
    generation.stdin.destroy()
    if (!generation.pid) { generation.kill(); return }
    if (process.platform === 'win32') {
      // Terminate the owned install/backend tree, including pip children. A
      // parent-only kill can leave an installer racing the next activation.
      const killer = spawn('taskkill', ['/pid', String(generation.pid), '/T', '/F'], {stdio:'ignore', windowsHide:true})
      killer.on('error', () => generation.kill())
    } else {
      // spawn(detached) below gives this generation its own process group.
      try { process.kill(-generation.pid, 'SIGTERM') } catch { generation.kill() }
    }
  }
  const down = (generation, reason) => {
    if (closed || child !== generation) return
    ready = false; child = undefined; lastError = reason
    clearTimeout(handshakeTimer)
    lines?.close()
    terminate(generation)
    for (const [id, message] of inFlight) {
      if (message.method === 'tools/call') unavailable(id, true)
      else protocolError(id, -32603, 'Backend connection lost; request was not replayed')
    }
    inFlight.clear()
    for (const id of queued.keys()) { cancelQueued(id); unavailable(id) }
    failures += 1
    const wait = Math.min(maxRetryDelayMs, retryDelayMs * 2 ** Math.min(failures - 1, 10))
    log(`[dsh_kline] ${reason}; retrying backend in ${wait}ms; MCP connection retained.\n`)
    persist()
    // Wait for this generation to exit before starting another Python owner.
    const schedule = () => {
      if (!closed && !retryTimer) retryTimer = setTimeout(() => { retryTimer = undefined; start() }, wait)
    }
    if (generation.exitCode != null || generation.signalCode != null || !generation.pid) schedule()
    else generation.once('exit', schedule)
  }
  const start = () => {
    if (closed || child) return
    let generation
    try { generation = spawnServer(command, args, { env: { ...env, DSH_KLINE_DEFER_BOOTSTRAP: '0' }, stdio: ['pipe', 'pipe', 'pipe'], detached:process.platform !== 'win32', windowsHide: true }) }
    catch {
      lastError = 'backend_spawn_failed'; failures += 1; log('[dsh_kline] backend_spawn_failed; MCP connection retained.\n'); persist()
      retryTimer = setTimeout(() => { retryTimer = undefined; start() }, Math.min(maxRetryDelayMs, retryDelayMs * 2 ** Math.min(failures - 1, 10)))
      return
    }
    child = generation; persist()
    generation.stderr.on('data', log)
    generation.stdin.on('error', () => down(generation, 'backend_pipe_failed'))
    generation.on('error', () => down(generation, 'backend_spawn_failed'))
    generation.on('exit', (code, signal) => {
      if (child === generation && !closed) log(`[dsh_kline] Backend exited code=${code} signal=${signal || 'none'}.\n`)
      down(generation, 'backend_exited')
    })
    lines = createInterface({ input: generation.stdout })
    lines.on('line', line => {
      if (child !== generation || closed) return
      let value
      try { value = JSON.parse(line) } catch { log('[dsh_kline] Ignored non-protocol backend stdout.\n'); return }
      if (!value || typeof value !== 'object' || Array.isArray(value) || value.jsonrpc !== '2.0') {
        log('[dsh_kline] Ignored invalid backend protocol frame.\n'); return
      }
      if (!ready && value.id === 'dsh-kline-bootstrap-initialize') {
        if (value.error || !value.result) { down(generation, 'backend_initialize_failed'); return }
        clearTimeout(handshakeTimer)
        forward({ jsonrpc: '2.0', method: 'notifications/initialized' })
        ready = true; lastError = undefined; failures = 0; persist()
        for (const [id, request] of queued) { cancelQueued(id); forward(request.message) }
      } else if (!['notifications/tools/list_changed', 'notifications/resources/list_changed'].includes(value.method)) {
        if (!value.method) inFlight.delete(value.id)
        send(value)
      }
    })
    handshakeTimer = setTimeout(() => down(generation, 'backend_initialize_timeout'), handshakeTimeoutMs)
    forward({ ...init, id: 'dsh-kline-bootstrap-initialize' })
    inFlight.delete('dsh-kline-bootstrap-initialize')
  }
  const shutdown = () => {
    if (closed) return
    closed = true; ready = false
    clearTimeout(retryTimer); clearTimeout(handshakeTimer)
    for (const id of queued.keys()) cancelQueued(id)
    inFlight.clear()
    if (child) terminate(child)
    lines?.close(); inputLines.close()
    process.removeListener('SIGTERM', shutdown); process.removeListener('SIGINT', shutdown)
  }
  const inputLines = createInterface({ input })
  inputLines.on('line', line => {
    let message
    try { message = JSON.parse(line) } catch { protocolError(null, -32700, 'Invalid JSON'); return }
    if (!message || typeof message !== 'object' || Array.isArray(message) || message.jsonrpc !== '2.0') { protocolError(null, -32600, 'Invalid JSON-RPC message'); return }
    if (message.method === 'initialize' && !init) {
      init = message
      reply(message.id, { protocolVersion: message.params?.protocolVersion || '2024-11-05',
        capabilities: { tools: { listChanged: false } }, serverInfo: { name: 'dsh_kline', version: catalog.version },
        instructions: `${catalog.instructions}\nThe complete tool catalog is available during preparation. Retry calls reporting runtime_preparing only after readiness; never replay operations with unknown outcomes.` })
      start(); return
    }
    if (message.method === 'ping') { reply(message.id, {}); return }
    if (!init) { if (message.id != null) protocolError(message.id, -32002, 'Initialize the server first'); return }
    if (message.method === 'tools/list') reply(message.id, { tools: [...catalog.tools, runtimeTool] })
    else if (message.method === 'resources/list') reply(message.id, { resources: [] })
    else if (message.method === 'resources/templates/list') reply(message.id, { resourceTemplates: [] })
    else if (message.method === 'tools/call' && message.params?.name === runtimeTool.name) {
      reply(message.id, { content: [{ type: 'text', text: JSON.stringify(status()) }], structuredContent: status(), isError: false })
    } else if (message.method === 'notifications/initialized') { /* Child has its own handshake. */ }
    else if (message.method === 'notifications/cancelled') {
      if (queued.has(message.params?.requestId)) cancelQueued(message.params.requestId)
      else if (ready) { inFlight.delete(message.params?.requestId); forward(message) }
    } else if (message.method === 'tools/call' && !catalog.tools.some(tool => tool.name === message.params?.name)) protocolError(message.id, -32602, 'Unknown tool')
    else if (ready) forward(message)
    else if (message.method === 'tools/call') {
      if (queued.has(message.id)) return
      const timer = setTimeout(() => { queued.delete(message.id); unavailable(message.id) }, preparationWaitMs)
      queued.set(message.id, { message, timer })
    } else if (message.id != null) protocolError(message.id, -32002, 'Python backend is preparing or recovering')
  })
  inputLines.on('close', shutdown)
  process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown)
  return { shutdown }
}
