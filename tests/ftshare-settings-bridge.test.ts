import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import {
  SETTINGS_CREDENTIAL_ENV,
  settingsCredentialFile,
  startFtshareSettingsBridge,
} from '../src/ftshare-settings-bridge.ts'
import {
  settingsCredentialEnvironment,
  settingsCredentialFile as launcherCredentialFile,
} from '../scripts/run-dsh-kline.mjs'

const roots: string[] = []

async function runtimeRoot(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-kline-bridge-test-'))
  roots.push(directory)
  return directory
}

after(async () => {
  for (const root of roots) await rm(root, { recursive: true, force: true })
})

/** Settings service stub: the bridge only ever calls these two methods. */
function fakeSettings(initial?: string) {
  let value = initial
  const listeners = new Set<() => void>()
  return {
    service: {
      apiKey: {
        resolve: async () => value,
        subscribe(listener: () => void) {
          listeners.add(listener)
          return () => { listeners.delete(listener) }
        },
      },
    },
    publish(next?: string) {
      value = next
      for (const listener of listeners) listener()
    },
    get listeners() {
      return listeners.size
    },
  }
}

async function waitFor(predicate: () => Promise<boolean>, message: string, timeoutMs = 2000): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    if (await predicate()) return
    await new Promise(resolve => setTimeout(resolve, 10))
  }
  throw new Error(message)
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

test('the launcher locates the same credential file as the host bridge', () => {
  for (const pid of [1, 4321, 999999]) {
    assert.equal(launcherCredentialFile('/runtime', pid), settingsCredentialFile('/runtime', pid))
  }
  assert.equal(settingsCredentialFile('/runtime', 4321), join('/runtime', 'credentials', 'ftshare-4321.json'))
})

test('the launcher only points the MCP server at a credential file a host can own', () => {
  const expected = { [SETTINGS_CREDENTIAL_ENV]: join('/runtime', 'credentials', 'ftshare-42.json') }
  assert.deepEqual(settingsCredentialEnvironment('/runtime', { DSH_KLINE_HOST_PID: '42' }), expected)
  // A standalone or hand-started server keeps resolving credentials exactly as before.
  assert.deepEqual(settingsCredentialEnvironment('/runtime', {}), {})
  assert.deepEqual(settingsCredentialEnvironment('/runtime', { DSH_KLINE_HOST_PID: '   ' }), {})
  assert.deepEqual(settingsCredentialEnvironment('/runtime', { DSH_KLINE_HOST_PID: 'nope' }), {})
  assert.deepEqual(settingsCredentialEnvironment('/runtime', { DSH_KLINE_HOST_PID: '-1' }), {})
})

test('publishes the configured Key in the shape the MCP server reads', async () => {
  const runtime = await runtimeRoot()
  const settings = fakeSettings('ftshare_sk_test_key')
  const file = settingsCredentialFile(runtime, 4242)
  const bridge = startFtshareSettingsBridge({ settings: settings.service, runtimeDirectory: runtime, hostPid: 4242 })
  try {
    await waitFor(() => exists(file), 'the credential file was never published')
    assert.deepEqual(JSON.parse(await readFile(file, 'utf8')), { version: 1, api_key: 'ftshare_sk_test_key' })
    if (process.platform !== 'win32') {
      assert.equal((await stat(file)).mode & 0o777, 0o600, 'the published credential must stay private')
    }
    // The MCP server is a separate process: the file is the whole contract.
    assert.equal((await stat(dirname(file))).isDirectory(), true)
  } finally {
    await bridge.dispose()
  }
})

test('follows a Key change and removes the file when the Key is cleared', async () => {
  const runtime = await runtimeRoot()
  const settings = fakeSettings('first-key')
  const file = settingsCredentialFile(runtime, 4243)
  const bridge = startFtshareSettingsBridge({ settings: settings.service, runtimeDirectory: runtime, hostPid: 4243 })
  try {
    await waitFor(() => exists(file), 'the credential file was never published')
    settings.publish('second-key')
    await waitFor(async () => await exists(file) && JSON.parse(await readFile(file, 'utf8')).api_key === 'second-key',
      'a Key change was not followed')
    // Clearing the setting must not leave the previous Key behind.
    settings.publish(undefined)
    await waitFor(async () => !(await exists(file)), 'a cleared Key left its file behind')
  } finally {
    await bridge.dispose()
  }
})

test('never publishes a Key the MCP server would discard', async () => {
  const runtime = await runtimeRoot()
  const settings = fakeSettings('bad\u0000key')
  const file = settingsCredentialFile(runtime, 4244)
  const bridge = startFtshareSettingsBridge({ settings: settings.service, runtimeDirectory: runtime, hostPid: 4244 })
  try {
    settings.publish('x'.repeat(513))
    await new Promise(resolve => setTimeout(resolve, 50))
    assert.equal(await exists(file), false)
  } finally {
    await bridge.dispose()
  }
})

test('removes the published file on dispose', async () => {
  const runtime = await runtimeRoot()
  const settings = fakeSettings('ftshare_sk_disposable')
  const file = settingsCredentialFile(runtime, 4245)
  const bridge = startFtshareSettingsBridge({ settings: settings.service, runtimeDirectory: runtime, hostPid: 4245 })
  await waitFor(() => exists(file), 'the credential file was never published')
  await bridge.dispose()
  assert.equal(await exists(file), false)
  assert.equal(settings.listeners, 0, 'disposing must stop following the credential')
})

test('keeps a live host file and drops the one a dead host left behind', async () => {
  const runtime = await runtimeRoot()
  const directory = join(runtime, 'credentials')
  await mkdir(directory, { recursive: true })
  const live = settingsCredentialFile(runtime, process.ppid)
  const dead = settingsCredentialFile(runtime, 999999999)
  await writeFile(live, '{"version":1,"api_key":"live"}', { mode: 0o600 })
  await writeFile(dead, '{"version":1,"api_key":"stale"}', { mode: 0o600 })
  const settings = fakeSettings('ftshare_sk_pruned')
  const bridge = startFtshareSettingsBridge({ settings: settings.service, runtimeDirectory: runtime, hostPid: 4246 })
  try {
    await waitFor(async () => !(await exists(dead)), 'a dead host credential survived')
    assert.equal(await exists(live), true, 'another live host owns its own file')
  } finally {
    await bridge.dispose()
  }
})
