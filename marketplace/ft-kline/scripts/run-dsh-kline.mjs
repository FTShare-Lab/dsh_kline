#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { access, appendFile, mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { delimiter, dirname, join, posix, resolve, win32 } from 'node:path'
import { fileURLToPath } from 'node:url'

const PROJECT_ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)))
const REQUIREMENTS_FILE = join(PROJECT_ROOT, 'requirements.txt')
const IMPORT_CHECK = 'import ftshare, mcp, pydantic, pydantic_settings, talib; assert talib.__version__ == "0.8.2" and len(talib.get_functions()) == 201'
// Native dependency imports can be cold on macOS. Node already owns the MCP
// handshake, so a short probe timeout must not trigger needless reinstallation.
const IMPORT_PROBE_TIMEOUT_MS = 90_000
const VERSION_CHECK = 'import sys; raise SystemExit(sys.version_info < (3, 11))'
const RUNTIME_VERSION_CHECK = 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
const REQUIREMENTS_STAMP = '.dsh-kline-requirements'
const BOOTSTRAP_FAILURE = '.dsh-kline-bootstrap-failed'
const BOOTSTRAP_RUNNING = '.dsh-kline-bootstrap-running'
const BACKGROUND_BOOTSTRAP_STALE_MS = 10 * 60 * 1000
// A failed download or a temporarily unavailable index must not turn into a
// permanent startup failure. Keep reconnect storms from repeatedly invoking
// pip, but let a later launch repair the environment by itself.
const BOOTSTRAP_FAILURE_RETRY_MS = 5 * 60 * 1000

function runtimeError(code, message) {
  return Object.assign(new Error(message), { code })
}

export function pythonProbeOutcome(candidate, result, platform = process.platform, resolvedCommand = candidate.command) {
  const version = String(result.stdout || '').trim()
  if (result.status === 0 && /^\d+\.\d+$/.test(version)) {
    const [major, minor] = version.split('.').map(Number)
    return { code: major > 3 || major === 3 && minor >= 11 ? 'PYTHON_READY' : 'PYTHON_VERSION_TOO_OLD', version }
  }
  // A working Store-installed interpreter is accepted above. Only a failed
  // redirector probe is classified as a Store placeholder.
  if (platform === 'win32' && (/\\Microsoft\\WindowsApps\\/i.test(resolvedCommand)
    || /Microsoft Store|App execution aliases/i.test(String(result.stderr || '') + String(result.stdout || '')))) {
    return { code: 'PYTHON_STORE_ALIAS' }
  }
  return { code: result.error?.code === 'ENOENT' ? 'PYTHON_NOT_FOUND' : 'PYTHON_EXECUTION_FAILED' }
}

async function resolvedPythonCommand(candidate) {
  if (/[\\/]/.test(candidate.command)) return candidate.command
  for (const directory of (process.env.PATH || '').split(delimiter).filter(Boolean)) {
    const path = join(directory, candidate.command + (process.platform === 'win32' ? '.exe' : ''))
    try { await stat(path); return path } catch {}
  }
  return candidate.command
}

async function bootstrapStep(code, label, command, args, logPath) {
  try { return await runLogged(command, args, logPath) }
  catch (error) { throw runtimeError(code, `${label}. ${error instanceof Error ? error.message : String(error)}`) }
}

async function dependencyImportCheck() {
  const requirements = await readFile(REQUIREMENTS_FILE, 'utf8')
  const pins = {}
  for (const line of requirements.split(/\r?\n/)) {
    const pinned = line.match(/^([\w.-]+)==([^\s;]+)\s*$/)
    const tagged = line.match(/^([\w.-]+)\s+@\s+https:\/\/github\.com\/[^\s]+\/refs\/tags\/v([\d.]+)\.tar\.gz\s*$/)
    if (pinned || tagged) { const [, name, version] = pinned || tagged; pins[name] = version }
  }
  return `${IMPORT_CHECK}; from importlib.metadata import version as installed_version; assert all(installed_version(name) == expected for name, expected in ${JSON.stringify(pins)}.items()), "Pinned runtime dependency mismatch"`
}

