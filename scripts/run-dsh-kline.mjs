#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { access, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, posix, resolve, win32 } from 'node:path'
import { fileURLToPath } from 'node:url'

const PROJECT_ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)))
const REQUIREMENTS_FILE = join(PROJECT_ROOT, 'requirements.txt')
const IMPORT_CHECK = 'import ftshare, mcp, pydantic, pydantic_settings'
const VERSION_CHECK = 'import sys; raise SystemExit(sys.version_info < (3, 10))'
const REQUIREMENTS_STAMP = '.dsh-kline-requirements'
const BOOTSTRAP_FAILURE = '.dsh-kline-bootstrap-failed'
const BOOTSTRAP_RUNNING = '.dsh-kline-bootstrap-running'
const BACKGROUND_BOOTSTRAP_STALE_MS = 10 * 60 * 1000

export function pythonPathForVenv(venvDirectory, platform = process.platform) {
  const paths = platform === 'win32' ? win32 : posix
  return platform === 'win32'
    ? paths.join(venvDirectory, 'Scripts', 'python.exe')
    : paths.join(venvDirectory, 'bin', 'python')
}

export function defaultStateDirectory(env = process.env, platform = process.platform, userHome = homedir()) {
  const paths = platform === 'win32' ? win32 : posix
  const explicit = String(env.DSH_KLINE_CACHE_DIR || '').trim()
  if (explicit) return paths.resolve(explicit)
  if (platform === 'win32') {
    const local = String(env.LOCALAPPDATA || env.APPDATA || '').trim()
    return paths.join(local || paths.join(userHome, 'AppData', 'Local'), 'dsh_kline')
  }
  const cache = String(env.XDG_CACHE_HOME || '').trim()
  return paths.join(cache || paths.join(userHome, '.cache'), 'dsh_kline')
}

export function defaultRuntimeDirectory(env = process.env, platform = process.platform, userHome = homedir()) {
  const paths = platform === 'win32' ? win32 : posix
  const explicit = String(env.DSH_KLINE_RUNTIME_DIR || '').trim()
  return explicit ? paths.resolve(explicit) : paths.join(defaultStateDirectory(env, platform, userHome), 'runtime')
}

export function pythonCandidates(env = process.env, platform = process.platform) {
  const explicit = String(env.DSH_KLINE_PYTHON || '').trim()
  if (explicit) return [{ command: explicit, args: [] }]
  if (platform === 'win32') {
    return [
      ...['3.13', '3.12', '3.11', '3.10'].map(version => ({ command: 'py', args: [`-${version}`] })),
      { command: 'python', args: [] },
      { command: 'python3', args: [] },
    ]
  }
  return [
    'python3', 'python3.13', 'python3.12', 'python3.11', 'python3.10',
    '/opt/homebrew/bin/python3', '/opt/homebrew/bin/python3.13', '/opt/homebrew/bin/python3.12',
    '/opt/homebrew/bin/python3.11', '/opt/homebrew/bin/python3.10',
    '/usr/local/bin/python3', '/usr/local/bin/python3.13', '/usr/local/bin/python3.12',
    '/usr/local/bin/python3.11', '/usr/local/bin/python3.10',
    join(homedir(), 'miniforge3', 'bin', 'python'),
    join(homedir(), 'Caskroom', 'miniforge', 'base', 'bin', 'python3'),
    '/opt/homebrew/Caskroom/miniforge/base/bin/python3',
    join(homedir(), 'miniconda3', 'bin', 'python'),
    join(homedir(), 'anaconda3', 'bin', 'python'),
  ].map(command => ({ command, args: [] }))
}

export function pythonEnvironment(env = process.env) {
  return {
    ...env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PIP_PROGRESS_BAR: 'off',
    PIP_DISABLE_PIP_VERSION_CHECK: '1',
    PIP_NO_INPUT: '1',
  }
}

function commandPasses(command, args, code) {
  const result = spawnSync(command, [...args, '-c', code], {
    env: pythonEnvironment(),
    encoding: 'utf8',
    stdio: 'ignore',
    timeout: 10_000,
    windowsHide: true,
  })
  return result.status === 0
}

