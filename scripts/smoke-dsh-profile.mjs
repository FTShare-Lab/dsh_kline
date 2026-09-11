// Installs the packed plugin into an isolated DSH profile, boots DSH Web, and
// verifies that the bundle patch starts the MCP/chart service successfully.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const project = resolve(fileURLToPath(new URL('..', import.meta.url)))
const archive = resolve(process.argv[2] || '')
assert.ok(process.argv[2]?.endsWith('.tgz'), 'Supply the packed .tgz path')
const dshBin = join(project, 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js')
const scratch = await mkdtemp(join(tmpdir(), 'dsh-kline-host-'))
const dshHome = join(scratch, 'DSH profile 空格')
const runtime = join(scratch, '运行 runtime')
const cache = join(scratch, '用户 cache')
await mkdir(dshHome, { recursive: true })
const env = {
  ...process.env,
  DSH_HOME: dshHome,
  DSH_KLINE_CACHE_DIR: cache,
  DSH_KLINE_RUNTIME_DIR: runtime,
  DSH_KLINE_CHART_PORT: '0',
  // The isolated profile lives under a temporary path without a package.json;
  // prevent Corepack from trying to mutate /tmp/package.json while forwarding
  // the plugin install to pnpm.
  COREPACK_ENABLE_PROJECT_SPEC: '0',
  FTSHARE_API_KEY: '',
  FTSHARE_API_KEY_FILE: join(scratch, 'no-credentials.json'),
}

const install = spawnSync(process.execPath, [dshBin, 'plugin', '--profile', 'web', 'add', archive], {
  cwd: project,
  env,
  encoding: 'utf8',
  timeout: 120_000,
  windowsHide: true,
})
assert.equal(install.status, 0, `isolated DSH plugin install failed:\n${install.stderr}`)

const child = spawn(process.execPath, [dshBin, '--profile', 'web', '--no-open', '--port', '0'], {
  cwd: project,
  env,
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
})
let output = ''
let errors = ''
child.stdout.on('data', chunk => { output += chunk.toString() })
child.stderr.on('data', chunk => { errors += chunk.toString() })
const exited = new Promise(resolveExit => child.once('exit', (code, signal) => resolveExit({ code, signal })))

function scrub(text) {
  return text.replace(/([?&]token=)[^\s]+/g, '$1[redacted]')
}

async function waitUntilReady() {
  const deadline = Date.now() + 300_000
  while (Date.now() < deadline) {
    if (output.includes('dsh web: http://')) return
    if (child.exitCode !== null) throw new Error(`DSH exited before ready (${child.exitCode}):\n${scrub(errors)}`)
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100))
  }
  throw new Error(`DSH startup timed out:\n${scrub(errors)}`)
}

async function waitForServiceLocator() {
  const deadline = Date.now() + 300_000
  const serviceDirectory = join(runtime, 'services')
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`DSH exited before the MCP service became ready (${child.exitCode}):\n${scrub(errors)}`)
    try {
      const services = (await readdir(serviceDirectory)).filter(name => name.endsWith('.json'))
      if (services.length === 1) {
        const locator = JSON.parse(await readFile(join(serviceDirectory, services[0]), 'utf8'))
        const health = await fetch(`${locator.service_url}/healthz`).catch(() => null)
        if (health?.status === 200) return { serviceDirectory, services, locator }
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100))
  }
  throw new Error(`MCP service did not become ready:\n${scrub(errors)}`)
}

try {
  await waitUntilReady()
  const { services, locator } = await waitForServiceLocator()
  assert.equal(services.length, 1, `expected one MCP service locator, got ${services.length}`)
  assert.equal(locator.ok, true)
  assert.ok(Number.isSafeInteger(locator.process_id) && locator.process_id > 0)
  console.log('PASS isolated DSH Web install + bundle patch + MCP/chart startup')
} finally {
  if (child.exitCode === null) child.kill()
  await Promise.race([exited, new Promise(resolveDelay => setTimeout(resolveDelay, 5000))])
  await rm(scratch, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }).catch(() => {})
}