export function desktopPythonCandidates(executable = process.execPath, platform = process.platform) {
  // Signed macOS app runtimes may forbid loading third-party native wheels.
  // Do not silently select that private runtime over a standard Python.
  if (platform !== 'win32') return []
  const python = win32.join(win32.dirname(executable), 'resources', 'runtime', 'primary-runtime', 'dependencies', 'python')
  return [win32.join(python, 'python.exe'), win32.join(python, 'bin', 'python.exe')]
    .map(command => ({ command, args: [] }))
}

export function venvBaseCandidates(config, platform = process.platform) {
  const paths = platform === 'win32' ? win32 : posix
  const home = config.match(/^\s*home\s*=\s*(.+?)\s*$/mi)?.[1]
  const executable = config.match(/^\s*executable\s*=\s*(.+?)\s*$/mi)?.[1]
  return [executable, ...(home ? [paths.join(home, platform === 'win32' ? 'python.exe' : 'python3')] : [])]
    .filter(path => path && paths.isAbsolute(path)).map(command => ({ command, args: [] }))
}

async function bootstrapCandidates(venvDirectory, preferred = '') {
  // An explicit interpreter is authoritative; do not fall back to another one.
  if (String(process.env.DSH_KLINE_PYTHON || '').trim()) return pythonCandidates()
  let config = ''
  try { config = await readFile(join(venvDirectory, 'pyvenv.cfg'), 'utf8') } catch {}
  return [...(preferred ? [{ command: preferred, args: [] }] : []),
    ...venvBaseCandidates(config), ...desktopPythonCandidates(), ...pythonCandidates()]
}

export async function bootstrapEnvironmentFingerprint(venvDirectory) {
  const candidates = [{ command: pythonPathForVenv(venvDirectory), args: [] },
    ...await bootstrapCandidates(venvDirectory)]
  const observations = []
  for (const candidate of candidates) {
    const locations = /[\\/]/.test(candidate.command) ? [candidate.command]
      : (process.env.PATH || '').split(delimiter).filter(Boolean).flatMap(directory => {
        const path = join(directory, candidate.command)
        return process.platform === 'win32' ? [path, path + '.exe'] : [path]
      })
    for (const location of locations) {
      try { const file = await stat(location); observations.push([location, file.size, file.mtimeMs, file.mode]) } catch {}
    }
  }
  let config = ''
  try { config = await readFile(join(venvDirectory, 'pyvenv.cfg'), 'utf8') } catch {}
  return createHash('sha256').update(JSON.stringify({ candidates, observations, config,
    platform: process.platform,
    python: process.env.DSH_KLINE_PYTHON || '', path: process.env.PATH || '',
    pythonHome: process.env.PYTHONHOME || '', pythonPath: process.env.PYTHONPATH || '' })).digest('hex')
}

export function pythonPathForVenv(venvDirectory, platform = process.platform) {
  const paths = platform === 'win32' ? win32 : posix
  return platform === 'win32'
    ? paths.join(venvDirectory, 'Scripts', 'python.exe')
    : paths.join(venvDirectory, 'bin', 'python')
}

export function defaultStateDirectory(env = process.env, platform = process.platform, userHome = homedir()) {
  const paths = platform === 'win32' ? win32 : posix
  const codexServer = String(env.FT_KLINE_SERVER_ENTRY || '').trim() === 'codex_server.py'
  const codexExplicit = String(env.FT_KLINE_CACHE_DIR || '').trim()
  if (codexServer && codexExplicit) return paths.resolve(codexExplicit)
  const explicit = String(env.DSH_KLINE_CACHE_DIR || '').trim()
  if (explicit) return paths.resolve(explicit)
  if (platform === 'win32') {
    const local = String(env.LOCALAPPDATA || env.APPDATA || '').trim()
    return paths.join(local || paths.join(userHome, 'AppData', 'Local'), codexServer ? 'ft-kline' : 'dsh_kline')
  }
  const cache = String(env.XDG_CACHE_HOME || '').trim()
  return paths.join(cache || paths.join(userHome, '.cache'), codexServer ? 'ft-kline' : 'dsh_kline')
}