async function pathExists(path) {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

async function requirementsFingerprint() {
  return createHash('sha256').update(await readFile(REQUIREMENTS_FILE)).digest('hex')
}

async function stampMatches(venvDirectory, fingerprint) {
  try {
    return (await readFile(join(venvDirectory, REQUIREMENTS_STAMP), 'utf8')).trim() === fingerprint
  } catch {
    return false
  }
}

async function writeStamp(venvDirectory, fingerprint) {
  const destination = join(venvDirectory, REQUIREMENTS_STAMP)
  const temporary = `${destination}.${process.pid}.tmp`
  await writeFile(temporary, `${fingerprint}\n`, { encoding: 'utf8', mode: 0o600 })
  try {
    await replaceWithRetry(temporary, destination)
  } finally {
    await rm(temporary, { force: true })
  }
}

async function replaceWithRetry(source, destination) {
  const attempts = process.platform === 'win32' ? 6 : 1
  let lastError
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      await rename(source, destination)
      return
    } catch (error) {
      lastError = error
      if (process.platform !== 'win32' || !['EACCES', 'EPERM', 'EEXIST'].includes(error?.code) || attempt + 1 === attempts) break
      await rm(destination, { force: true }).catch(() => {})
      await new Promise(resolveDelay => setTimeout(resolveDelay, 40 * (attempt + 1)))
    }
  }
  throw lastError
}

export function backgroundBootstrapSpawnOptions(platform = process.platform, env = process.env) {
  return {
    cwd: PROJECT_ROOT,
    env,
    // The bootstrap must outlive the short-lived MCP handshake process on
    // every host. On Windows, `unref()` alone does not detach a child from
    // the parent's process group/job, so the child can be reaped as soon as
    // the initial MCP attempt exits.
    detached: true,
    stdio: 'ignore',
    windowsHide: platform === 'win32',
  }
}

function findBootstrapPython(preferred = '') {
  const candidates = preferred
    ? [{ command: preferred, args: [] }, ...pythonCandidates()]
    : pythonCandidates()
  const seen = new Set()
  for (const candidate of candidates) {
    const key = `${candidate.command}\u0000${candidate.args.join('\u0000')}`
    if (seen.has(key)) continue
    seen.add(key)
    if (commandPasses(candidate.command, candidate.args, VERSION_CHECK)) return candidate
  }
  const hint = process.platform === 'win32'
    ? 'Install Python 3.10 or newer from python.org, enable the Python Launcher, or set DSH_KLINE_PYTHON.'
    : 'Install Python 3.10 or newer, or set DSH_KLINE_PYTHON to its executable.'
  throw new Error(`dsh_kline requires Python 3.10 or newer. ${hint}`)
}

async function runLogged(command, args, logPath) {
  const startedAt = Date.now()
  await mkdir(dirname(logPath), { recursive: true })
  const log = createWriteStream(logPath, { flags: 'a', mode: 0o600 })
  return await new Promise((resolveRun, rejectRun) => {
    let settled = false
    const child = spawn(command, args, {
      cwd: PROJECT_ROOT,
      env: pythonEnvironment(),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    const forward = chunk => {
      process.stderr.write(chunk)
      log.write(chunk)
    }
    child.stdout.on('data', forward)
    child.stderr.on('data', forward)
    child.once('error', error => {
      if (settled) return
      settled = true
      log.end()
      rejectRun(error)
    })
    child.once('close', code => {
      if (settled) return
      settled = true
      log.end()
      if (code === 0) resolveRun(Date.now() - startedAt)
      else rejectRun(new Error(`${command} exited with code ${code}`))
    })
  })
}

async function prepareRuntime(venvDirectory, fingerprint, logPath, preferredPython = '') {
  const base = findBootstrapPython(preferredPython)
  await mkdir(dirname(venvDirectory), { recursive: true })
  await mkdir(dirname(logPath), { recursive: true })
  await writeFile(logPath, '', { encoding: 'utf8', mode: 0o600 })
  process.stderr.write('[dsh_kline] Creating or repairing the Python environment…\n')
  const venvMs = await runLogged(base.command, [...base.args, '-m', 'venv', venvDirectory], logPath)
  process.stderr.write(`[dsh_kline] Python environment ready in ${Math.ceil(venvMs / 1000)}s.\n`)
  const runtimePython = pythonPathForVenv(venvDirectory)
  process.stderr.write('[dsh_kline] Installing dependencies…\n')
  const dependenciesMs = await runLogged(runtimePython, ['-m', 'pip', 'install', '-r', REQUIREMENTS_FILE], logPath)
  process.stderr.write(`[dsh_kline] Dependencies ready in ${Math.ceil(dependenciesMs / 1000)}s.\n`)
  process.stderr.write('[dsh_kline] Verifying the runtime…\n')
  await runLogged(runtimePython, ['-c', IMPORT_CHECK], logPath)
  await writeStamp(venvDirectory, fingerprint)
  await rm(join(venvDirectory, BOOTSTRAP_FAILURE), { force: true })
  if (!(await stampMatches(venvDirectory, fingerprint))) {
    throw new Error('Dependency fingerprint was not persisted; refusing to report a ready runtime.')
  }
  process.stderr.write('[dsh_kline] Dependency fingerprint saved.\n')
  return runtimePython
}

async function readBootstrapFailure(venvDirectory, fingerprint) {
  try {
    const failure = JSON.parse(await readFile(join(venvDirectory, BOOTSTRAP_FAILURE), 'utf8'))
    return failure?.fingerprint === fingerprint ? failure : null
  } catch {
    return null
  }
}

async function writeBootstrapFailure(venvDirectory, fingerprint, error) {
  await mkdir(venvDirectory, { recursive: true })
  await writeFile(join(venvDirectory, BOOTSTRAP_FAILURE), JSON.stringify({ fingerprint, at: new Date().toISOString(), error: String(error) }), { encoding: 'utf8', mode: 0o600 })
}

function processIsAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error?.code === 'EPERM'
  }
}

