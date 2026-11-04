import { test } from 'node:test'
import assert from 'node:assert/strict'
import { copyFileSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import { mcpConfiguration } from '../scripts/dsh-mcp-plugin.mjs'

test('nested bundle launch resolves beside its own module, with no profile-root package', async () => {
  const profile = realpathSync(mkdtempSync(join(tmpdir(), 'kline profile 中文 ')))
  try {
    const root = join(profile, 'node_modules', '@ft', 'dsh-fft-bundle', 'node_modules', '@ftshare-lab', 'dsh-kline')
    mkdirSync(join(root, 'scripts'), { recursive: true })
    writeFileSync(join(root, 'package.json'), JSON.stringify({ name: '@ftshare-lab/dsh-kline', type: 'module' }))
    writeFileSync(join(root, 'scripts', 'run-dsh-kline.mjs'), 'process.stdout.write("nested-mcp-started")')
    const entry = join(root, 'scripts', 'dsh-mcp-plugin.mjs')
    copyFileSync(new URL('../scripts/dsh-mcp-plugin.mjs', import.meta.url), entry)
    const plugin = await import(pathToFileURL(entry).href)
    const config = plugin.mcpConfiguration({ serverName: 'dsh-kline', env: { KEEP: 'yes' } }, {})
    assert.equal(config.cwd, root)
    assert.equal(config.args[0], join(root, 'scripts', 'run-dsh-kline.mjs'))
    const child = spawnSync(config.command, config.args, { cwd: config.cwd, encoding: 'utf8' })
    assert.equal(child.status, 0, child.stderr)
    assert.equal(child.stdout, 'nested-mcp-started')
    assert.deepEqual(config.env, { KEEP: 'yes' })
    const alias = join(profile, 'linked package 中文')
    symlinkSync(root, alias, process.platform === 'win32' ? 'junction' : 'dir')
    const linked = plugin.mcpConfiguration({}, { DSH_KLINE_PACKAGE_ROOT: alias })
    assert.equal(linked.cwd, root)
    assert.equal(spawnSync(linked.command, linked.args, { cwd: linked.cwd }).status, 0)
    let loaded, mounted
    await plugin.apply({ loader: { async import(name) { loaded = name; return { apply() {} } } },
      plugin(client, resolved) { mounted = resolved } }, { serverName: 'dsh-kline' })
    assert.equal(loaded, '@deepseek-ai/dsh-mcp-client')
    assert.equal(mounted.cwd, root)
  } finally { rmSync(profile, { recursive: true, force: true }) }
})

test('explicit package roots are validated before spawning', () => {
  assert.throws(() => mcpConfiguration({}, { DSH_KLINE_PACKAGE_ROOT: 'relative/path' }), /absolute/)
  assert.throws(() => mcpConfiguration({}, { DSH_KLINE_PACKAGE_ROOT: join(tmpdir(), 'missing-kline-root') }), /incomplete/)
  assert.equal(mcpConfiguration({}, {}).transport, 'stdio')
})
