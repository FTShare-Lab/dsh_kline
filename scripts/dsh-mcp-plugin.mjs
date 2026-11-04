// A relative Cordis plugin name is anchored beside its bundle patch by DSH.
// Resolve the Python launcher from this module, including nested/pnpm installs.
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-kline-mcp-launcher'
export const inject = ['loader']

export function mcpConfiguration(config = {}, env = process.env, packageRoot = fileURLToPath(new URL('..', import.meta.url))) {
  const override = String(env.DSH_KLINE_PACKAGE_ROOT || '').trim()
  if (override && !isAbsolute(override)) throw new Error('DSH_KLINE_PACKAGE_ROOT must be an absolute package directory')
  let root = resolve(override || packageRoot)
  let manifest
  try { root = realpathSync(root); manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')) } catch {}
  if (manifest?.name !== '@ftshare-lab/dsh-kline' || !existsSync(join(root, 'scripts', 'run-dsh-kline.mjs'))) {
    throw new Error('dsh_kline package directory is incomplete; reinstall the plugin or correct DSH_KLINE_PACKAGE_ROOT')
  }
  return { ...config, command: config.command || process.execPath, transport: 'stdio',
    cwd: root, args: [join(root, 'scripts', 'run-dsh-kline.mjs')] }
}

export async function apply(ctx, config) {
  const resolved = mcpConfiguration(config)
  const client = await ctx.loader.import('@deepseek-ai/dsh-mcp-client')
  ctx.plugin(client.default || client, resolved)
}
