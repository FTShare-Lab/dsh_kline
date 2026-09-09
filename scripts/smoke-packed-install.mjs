// Run after pnpm pack: node scripts/smoke-packed-install.mjs /absolute/package.tgz
// Does not use the developer's venv, FTShare key, or active Harness profile.
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { mkdtemp, mkdir, readFile, rename } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

const archive = resolve(process.argv[2] || '')
assert.ok(process.argv[2]?.endsWith('.tgz'), 'Supply the packed .tgz path')
const scratch = await mkdtemp(join(tmpdir(), 'dsh-kline-packed-'))
const root = join(scratch, 'profile 空格', 'node_modules', '@ftshare-lab', 'dsh-kline')
const extracted = join(scratch, 'extracted-package')
await mkdir(extracted, {recursive:true})
const entries = execFileSync('tar', ['-tzf', archive], {encoding:'utf8'}).trim().split('\n')
assert.ok(entries.every(path => !/( 2\.|\.runtime\/|\.venv\/|node_modules\/|credentials|\.env$)/.test(path)), 'Unexpected files in archive')
execFileSync('tar', ['-xzf', archive, '-C', extracted, '--strip-components=1'])
await mkdir(join(root, '..'), {recursive:true})
await rename(extracted, root)
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('FTSHARE_') && !key.startsWith('DSH_KLINE_')))
const runtime = join(scratch, '运行 runtime')
Object.assign(env, {DSH_KLINE_HOST_PID:String(process.pid), DSH_KLINE_CHART_PORT:'0',
  DSH_KLINE_VENV:join(scratch, 'fresh-venv'), DSH_KLINE_CACHE_DIR:join(scratch, 'cache'),
  DSH_KLINE_RUNTIME_DIR:runtime,
  FTSHARE_API_KEY_FILE:join(scratch, 'no-credentials.json')})
const stderr = createWriteStream(join(scratch, 'bootstrap.log'), {mode:0o600})
const child = spawn(process.execPath, ['scripts/run-dsh-kline.mjs'], {cwd:root, env, stdio:['pipe','pipe','pipe'], windowsHide:true})
const childExit = new Promise(resolveExit => child.once('exit', resolveExit))
child.stderr.pipe(stderr)
let stderrTail = ''
child.stderr.on('data', chunk => {
  stderrTail = (stderrTail + chunk.toString('utf8')).slice(-32_768)
})
const pending = new Map()
const lines = createInterface({input:child.stdout})
lines.on('line', line => {
  try {
    const message = JSON.parse(line)
    const entry = pending.get(message.id)
    if (entry) {pending.delete(message.id); clearTimeout(entry.timer); entry.resolve(message)}
  } catch { /* Only protocol responses can satisfy requests. */ }
})
child.on('exit', code => {
  const detail = stderrTail.trim() || '(bootstrap produced no stderr)'
  for (const entry of pending.values()) {
    clearTimeout(entry.timer)
    entry.reject(Error(`MCP exited (${code}); bootstrap log follows:\n${detail}`))
  }
  pending.clear()
})
let sequence = 0
const send = message => child.stdin.write(JSON.stringify({jsonrpc:'2.0', ...message}) + '\n')
const request = (method, params = {}, timeout = 120000) => new Promise((resolve, reject) => {
  const id = ++sequence
  const timer = setTimeout(() => {pending.delete(id); reject(Error(`${method} timed out; see ${scratch}/bootstrap.log`))}, timeout)
  pending.set(id, {resolve, reject, timer})
  send({id, method, params})
})
try {
  const init = await request('initialize', {protocolVersion:'2024-11-05', capabilities:{}, clientInfo:{name:'packed-install-smoke',version:'1'}}, 300000)
  assert.ok(init.result?.serverInfo)
  send({method:'notifications/initialized'})
  console.log('PASS first launch: fresh venv + native Node launcher + Unicode/space path')
  const list = await request('tools/list')
  assert.equal(list.result?.tools.length, 9)
  console.log('PASS MCP initialize + 9 tools')
  const candles = await request('tools/call', {name:'fetch_candles', arguments:{symbol:'000001.XSHG', interval:'day',limit:10}})
  assert.equal(candles.result?.isError ?? false, false)
  const payload = candles.result?.structuredContent
  assert.ok(payload?.ok && payload.rows?.length > 0, 'Anonymous index candles unavailable')
  console.log(`PASS anonymous index candles: ${payload.rows.length} bars`)
  const locator = JSON.parse(await readFile(join(runtime, 'services',`${process.pid}.json`), 'utf8'))
  assert.equal(locator.host_process_id, process.pid)
  assert.ok(Number.isSafeInteger(locator.process_id) && locator.process_id > 0)
  const health = await fetch(`${locator.service_url}/healthz`)
  assert.equal(health.status, 200)
  const denied = await fetch(`${locator.service_url}/api/tools/data_source_status`, {method:'POST',body:'{}'})
  assert.equal(denied.status, 401)
  console.log('PASS host-scoped locator + HTTP health + unauthenticated access denied')
  console.log(`Test artifacts retained in ${scratch}`)
} finally {
  lines.close()
  for (const entry of pending.values()) clearTimeout(entry.timer)
  if (child.exitCode === null) {
    child.stdin.end()
    const force = setTimeout(() => {try {child.kill('SIGTERM')} catch {}}, 3000)
    await childExit
    clearTimeout(force)
  }
  stderr.end()
}
