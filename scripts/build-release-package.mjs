import { execFileSync } from 'node:child_process'
import { copyFile, cp, mkdir, mkdtemp, readdir, readFile, rm, lstat, writeFile } from 'node:fs/promises'
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

const SKIP_DIRECTORY_NAMES = new Set(['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', 'tests', 'runtime', 'cache', 'credentials'])
const ALLOWED_DOT_PATHS = new Set(['plugins/dsh-kline/.codex-plugin', 'plugins/dsh-kline/.mcp.json'])
const SAFE_FILE_PATTERN = /\.(?:json|yml|yaml|md|txt|js|map|d\.ts|py|sh|html|jpg|jpeg|png)$/i

async function collectFiles(entry) {
  const source = safeSource(entry)
  const details = await lstat(source)
  if (details.isSymbolicLink()) throw new Error(`symbolic links are not distributable: ${entry}`)
  if (details.isFile()) return [entry]
  if (!details.isDirectory()) return []
  const output = []
  async function visit(directory, relativeDirectory) {
    for (const name of await readdir(directory, { withFileTypes: true })) {
      const relativePath = relativeDirectory ? `${relativeDirectory}/${name.name}` : name.name
      if ((name.name.startsWith('.') && !ALLOWED_DOT_PATHS.has(relativePath)) || SKIP_DIRECTORY_NAMES.has(name.name)) continue
      const absolutePath = join(directory, name.name)
      if (name.isDirectory()) {
        await visit(absolutePath, relativePath)
      } else if (name.isFile() && SAFE_FILE_PATTERN.test(name.name)) {
        output.push(relativePath)
      }
    }
  }
  await visit(source, entry)
  return output
}

try {
  await mkdir(packageDir, { recursive: true })
  const includes = ['package.json', ...manifest.files.filter(entry => typeof entry === 'string' && !entry.startsWith('!'))]
  const excludes = manifest.files.filter(entry => typeof entry === 'string' && entry.startsWith('!')).map(entry => entry.slice(1))
  const isExcluded = relativePath => (
    // Python bytecode is a runtime cache, not distributable source. Keep this
    // explicit rather than trusting the current checkout to be cache-free.
    relativePath.split('/').includes('__pycache__') || /\.py[cod]$/.test(relativePath)
      || excludes.some(pattern => pattern === relativePath)
  )
  const tracked = (await Promise.all(includes.map(collectFiles)))
    .flat()
    .filter(entry => !isExcluded(entry))
  for (const entry of includes) {
    if (!tracked.some(path => path === entry || path.startsWith(`${entry}/`))) {
      throw new Error(`package files entry contains no distributable files: ${entry}`)
    }
  }
  for (const entry of tracked) {
    const source = safeSource(entry)
    const target = join(packageDir, relative(root, source))
    await mkdir(dirname(target), { recursive: true })
    await cp(source, target, { preserveTimestamps: true })
  }

  // Both host descriptors travel with the same runtime. Codex copies the plugin
  // root into its cache, so nothing may point back to a source checkout or SSH host.
  for (const name of ['.codex-plugin', '.mcp.json', 'assets']) {
    await cp(join(packageDir, 'plugins/dsh-kline', name), join(packageDir, name), { recursive: true })
  }
  const pluginManifest = JSON.parse(await readFile(join(packageDir, '.codex-plugin/plugin.json'), 'utf8'))
  if (pluginManifest.version !== manifest.version) throw new Error('Codex and DSH package versions must match')
  const stagedManifest = { ...manifest, files: [...manifest.files, '.codex-plugin', '.mcp.json', 'assets'] }
  await writeFile(join(packageDir, 'package.json'), JSON.stringify(stagedManifest, null, 2) + '\n')

  if (process.argv.includes('--codex')) {
    // A Codex plugin archive has its natural folder name, while npm expects package/.
    const pluginRoot = join(scratch, 'dsh-kline')
    await cp(packageDir, pluginRoot, { recursive: true })
    await mkdir(dirname(destination), { recursive: true })
    const archive = join(scratch, 'codex.tgz')
    execFileSync('tar', ['-czf', archive, '-C', scratch, 'dsh-kline'])
    await copyFile(archive, destination)
    console.log(`Codex plugin ready: ${destination}`)
  } else {
    const output = execFileSync(
      process.platform === 'win32' ? 'npm.cmd' : 'npm',
      ['pack', '--ignore-scripts', '--json', '--pack-destination', scratch],
      { cwd: packageDir, encoding: 'utf8', shell: process.platform === 'win32' },
    )
    const packed = JSON.parse(output)[0]
    if (typeof packed?.filename !== 'string') throw new Error('npm pack returned no archive filename')

    await mkdir(dirname(destination), { recursive: true })
    await copyFile(join(scratch, packed.filename), destination)
    console.log(`Release package ready: ${destination}`)
  }
} finally {
  await rm(scratch, { recursive: true, force: true })
}
