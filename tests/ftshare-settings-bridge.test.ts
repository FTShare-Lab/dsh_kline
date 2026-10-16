import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises'
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
  for (const pid of ['42oops','42.5','4e2','+42','9007199254740992']) {
    assert.deepEqual(settingsCredentialEnvironment('/runtime', { DSH_KLINE_HOST_PID: pid }), {})
  }
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

test('failed key resolution withdraws the old credential and never logs provider exception text', async () => {
  const runtime = await runtimeRoot(), settings = fakeSettings('first-key'), warnings: string[] = []
  const file = settingsCredentialFile(runtime, 4247)
  const bridge = startFtshareSettingsBridge({settings:settings.service,runtimeDirectory:runtime,hostPid:4247,warn:m=>warnings.push(m)})
  try {
    await waitFor(()=>exists(file),'missing first credential')
    settings.service.apiKey.resolve=async()=>{throw Error('secret-key provider response')}
    settings.publish('next-key')
    await waitFor(async()=>!(await exists(file)) && warnings.length===1,'failed rotation left old key active')
    assert.deepEqual(warnings,['FTShare settings credential publication failed'])
  } finally {await bridge.dispose()}
})

test('predictable staging symlinks are not followed and unsafe credential directories are not written or pruned', async () => {
  const runtime=await runtimeRoot(), directory=join(runtime,'credentials'), victim=join(runtime,'victim')
  await mkdir(directory);await writeFile(victim,'preserve')
  const file=settingsCredentialFile(runtime,4248)
  await symlink(victim,join(directory,`.ftshare-4248.json.${process.pid}.tmp`))
  const settings=fakeSettings('first-key'), bridge=startFtshareSettingsBridge({settings:settings.service,runtimeDirectory:runtime,hostPid:4248})
  try {await waitFor(()=>exists(file),'missing credential');assert.equal(await readFile(victim,'utf8'),'preserve')}
  finally {await bridge.dispose()}
  const second=await runtimeRoot(), outside=join(runtime,'outside');await mkdir(outside)
  const outsideFile=settingsCredentialFile(runtime,4249).replace(directory,outside)
  await writeFile(outsideFile,'preserve outside')
  const stale=join(outside,'ftshare-999999999.json');await writeFile(stale,'preserve stale')
  await symlink(outside,join(second,'credentials'),process.platform==='win32'?'junction':'dir')
  const warnings:string[]=[], unsafe=startFtshareSettingsBridge({settings:settings.service,runtimeDirectory:second,hostPid:4249,warn:m=>warnings.push(m)})
  try {
    await waitFor(async()=>warnings.length>0,'unsafe directory was accepted')
    assert.equal(await readFile(outsideFile,'utf8'),'preserve outside');assert.equal(await readFile(stale,'utf8'),'preserve stale')
  } finally {await unsafe.dispose()}
  assert.equal(await readFile(outsideFile,'utf8'),'preserve outside')
})
