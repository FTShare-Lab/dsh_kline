import { execFileSync } from 'node:child_process'
import { copyFile, cp, mkdir, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const manifest = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
if (!Array.isArray(manifest.files) || manifest.files.length === 0) {
  throw new Error('package.json must declare a non-empty files allowlist')
}

const destination = resolve(process.argv[2] ?? join(root, 'release', 'dsh-kline.tgz'))
const scratch = await mkdtemp(join(tmpdir(), 'dsh-kline-release-'))
const packageDir = join(scratch, 'package')

function safeSource(entry) {
  if (typeof entry !== 'string' || entry === '' || isAbsolute(entry)) {
    throw new Error(`invalid package files entry: ${JSON.stringify(entry)}`)
  }
  const source = resolve(root, entry)
  if (source !== root && !source.startsWith(root + sep)) {
    throw new Error(`package files entry escapes the repository: ${entry}`)
  }
  return source
}

try {
  await mkdir(packageDir, { recursive: true })
  const allowlist = ['package.json', ...manifest.files]
  const tracked = execFileSync(
    'git',
    ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', ...allowlist],
    { cwd: root },
  )
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
  for (const entry of allowlist) {
    if (!tracked.some(path => path === entry || path.startsWith(`${entry}/`))) {
      throw new Error(`package files entry contains no tracked files: ${entry}`)
    }
  }
  for (const entry of tracked) {
    const source = safeSource(entry)
    const target = join(packageDir, relative(root, source))
    await mkdir(dirname(target), { recursive: true })
    await cp(source, target, { preserveTimestamps: true })
  }

  const output = execFileSync(
    process.platform === 'win32' ? 'npm.cmd' : 'npm',
    ['pack', '--ignore-scripts', '--json', '--pack-destination', scratch],
    { cwd: packageDir, encoding: 'utf8', shell: process.platform === 'win32' },
  )
  const packed = JSON.parse(output)[0]
  if (typeof packed?.filename !== 'string') throw new Error('npm pack returned no archive filename')

  await mkdir(dirname(destination), { recursive: true })
  await rm(destination, { force: true })
  await copyFile(join(scratch, packed.filename), destination)
  console.log(`Release package ready: ${destination}`)
} finally {
  await rm(scratch, { recursive: true, force: true })
}
