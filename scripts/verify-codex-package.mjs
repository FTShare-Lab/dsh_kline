import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const archive = resolve(process.argv[2] ?? `${root}/release/ft-kline-v0.6.0.zip`)
const data = await readFile(archive)
const end = data.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
if (end < 0) throw new Error('not a ZIP archive')
const count = data.readUInt16LE(end + 10), centralOffset = data.readUInt32LE(end + 16)
let cursor = centralOffset; const names = new Set(), entries = new Map()
for (let index = 0; index < count; index += 1) {
  if (data.readUInt32LE(cursor) !== 0x02014b50) throw new Error('invalid ZIP central directory')
  const length = data.readUInt16LE(cursor + 28), extra = data.readUInt16LE(cursor + 30), comment = data.readUInt16LE(cursor + 32)
  const name = data.subarray(cursor + 46, cursor + 46 + length).toString('utf8')
  names.add(name)
  entries.set(name, {
    method: data.readUInt16LE(cursor + 10),
    size: data.readUInt32LE(cursor + 20),
    mode: data.readUInt32LE(cursor + 38) >>> 16,
    offset: data.readUInt32LE(cursor + 42),
  })
  cursor += 46 + length + extra + comment
}
function readStoredEntry(name) {
  const entry = entries.get(name)
  if (!entry) throw new Error(`Codex package missing ${name}`)
  if (entry.method !== 0 || data.readUInt32LE(entry.offset) !== 0x04034b50) throw new Error(`unsupported ZIP entry ${name}`)
  const length = data.readUInt16LE(entry.offset + 26), extra = data.readUInt16LE(entry.offset + 28)
  return data.subarray(entry.offset + 30 + length + extra, entry.offset + 30 + length + extra + entry.size)
}
for (const required of ['plugin.json', '.codex-plugin/plugin.json', 'mcp.json', '.mcp.json', 'codex_server.py', 'codex_runtime/state.py', 'scripts/run-ft-kline.mjs', 'tools/baostock_source.py', 'tools/draw.py', 'tools/chart_indicators.py', 'view/kline.html', 'assets/ft-kline.svg', 'docs/release-notes-v0.6.0.md', 'docs/release-acceptance-v0.6.0.md']) {
  if (!names.has(required)) throw new Error(`Codex package missing ${required}`)
}
if ([...entries.values()].some(entry => entry.mode !== 0o100644)) throw new Error('Codex package entries must extract as readable regular files')
for (const forbidden of ['chart_service.py', 'server.py', 'cordis.patch.yml', 'config/dsh-kline.patch.yml', 'scripts/run-dsh-kline.sh']) {
  if (names.has(forbidden)) throw new Error(`Codex package is not isolated: ${forbidden}`)
}
if ([...names].some(name => name.endsWith('.app.json') || name.startsWith('hooks/'))) throw new Error('Codex package contains forbidden host hooks')
const packageManifest = JSON.parse(readStoredEntry('package.json'))
const pluginManifests = ['plugin.json', '.codex-plugin/plugin.json'].map(name => JSON.parse(readStoredEntry(name)))
for (const manifest of pluginManifests) {
  if (manifest.name !== 'ft-kline' || manifest.version !== packageManifest.version) throw new Error('Codex plugin ID/version is not synchronized')
}
const resourceUri = pluginManifests[0]?.extensions?.['com.openai']?.mcpApps?.resourceUri
if (resourceUri !== 'ui://ft-kline/chart-v3' || !readStoredEntry('codex_runtime/state.py').toString('utf8').includes(`APP_RESOURCE_URI = "${resourceUri}"`)) {
  throw new Error('Codex chart resource URI is not synchronized')
}
for (const name of ['mcp.json', '.mcp.json']) {
  const server = JSON.parse(readStoredEntry(name))?.mcpServers?.['ft-kline']
  if (server?.type !== 'stdio' || server?.command !== 'node' || JSON.stringify(server?.args) !== JSON.stringify(['${PLUGIN_ROOT}/scripts/run-ft-kline.mjs'])) {
    throw new Error(`${name} does not use the isolated PLUGIN_ROOT launcher`)
  }
  if (server?.env?.FT_KLINE_CLIENT !== 'desktop' || server?.env?.FT_KLINE_CODEX_MEMORY_ONLY !== '1') throw new Error(`${name} is missing Codex isolation flags`)
}
console.log(`Codex package verified: ${archive} (${names.size} files)`)
