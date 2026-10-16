import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const PROJECT_ROOT = fileURLToPath(new URL('..', import.meta.url))

// Dev/CI only: no bootstrap, download, provider probe or credential discovery.
export function testPythonExecutable({ env = process.env, platform = process.platform,
  root = PROJECT_ROOT, exists = existsSync } = {}) {
  const explicit = String(env.DSH_KLINE_TEST_PYTHON || '').trim()
  if (explicit) return explicit
  const local = resolve(root, '.venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']))
  return exists(local) ? local : platform === 'win32' ? 'python' : 'python3'
}

export function isolatedTestEnvironment(env, directory, python) {
  const isolated = { ...env, DSH_KLINE_TEST_PYTHON: python,
    DSH_KLINE_RUNTIME_DIR: join(directory, 'runtime'), DSH_KLINE_CACHE_DIR: join(directory, 'cache'),
    FTSHARE_API_KEY_FILE: join(directory, 'no-credential.json'), PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
  delete isolated.FTSHARE_API_KEY
  delete isolated.DSH_KLINE_SETTINGS_KEY_FILE
  delete isolated.DSH_KLINE_HOST_PID
  return isolated
}

export const TEST_PYTHON = testPythonExecutable()