export function defaultRuntimeDirectory(env = process.env, platform = process.platform, userHome = homedir()) {
  const paths = platform === 'win32' ? win32 : posix
  const codexServer = String(env.FT_KLINE_SERVER_ENTRY || '').trim() === 'codex_server.py'
  const codexExplicit = String(env.FT_KLINE_RUNTIME_DIR || '').trim()
  if (codexServer && codexExplicit) return paths.resolve(codexExplicit)
  const explicit = String(env.DSH_KLINE_RUNTIME_DIR || '').trim()
  return explicit ? paths.resolve(explicit) : paths.join(defaultStateDirectory(env, platform, userHome), 'runtime')
}

/**
 * Credential file the DSH host publishes from its FTShare settings service.
 *
 * Mirrors `settingsCredentialFile()` in `src/ftshare-settings-bridge.ts`; the
 * host_process_id keeps a file from an earlier DSH run from being reused.
 */
export function settingsCredentialFile(runtimeDirectory, hostPid) {
  return join(runtimeDirectory, 'credentials', `ftshare-${hostPid}.json`)
}

/**
 * Point the MCP server at the host's settings credential when this process was
 * launched by a DSH host that could publish one.  Without that locator the
 * server keeps its previous credential resolution untouched.
 */
export function settingsCredentialEnvironment(runtimeDirectory, env = process.env) {
  const rawPid = String(env.DSH_KLINE_HOST_PID || '').trim()
  if (!/^[1-9]\d*$/.test(rawPid)) return {}
  const hostPid = Number(rawPid)
  if (!Number.isSafeInteger(hostPid) || hostPid <= 0) return {}
  return { DSH_KLINE_SETTINGS_KEY_FILE: settingsCredentialFile(runtimeDirectory, hostPid) }
}

