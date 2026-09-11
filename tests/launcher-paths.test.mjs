import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  defaultRuntimeDirectory,
  defaultStateDirectory,
  backgroundBootstrapSpawnOptions,
  pythonCandidates,
  pythonEnvironment,
  pythonPathForVenv,
} from '../scripts/run-dsh-kline.mjs'

test('Windows uses native venv and LOCALAPPDATA paths', () => {
  const env = { LOCALAPPDATA: 'C:\\Users\\测试 User\\AppData\\Local' }
  assert.equal(
    pythonPathForVenv('C:\\Users\\测试 User\\runtime', 'win32'),
    'C:\\Users\\测试 User\\runtime\\Scripts\\python.exe',
  )
  assert.equal(
    defaultStateDirectory(env, 'win32', 'C:\\Users\\测试 User'),
    'C:\\Users\\测试 User\\AppData\\Local\\dsh_kline',
  )
  assert.equal(
    defaultRuntimeDirectory(env, 'win32', 'C:\\Users\\测试 User'),
    'C:\\Users\\测试 User\\AppData\\Local\\dsh_kline\\runtime',
  )
})

test('Windows Python Launcher candidates are version bounded and ordered', () => {
  assert.deepEqual(pythonCandidates({}, 'win32').slice(0, 4), [
    { command: 'py', args: ['-3.13'] },
    { command: 'py', args: ['-3.12'] },
    { command: 'py', args: ['-3.11'] },
    { command: 'py', args: ['-3.10'] },
  ])
  assert.deepEqual(pythonCandidates({ DSH_KLINE_PYTHON: 'D:\\Python\\python.exe' }, 'win32'), [
    { command: 'D:\\Python\\python.exe', args: [] },
  ])
})

test('POSIX and explicit runtime paths remain deterministic', () => {
  assert.equal(pythonPathForVenv('/tmp/venv', 'linux'), '/tmp/venv/bin/python')
  assert.equal(
    defaultStateDirectory({ XDG_CACHE_HOME: '/tmp/cache root' }, 'linux', '/home/user'),
    '/tmp/cache root/dsh_kline',
  )
  assert.equal(
    defaultRuntimeDirectory({ DSH_KLINE_RUNTIME_DIR: '/tmp/custom runtime' }, 'linux', '/home/user'),
    '/tmp/custom runtime',
  )
})

test('Python subprocesses use deterministic UTF-8 and noninteractive pip output', () => {
  assert.deepEqual(pythonEnvironment({ KEEP_ME: 'yes', PYTHONUTF8: '0' }), {
    KEEP_ME: 'yes',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PIP_PROGRESS_BAR: 'off',
    PIP_DISABLE_PIP_VERSION_CHECK: '1',
    PIP_NO_INPUT: '1',
  })
})

test('deferred bootstrap is detached on every host, including Windows', () => {
  assert.equal(backgroundBootstrapSpawnOptions('win32', {}).detached, true)
  assert.equal(backgroundBootstrapSpawnOptions('win32', {}).windowsHide, true)
  assert.equal(backgroundBootstrapSpawnOptions('linux', {}).detached, true)
})