async function readBootstrapMarker(marker) {
  try {
    const details = JSON.parse(await readFile(marker, 'utf8'))
    return details && typeof details === 'object' ? details : null
  } catch {
    return null
  }
}

async function writeBootstrapMarker(marker, details) {
  const temporary = `${marker}.${process.pid}.tmp`
  await writeFile(temporary, JSON.stringify(details), { encoding: 'utf8', mode: 0o600 })
  try {
    await replaceWithRetry(temporary, marker)
  } finally {
    await rm(temporary, { force: true })
  }
}

async function clearBootstrapMarker(venvDirectory, expectedPid = process.pid) {
  const marker = join(venvDirectory, BOOTSTRAP_RUNNING)
  const details = await readBootstrapMarker(marker)
  if (details && Number(details.pid) !== expectedPid) return
  await rm(marker, { force: true }).catch(() => {})
}

async function bootstrapIsRunning(venvDirectory) {
  const marker = join(venvDirectory, BOOTSTRAP_RUNNING)
  const details = await readBootstrapMarker(marker)
  const pid = Number(details?.pid)
  if (processIsAlive(pid)) return true
  const startedAt = Date.parse(details?.started_at || '')
  // Older markers did not carry a PID. Keep their short grace period for
  // upgrade compatibility, but remove markers whose owner is definitely
  // gone instead of blocking reconnect forever after a killed child.
  if (!Number.isSafeInteger(pid) && Number.isFinite(startedAt) && Date.now() - startedAt < BACKGROUND_BOOTSTRAP_STALE_MS) return true
  await rm(marker, { force: true }).catch(() => {})
  return false
}

async function startBackgroundBootstrap(venvDirectory) {
  if (await bootstrapIsRunning(venvDirectory)) return false
  await mkdir(venvDirectory, { recursive: true })
  const marker = join(venvDirectory, BOOTSTRAP_RUNNING)
  const startedAt = new Date().toISOString()
  try {
    // Reserve the marker before spawning so concurrent reconnect attempts do
    // not launch duplicate dependency installers.
    await writeFile(marker, JSON.stringify({ pid: process.pid, started_at: startedAt }), {
      encoding: 'utf8', mode: 0o600, flag: 'wx',
    })
  } catch (error) {
    if (error?.code === 'EEXIST') return false
    throw error
  }
  let child
  try {
    child = spawn(process.execPath, [fileURLToPath(import.meta.url), '--bootstrap-runtime'], backgroundBootstrapSpawnOptions())
    child.once('error', () => { void clearBootstrapMarker(venvDirectory, child?.pid || process.pid) })
    child.once('exit', () => { void clearBootstrapMarker(venvDirectory, child?.pid || process.pid) })
    await writeBootstrapMarker(marker, { pid: child.pid, started_at: startedAt })
    child.unref()
    return true
  } catch (error) {
    if (child && child.exitCode === null) child.kill()
    await clearBootstrapMarker(venvDirectory, child?.pid || process.pid)
    throw error
  }
}

