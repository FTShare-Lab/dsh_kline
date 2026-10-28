import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const manifest = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'))
const destination = resolve(process.argv[2] ?? resolve(root, 'release', `ft-kline-v${manifest.version}.zip`))

// This is intentionally independent from package.json's DSH npm allowlist.
// A Codex archive must not accidentally inherit a loopback server, DSH client,
// Cordis patch, or DSH credential bridge as the project grows.
const allowlist = [
  'CHANGELOG.md', 'LICENSE', 'README.md', 'README.en.md', 'package.json', 'requirements.txt',
  'docs/release-notes-v0.6.0.md', 'docs/release-acceptance-v0.6.0.md',
  'codex_server.py', 'codex_runtime', 'core', 'config/basic-symbols.json', 'view',
  // Only provider/indicator/geometry modules shared by the Codex adapter.
  // DSH context, HTTP application, and snapshot modules are intentionally not
  // present in this archive.
  'tools/annotations.py', 'tools/calc.py', 'tools/chart_indicators.py', 'tools/channels.py', 'tools/channel_candidates.py',
  'tools/draw.py', 'tools/fetch.py', 'tools/fibonacci.py', 'tools/free_sources.py', 'tools/lines.py',
  'tools/pivots.py', 'tools/polylines.py', 'tools/price_bands.py', 'tools/price_series.py',
  'tools/price_sticks.py', 'tools/range_candidates.py', 'tools/rectangles.py', 'tools/trend_lines.py',
  'scripts/run-dsh-kline.mjs', 'scripts/run-ft-kline.mjs', 'scripts/run-ft-kline-cli.mjs',
  'plugins/ft-kline/plugin.json', 'plugins/ft-kline/.codex-plugin/plugin.json',
  'plugins/ft-kline/mcp.json', 'plugins/ft-kline/.mcp.json', 'plugins/ft-kline/assets',
]
const remap = new Map([
  ['plugins/ft-kline/plugin.json', 'plugin.json'],
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
function crc32(data) {
  let crc = 0xffffffff
  for (const byte of data) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  return (crc ^ 0xffffffff) >>> 0
}
function dosTime(date) {
  const year = Math.max(1980, date.getFullYear())
  return { time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate() }
}
function localHeader(name, data, crc, stamp) {
  const buffer = Buffer.alloc(30 + name.length)
  buffer.writeUInt32LE(0x04034b50, 0); buffer.writeUInt16LE(20, 4); buffer.writeUInt16LE(0x800, 6)
  buffer.writeUInt16LE(0, 8); buffer.writeUInt16LE(stamp.time, 10); buffer.writeUInt16LE(stamp.date, 12)
  buffer.writeUInt32LE(crc, 14); buffer.writeUInt32LE(data.length, 18); buffer.writeUInt32LE(data.length, 22)
  buffer.writeUInt16LE(name.length, 26); buffer.writeUInt16LE(0, 28); name.copy(buffer, 30)
  return buffer
}
function centralHeader(name, data, crc, stamp, offset) {
  const buffer = Buffer.alloc(46 + name.length)
  buffer.writeUInt32LE(0x02014b50, 0); buffer.writeUInt16LE(0x0314, 4); buffer.writeUInt16LE(20, 6)
  buffer.writeUInt16LE(0x800, 8); buffer.writeUInt16LE(0, 10); buffer.writeUInt16LE(stamp.time, 12); buffer.writeUInt16LE(stamp.date, 14)
  buffer.writeUInt32LE(crc, 16); buffer.writeUInt32LE(data.length, 20); buffer.writeUInt32LE(data.length, 24)
  buffer.writeUInt16LE(name.length, 28); buffer.writeUInt16LE(0, 30); buffer.writeUInt16LE(0, 32); buffer.writeUInt16LE(0, 34)
  buffer.writeUInt16LE(0, 36); buffer.writeUInt32LE(0, 38); buffer.writeUInt32LE(offset, 42); name.copy(buffer, 46)
  return buffer
}
function endOfDirectory(count, size, offset) {
  const buffer = Buffer.alloc(22)
  buffer.writeUInt32LE(0x06054b50, 0); buffer.writeUInt16LE(0, 4); buffer.writeUInt16LE(0, 6)
  buffer.writeUInt16LE(count, 8); buffer.writeUInt16LE(count, 10); buffer.writeUInt32LE(size, 12); buffer.writeUInt32LE(offset, 16); buffer.writeUInt16LE(0, 20)
  return buffer
}

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
  records.push({ name: Buffer.from(target.replaceAll(sep, '/')), data: await readFile(resolve(root, path)) })
}
const seen = new Set()
for (const record of records) {
  if (seen.has(record.name.toString())) throw new Error(`duplicate archive path: ${record.name}`)
  seen.add(record.name.toString())
}
// The release workflow records a SHA-256 of this archive. Fixed ZIP metadata
// makes a rebuild of unchanged source reproduce that asset exactly.
const now = dosTime(new Date(Date.UTC(2026, 0, 1, 0, 0, 0)))
let offset = 0; const locals = [], central = []
for (const record of records) {
  const crc = crc32(record.data); const local = localHeader(record.name, record.data, crc, now)
  locals.push(local, record.data); central.push(centralHeader(record.name, record.data, crc, now, offset)); offset += local.length + record.data.length
}
const centralSize = central.reduce((total, item) => total + item.length, 0)
await mkdir(dirname(destination), { recursive: true }); await rm(destination, { force: true })
await writeFile(destination, Buffer.concat([...locals, ...central, endOfDirectory(records.length, centralSize, offset)]))
console.log(`Codex package ready: ${destination}`)
console.log(`SHA-256 ${createHash('sha256').update(await readFile(destination)).digest('hex')}`)
