import { after, test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const runtime = await mkdtemp(join(tmpdir(), 'dsh-kline-apply-test-'))
process.env.DSH_KLINE_RUNTIME_DIR = runtime

const { apply } = await import('../src/index.ts')
const { settingsCredentialFile } = await import('../src/ftshare-settings-bridge.ts')

after(async () => { await rm(runtime, { recursive: true, force: true }) })

const file = settingsCredentialFile(runtime, process.pid)

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path)
    return true
  } catch {
    return false
  }
}

async function waitForFile(): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < 2000) {
    if (await exists(file)) return
    await new Promise(resolve => setTimeout(resolve, 10))
  }
  throw new Error('the bridge never published a credential file')
}

/** Minimal host context: the plugin must load with nothing else available. */
function hostContext(extra: Record<string, unknown> = {}) {
  return {
    effect: (callback: () => () => void) => { callback() },
    webServer: { register: () => () => {} },
    ...extra,
  } as never
}

/** Cordis only runs the nested callback while the service is available. */
function settingsHost(key: string | undefined, disposers: Array<() => void>) {
  return hostContext({
    inject: (_services: string[], callback: (ctx: unknown) => void) => {
      callback({
        effect: (body: () => () => void) => { disposers.push(body()) },
        ftshareSettings: {
          apiKey: { resolve: async () => key, subscribe: () => () => {} },
        },
      })
    },
  })
}

test('a host without the FTShare settings service loads unchanged and writes nothing', async () => {
  apply(hostContext())
  await new Promise(resolve => setTimeout(resolve, 50))
  assert.equal(await exists(file), false)
})

test('a host with the settings service publishes and withdraws the credential', async () => {
  const disposers: Array<() => void> = []
  apply(settingsHost('ftshare_sk_apply_test', disposers))
  await waitForFile()
  for (const dispose of disposers) dispose()
  const startedAt = Date.now()
  while (Date.now() - startedAt < 2000 && await exists(file)) {
    await new Promise(resolve => setTimeout(resolve, 10))
  }
  assert.equal(await exists(file), false)
})