export function pythonCandidates(env = process.env, platform = process.platform) {
  const explicit = String(env.DSH_KLINE_PYTHON || '').trim()
  if (explicit) return [{ command: explicit, args: [] }]
  if (platform === 'win32') {
    const installed = ['313', '312', '311'].flatMap(version => [
      ...(env.LOCALAPPDATA ? [win32.join(env.LOCALAPPDATA, 'Programs', 'Python', `Python${version}`, 'python.exe')] : []),
      ...(env.ProgramFiles ? [win32.join(env.ProgramFiles, `Python${version}`, 'python.exe')] : []),
    ])
    return [
      ...['3.13', '3.12', '3.11'].map(version => ({ command: 'py', args: [`-${version}`] })),
      ...installed.map(command => ({ command, args: [] })),
      { command: 'python', args: [] },
      { command: 'python3', args: [] },
    ]
  }
  return [
    'python3.13', 'python3.12', 'python3.11',
    '/opt/homebrew/bin/python3.13', '/opt/homebrew/bin/python3.12',
    '/opt/homebrew/bin/python3.11',
    '/usr/local/bin/python3.13', '/usr/local/bin/python3.12',
    '/usr/local/bin/python3.11',
    'python3', '/opt/homebrew/bin/python3', '/usr/local/bin/python3',
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

function commandPasses(command, args, code, timeoutMs = 10_000) {
  const result = spawnSync(command, [...args, '-c', code], {
    env: pythonEnvironment(),
    encoding: 'utf8',
    stdio: 'ignore',
    timeout: timeoutMs,
    windowsHide: true,
  })
  return result.status === 0
}

function commandOutput(command, args, code) {
  const result = spawnSync(command, [...args, '-c', code], {
    env: pythonEnvironment(),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
    timeout: 10_000,
    windowsHide: true,
  })
  return result.status === 0 ? result.stdout.trim() : ''
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

async function venvInterpreterMatches(venvDirectory, runtimePython) {
  const runtimeVersion = commandOutput(runtimePython, [], RUNTIME_VERSION_CHECK)
  if (!/^\d+\.\d+$/.test(runtimeVersion)) return false
  try {
    const config = await readFile(join(venvDirectory, 'pyvenv.cfg'), 'utf8')
    const match = config.match(/^\s*version\s*=\s*(\d+\.\d+)(?:\.\d+)?\s*$/mi)
    return match?.[1] === runtimeVersion
  } catch {
    return false
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

async function findBootstrapPython(venvDirectory, logPath, preferred = '') {
  const candidates = await bootstrapCandidates(venvDirectory, preferred)
  const seen = new Set()
  const outcomes = new Set()
  for (const candidate of candidates) {
    const key = `${candidate.command}\u0000${candidate.args.join('\u0000')}`
    if (seen.has(key)) continue
    seen.add(key)
    const result = spawnSync(candidate.command, [...candidate.args, '-c', RUNTIME_VERSION_CHECK], {
      env: pythonEnvironment(), encoding: 'utf8', timeout: 10_000, maxBuffer: 64 * 1024, windowsHide: true,
    })
    const outcome = pythonProbeOutcome(candidate, result, process.platform, await resolvedPythonCommand(candidate))
    if (outcome.code === 'PYTHON_READY' && !commandPasses(candidate.command, candidate.args, 'import venv, ensurepip')) {
      outcome.code = 'PYTHON_VENV_UNAVAILABLE'
    }
    // Record only paths, versions and classifications; never dump the parent
    // environment or arbitrary output from a failed executable.
    const diagnostic = `[dsh_kline] Python candidate: ${JSON.stringify({ command: candidate.command, args: candidate.args, ...outcome })}\n`
    await appendFile(logPath, diagnostic, 'utf8')
    process.stderr.write(diagnostic)
    if (outcome.code === 'PYTHON_READY') return candidate
    outcomes.add(outcome.code)
  }
  const hint = process.platform === 'win32'
    ? 'Install Python 3.11 or newer from python.org, enable the Python Launcher, or set DSH_KLINE_PYTHON.'
    : 'Install Python 3.11 or newer, or set DSH_KLINE_PYTHON to its executable.'
  const code = ['PYTHON_VENV_UNAVAILABLE', 'PYTHON_VERSION_TOO_OLD', 'PYTHON_STORE_ALIAS', 'PYTHON_EXECUTION_FAILED']
    .find(code => outcomes.has(code)) || 'PYTHON_NOT_FOUND'
  const message = {
    PYTHON_VENV_UNAVAILABLE: 'Python was found but cannot create a virtual environment (venv/ensurepip missing).',
    PYTHON_VERSION_TOO_OLD: 'Python was found but its version is below Python 3.11.',
    PYTHON_STORE_ALIAS: 'Detected a Windows Store Python placeholder, not a usable interpreter. Install python.org Python or set DSH_KLINE_PYTHON to the full python.exe file path.',
    PYTHON_EXECUTION_FAILED: 'A Python candidate could not execute or report its version.',
    PYTHON_NOT_FOUND: 'No usable Python interpreter was found; dsh_kline requires Python 3.11 or newer.',
  }[code]
  throw runtimeError(code, `${message} ${hint}`)
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

async function prepareRuntime(venvDirectory, fingerprint, logPath, preferredPython = '', clearExisting = false) {
  await mkdir(dirname(venvDirectory), { recursive: true })
  await mkdir(dirname(logPath), { recursive: true })
  await writeFile(logPath, '', { encoding: 'utf8', mode: 0o600 })
  const runtimePython = pythonPathForVenv(venvDirectory)
  const reusable = !clearExisting && await pathExists(runtimePython)
    && commandPasses(runtimePython, [], VERSION_CHECK) && await venvInterpreterMatches(venvDirectory, runtimePython)
    && (commandPasses(runtimePython, [], 'import pip') || commandPasses(runtimePython, [], 'import ensurepip'))
  if (reusable) {
    process.stderr.write('[dsh_kline] Reusing the existing Python environment.\n')
    if (!commandPasses(runtimePython, [], 'import pip')) await bootstrapStep('PYTHON_VENV_UNAVAILABLE',
      'Cannot prepare pip in the existing environment', runtimePython, ['-m', 'ensurepip', '--upgrade'], logPath)
  } else {
    const base = await findBootstrapPython(venvDirectory, logPath, preferredPython)
    process.stderr.write('[dsh_kline] Creating or repairing the Python environment…\n')
    const venvArgs = [...base.args, '-m', 'venv', ...(clearExisting ? ['--clear'] : []), venvDirectory]
    const venvMs = await bootstrapStep('PYTHON_VENV_UNAVAILABLE', 'Cannot create or repair the virtual environment', base.command, venvArgs, logPath)
    process.stderr.write(`[dsh_kline] Python environment ready in ${Math.ceil(venvMs / 1000)}s.\n`)
  }
  process.stderr.write('[dsh_kline] Installing dependencies…\n')
  // Isolate pip from a user's config (notably `user = true`, which makes a
  // venv install fail before it can write the ready stamp).
  const dependenciesMs = await bootstrapStep('PYTHON_DEPENDENCY_INSTALL_FAILED', 'Dependency installation failed',
    runtimePython, ['-m', 'pip', '--isolated', 'install', '-r', REQUIREMENTS_FILE], logPath)
  process.stderr.write(`[dsh_kline] Dependencies ready in ${Math.ceil(dependenciesMs / 1000)}s.\n`)
  process.stderr.write('[dsh_kline] Verifying the runtime…\n')
  await bootstrapStep('PYTHON_IMPORT_CHECK_FAILED', 'Installed dependency verification failed',
    runtimePython, ['-c', await dependencyImportCheck()], logPath)
  await writeStamp(venvDirectory, fingerprint)
  await rm(join(venvDirectory, BOOTSTRAP_FAILURE), { force: true })
  if (!(await stampMatches(venvDirectory, fingerprint))) {
    throw new Error('Dependency fingerprint was not persisted; refusing to report a ready runtime.')
  }
  process.stderr.write('[dsh_kline] Dependency fingerprint saved.\n')
  return runtimePython
}

async function readBootstrapFailure(venvDirectory, fingerprint, environment) {
  try {
    const failure = JSON.parse(await readFile(join(venvDirectory, BOOTSTRAP_FAILURE), 'utf8'))
    return failure?.fingerprint === fingerprint && failure.environment === environment ? failure : null
  } catch {
    return null
  }
}

async function writeBootstrapFailure(venvDirectory, fingerprint, error) {
  await mkdir(venvDirectory, { recursive: true })
  const environment = await bootstrapEnvironmentFingerprint(venvDirectory)
  await writeFile(join(venvDirectory, BOOTSTRAP_FAILURE), JSON.stringify({ fingerprint, environment,
    failureCode: error?.code || 'BOOTSTRAP_FAILED', at: new Date().toISOString(), error: String(error) }), { encoding: 'utf8', mode: 0o600 })
}

function bootstrapFailureRetryAt(failure) {
  const failedAt = Date.parse(String(failure?.at || ''))
  return Number.isFinite(failedAt) ? failedAt + BOOTSTRAP_FAILURE_RETRY_MS : 0
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
  const serverEntry = String(process.env.FT_KLINE_SERVER_ENTRY || '').trim() || 'server.py'
  if (!['server.py', 'codex_server.py'].includes(serverEntry)) throw new Error('FT_KLINE_SERVER_ENTRY must be server.py or codex_server.py')
  const child = spawn(runtimePython, [join(PROJECT_ROOT, serverEntry)], {
    cwd: PROJECT_ROOT,
    env: pythonEnvironment({
      ...process.env,
      DSH_KLINE_RUNTIME_DIR: runtimeDirectory,
      ...(serverEntry === 'server.py' ? settingsCredentialEnvironment(runtimeDirectory) : {}),
    }),
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
  // The host must never spend its reconnect budget waiting for pip. A stable
  // Node endpoint owns discovery while this same launcher prepares Python.
  if (!prepareProject && !bootstrapRuntime && process.env.DSH_KLINE_DEFER_BOOTSTRAP === '1'
    && process.env.DSH_KLINE_RUNTIME_MODE !== 'external' && process.env.FT_KLINE_SERVER_ENTRY !== 'codex_server.py') {
    const { serve } = await import('./dsh-bootstrap.mjs')
    serve({ args: [fileURLToPath(import.meta.url)] })
    return 0
  }
  const stateDirectory = defaultStateDirectory()
  const runtimeDirectory = defaultRuntimeDirectory()
  const configuredVenv = String(process.env.DSH_KLINE_VENV || '').trim()
  const configuredPython = String(process.env.DSH_KLINE_PYTHON || '').trim()
  const runtimeMode = String(process.env.DSH_KLINE_RUNTIME_MODE || '').trim() || 'auto'
  if (!['auto', 'external'].includes(runtimeMode)) {
    throw new Error('DSH_KLINE_RUNTIME_MODE must be auto or external')
  }
  if (runtimeMode === 'external') {
    if (configuredVenv || prepareProject || bootstrapRuntime) {
      throw new Error('External runtime cannot be combined with DSH_KLINE_VENV, --prepare-project or --bootstrap-runtime')
    }
    if (!configuredPython) {
      throw new Error('External runtime requires DSH_KLINE_PYTHON')
    }
    if (!commandPasses(configuredPython, [], VERSION_CHECK)) {
      throw new Error('External DSH_KLINE_PYTHON must be a working Python 3.11 or newer; automatic installation is disabled')
    }
    if (!commandPasses(configuredPython, [], IMPORT_CHECK, IMPORT_PROBE_TIMEOUT_MS)) {
      throw new Error('External DSH_KLINE_PYTHON is missing required dependencies; the host must provision them, automatic installation is disabled')
    }
    return await launchServer(configuredPython, runtimeDirectory)
  }
  const importCheck = await dependencyImportCheck()
  const projectVenv = join(PROJECT_ROOT, '.venv')
  const projectPython = pythonPathForVenv(projectVenv)
  const hasProjectRuntime = await pathExists(projectPython)
  const configuredPythonWorks = !prepareProject && !configuredVenv && Boolean(configuredPython)
    && commandPasses(configuredPython, [], VERSION_CHECK)
    && commandPasses(configuredPython, [], importCheck, IMPORT_PROBE_TIMEOUT_MS)
  const venvDirectory = prepareProject
    ? projectVenv
    : configuredVenv || (hasProjectRuntime ? projectVenv : join(stateDirectory, 'venv'))
  const managedRuntime = !configuredPythonWorks && (prepareProject || Boolean(configuredVenv) || !hasProjectRuntime)
  let runtimePython = configuredPythonWorks ? configuredPython : pythonPathForVenv(venvDirectory)
  const fingerprint = await requirementsFingerprint()
  const runtimeImportsWork = configuredPythonWorks || await pathExists(runtimePython) && commandPasses(runtimePython, [], importCheck, IMPORT_PROBE_TIMEOUT_MS)
  const runtimeVenvMatches = configuredPythonWorks || !runtimeImportsWork
    ? true
    : await venvInterpreterMatches(venvDirectory, runtimePython)
  const runtimeWorks = runtimeImportsWork && runtimeVenvMatches
  const previousFailure = managedRuntime ? await readBootstrapFailure(venvDirectory, fingerprint,
    await bootstrapEnvironmentFingerprint(venvDirectory)) : null
  let requirementsMatch = !managedRuntime || await stampMatches(venvDirectory, fingerprint)
  let reason = ''
  if (!runtimeWorks) reason = runtimeImportsWork
    ? 'Python runtime interpreter metadata is inconsistent'
    : 'Python runtime is missing or incomplete'
  else if (!requirementsMatch) reason = 'dependency requirements changed'

  if (reason) {
    if (!managedRuntime) {
      throw new Error('The project .venv is incomplete. Run: pnpm bootstrap')
    }
    if (previousFailure && !prepareProject) {
      const logPath = join(stateDirectory, 'bootstrap.log')
      const retryAt = bootstrapFailureRetryAt(previousFailure)
      if (retryAt > Date.now()) {
        throw new Error(`Python runtime preparation recently failed [${previousFailure.failureCode || 'BOOTSTRAP_FAILED'}]; automatic retry will resume after ${new Date(retryAt).toISOString()}. Run: pnpm bootstrap to retry now. See ${logPath}.`)
      }
      await rm(join(venvDirectory, BOOTSTRAP_FAILURE), { force: true }).catch(() => {})
    }
    const logPath = join(stateDirectory, 'bootstrap.log')
    process.stderr.write(`[dsh_kline] Preparing Python runtime: ${reason}.\n`)
    process.stderr.write(`[dsh_kline] Installation details: ${logPath}\n`)
    try {
      runtimePython = await prepareRuntime(
        venvDirectory,
        fingerprint,
        logPath,
        hasProjectRuntime ? projectPython : '',
        runtimeImportsWork && !runtimeVenvMatches,
      )
    } catch (error) {
      await writeBootstrapFailure(venvDirectory, fingerprint, error).catch(() => {})
      throw runtimeError(error?.code || 'BOOTSTRAP_FAILED', `Runtime preparation failed [${error?.code || 'BOOTSTRAP_FAILED'}]. See ${logPath}. ${error instanceof Error ? error.message : String(error)}`)
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
