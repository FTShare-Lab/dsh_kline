import { createHash } from 'node:crypto'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { codexPackageFiles } from './codex-package-files.mjs'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const manifest = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'))
const destination = resolve(process.argv[2] ?? resolve(root, 'release', `ft-kline-v${manifest.version}.zip`))

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
  // Mark all archive entries as regular, owner-readable source files. Without
  // this POSIX external attribute macOS `unzip` restores files as mode 000,
  // which prevents Codex from reading plugin.json after a fresh install.
  buffer.writeUInt16LE(0, 36); buffer.writeUInt32LE(0o100644 * 0x10000, 38); buffer.writeUInt32LE(offset, 42); name.copy(buffer, 46)
  return buffer
}
function endOfDirectory(count, size, offset) {
  const buffer = Buffer.alloc(22)
  buffer.writeUInt32LE(0x06054b50, 0); buffer.writeUInt16LE(0, 4); buffer.writeUInt16LE(0, 6)
  buffer.writeUInt16LE(count, 8); buffer.writeUInt16LE(count, 10); buffer.writeUInt32LE(size, 12); buffer.writeUInt32LE(offset, 16); buffer.writeUInt16LE(0, 20)
  return buffer
}

const records = (await codexPackageFiles(root)).map(record => ({ name: Buffer.from(record.path), data: record.data }))
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
