import { execFileSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { resolve, sep } from 'node:path'

// This is intentionally independent from package.json's DSH npm allowlist.
// A Codex archive must not accidentally inherit a loopback server, DSH client,
// Cordis patch, or DSH credential bridge as the project grows.
const allowlist = [
  'CHANGELOG.md', 'LICENSE', 'README.md', 'README.en.md', 'package.json', 'requirements.txt',
  'docs/release-notes-v0.6.0.md', 'docs/release-acceptance-v0.6.0.md',
  'docs/release-notes-v0.6.1.md', 'docs/release-acceptance-v0.6.1.md',
  'docs/release-notes-v0.6.2.md', 'docs/release-acceptance-v0.6.2.md',
  'docs/release-notes-v0.6.3.md', 'docs/release-acceptance-v0.6.3.md',
  'docs/release-notes-v0.6.4.md', 'docs/release-acceptance-v0.6.4.md',
  'docs/embedding.md', 'docs/release-notes-v0.6.5.md', 'docs/release-acceptance-v0.6.5.md',
  'codex_server.py', 'codex_runtime', 'core', 'config/basic-symbols.json', 'view',
  // Only provider/indicator/geometry modules shared by the Codex adapter.
  // DSH context, HTTP application, and snapshot modules are intentionally not
  // present in this archive.
  'tools/annotations.py', 'tools/calc.py', 'tools/chart_indicators.py', 'tools/channels.py', 'tools/channel_candidates.py',
  'tools/baostock_source.py', 'tools/draw.py', 'tools/fetch.py', 'tools/fibonacci.py', 'tools/free_sources.py', 'tools/lines.py',
  'tools/pivots.py', 'tools/polylines.py', 'tools/price_bands.py', 'tools/price_series.py',
  'tools/price_sticks.py', 'tools/range_candidates.py', 'tools/rectangles.py', 'tools/trend_lines.py',
  'scripts/run-dsh-kline.mjs', 'scripts/codex-bootstrap.mjs', 'scripts/run-ft-kline.mjs', 'scripts/run-ft-kline-cli.mjs',
  'plugins/ft-kline/plugin.json', 'plugins/ft-kline/.codex-plugin/plugin.json',
  'plugins/ft-kline/mcp.json', 'plugins/ft-kline/.mcp.json', 'plugins/ft-kline/assets',
  'plugins/ft-kline/.agents/plugins/marketplace.json',
]
const remap = new Map([
  ['plugins/ft-kline/plugin.json', 'plugin.json'],
  ['plugins/ft-kline/.agents/plugins/marketplace.json', '.agents/plugins/marketplace.json'],
  ['plugins/ft-kline/.codex-plugin/plugin.json', '.codex-plugin/plugin.json'],
  ['plugins/ft-kline/mcp.json', 'mcp.json'],
  ['plugins/ft-kline/.mcp.json', '.mcp.json'],
  ['plugins/ft-kline/assets/', 'assets/'],
])

function outputName(path) {
  if (remap.has(path)) return remap.get(path)
  for (const [from, to] of remap) if (from.endsWith('/') && path.startsWith(from)) return to + path.slice(from.length)
  return path
}
function validPath(path) {
  return typeof path === 'string' && path && !path.startsWith('/') && !path.split('/').includes('..')
}

export async function codexPackageFiles(root) {
  const files = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', ...allowlist], { cwd: root })
    .toString('utf8').split('\0').filter(Boolean).filter(path => !path.split('/').includes('__pycache__') && !/\.py[cod]$/.test(path))
  if (!files.length || allowlist.some(entry => !files.some(path => path === entry || path.startsWith(`${entry}/`)))) {
    throw new Error('Codex package allowlist contains an unavailable source')
  }
  const records = []
  for (const path of files.sort()) {
    if (!validPath(path)) throw new Error(`invalid archive path: ${path}`)
    const target = outputName(path)
    if (!validPath(target) || target.startsWith('plugins/')) throw new Error(`invalid Codex archive target: ${target}`)
    records.push({ path: target.replaceAll(sep, '/'), data: await readFile(resolve(root, path)) })
  }
  const seen = new Set()
  for (const record of records) {
    if (seen.has(record.path)) throw new Error(`duplicate archive path: ${record.path}`)
    seen.add(record.path)
  }
  return records
}
