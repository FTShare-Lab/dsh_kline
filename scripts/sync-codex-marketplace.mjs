import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { codexPackageFiles } from './codex-package-files.mjs'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const check = process.argv.slice(2).includes('--check')
if (process.argv.slice(2).some(arg => arg !== '--check')) throw new Error('Usage: node scripts/sync-codex-marketplace.mjs [--check]')
const catalog = JSON.parse(await readFile(resolve(root, '.agents/plugins/marketplace.json'), 'utf8'))
const entry = catalog.plugins?.find(plugin => plugin.name === 'ft-kline')
if (catalog.name !== 'ftshare' || entry?.source?.source !== 'local' || entry.source.path !== './marketplace/ft-kline' ||
    entry.policy?.installation !== 'AVAILABLE' || !entry.category) throw new Error('Invalid public FTShare marketplace entry')
const destination = resolve(root, entry.source.path)
const records = await codexPackageFiles(root)
const expected = new Set(records.map(record => record.path))
async function files(directory, prefix = '') {
  let entries
  try { entries = await readdir(directory, { withFileTypes: true }) }
  catch (error) { if (error.code === 'ENOENT') return []; throw error }
  const result = []
  for (const entry of entries) {
    if (entry.name === '__pycache__' || /\.py[cod]$/.test(entry.name)) continue
    const name = prefix + entry.name
    if (entry.isDirectory()) result.push(...await files(resolve(directory, entry.name), `${name}/`))
    else result.push(name)
  }
  return result
}
// Never silently delete an unknown file from a developer's checkout.
const extra = (await files(destination)).filter(name => !expected.has(name))
if (extra.length) throw new Error(`Unexpected marketplace snapshot files; review before removing: ${extra.join(', ')}`)
const stale = []
for (const record of records) {
  const target = resolve(destination, record.path)
  let current
  try { current = await readFile(target) }
  catch (error) { if (error.code !== 'ENOENT') throw error }
  if (current?.equals(record.data)) continue
  if (check) stale.push(record.path)
  else { await mkdir(dirname(target), { recursive: true }); await writeFile(target, record.data) }
}
if (stale.length) throw new Error(`Stale public plugin snapshot (${stale.join(', ')}). Run pnpm sync:codex-marketplace and commit the result.`)
console.log(`Public FTShare marketplace ${check ? 'verified' : 'synchronized'}: ${records.length} standalone plugin files`)