async function launchServer(runtimePython, runtimeDirectory) {
  await mkdir(runtimeDirectory, { recursive: true })
  const child = spawn(runtimePython, [join(PROJECT_ROOT, 'server.py')], {
    cwd: PROJECT_ROOT,
    env: pythonEnvironment({ ...process.env, DSH_KLINE_RUNTIME_DIR: runtimeDirectory }),
    stdio: 'inherit',
    windowsHide: true,
  })
  const forwardSignal = () => {
    if (child.exitCode === null && child.signalCode === null) child.kill()
  }
  process.once('SIGINT', forwardSignal)
  process.once('SIGTERM', forwardSignal)
  const result = await new Promise((resolveExit, rejectExit) => {
    child.once('error', rejectExit)
    child.once('exit', (code, signal) => resolveExit({ code, signal }))
  })
  process.removeListener('SIGINT', forwardSignal)
  process.removeListener('SIGTERM', forwardSignal)
  if (result.signal) return 1
  return result.code ?? 1
}

export async function main(argv = process.argv.slice(2)) {
  const prepareProject = argv.includes('--prepare-project')
  const bootstrapRuntime = argv.includes('--bootstrap-runtime')
  const stateDirectory = defaultStateDirectory()
  const runtimeDirectory = defaultRuntimeDirectory()
  const configuredVenv = String(process.env.DSH_KLINE_VENV || '').trim()
  const configuredPython = String(process.env.DSH_KLINE_PYTHON || '').trim()
  const projectVenv = join(PROJECT_ROOT, '.venv')
  const projectPython = pythonPathForVenv(projectVenv)
  const hasProjectRuntime = await pathExists(projectPython)
  const configuredPythonWorks = !prepareProject && !configuredVenv && Boolean(configuredPython)
    && commandPasses(configuredPython, [], VERSION_CHECK)
    && commandPasses(configuredPython, [], IMPORT_CHECK)
  const venvDirectory = prepareProject
    ? projectVenv
    : configuredVenv || (hasProjectRuntime ? projectVenv : join(stateDirectory, 'venv'))
  const managedRuntime = !configuredPythonWorks && (prepareProject || Boolean(configuredVenv) || !hasProjectRuntime)
  let runtimePython = configuredPythonWorks ? configuredPython : pythonPathForVenv(venvDirectory)
  const fingerprint = await requirementsFingerprint()
  const runtimeWorks = await pathExists(runtimePython) && commandPasses(runtimePython, [], IMPORT_CHECK)
  let reason = ''
  if (!runtimeWorks) reason = 'Python runtime is missing or incomplete'
  else if (managedRuntime && !(await stampMatches(venvDirectory, fingerprint))) reason = 'dependency requirements changed'

  if (reason) {
    if (!managedRuntime) {
      throw new Error('The project .venv is incomplete. Run: pnpm bootstrap')
    }
    const previousFailure = await readBootstrapFailure(venvDirectory, fingerprint)
    if (previousFailure && !prepareProject) {
      throw new Error(`Python runtime preparation previously failed for these dependencies. Run: pnpm bootstrap and inspect the bootstrap log.`)
    }
    const deferredBootstrap = String(process.env.DSH_KLINE_DEFER_BOOTSTRAP || '').trim() === '1'
    if (deferredBootstrap && !prepareProject && !bootstrapRuntime) {
      const started = await startBackgroundBootstrap(venvDirectory)
      const state = started ? 'started' : 'is already running'
      throw new Error(`Python runtime preparation ${state}. The MCP connection will retry automatically.`)
    }
    const logPath = join(stateDirectory, 'bootstrap.log')
    process.stderr.write(`[dsh_kline] Preparing Python runtime: ${reason}.\n`)
    process.stderr.write(`[dsh_kline] Installation details: ${logPath}\n`)
    try {
      runtimePython = await prepareRuntime(venvDirectory, fingerprint, logPath, hasProjectRuntime ? projectPython : '')
    } catch (error) {
      await writeBootstrapFailure(venvDirectory, fingerprint, error).catch(() => {})
      throw new Error(`Runtime preparation failed. See ${logPath}. ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (bootstrapRuntime) await clearBootstrapMarker(venvDirectory)
    }
  }

  if (prepareProject || bootstrapRuntime) {
    process.stderr.write(`[dsh_kline] Python runtime ready: ${venvDirectory}\n`)
    return 0
  }
  return await launchServer(runtimePython, runtimeDirectory)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(code => { process.exitCode = code }).catch(error => {
    process.stderr.write(`[dsh_kline] ${error instanceof Error ? error.message : String(error)}\n`)
    process.exitCode = 1
  })
}
