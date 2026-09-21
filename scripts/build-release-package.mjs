import { execFileSync } from 'node:child_process'
import { copyFile, cp, mkdir, mkdtemp, readdir, readFile, rm, lstat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const manifest = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
const codex = process.argv.includes('--codex')
const destination = resolve(process.argv.find(argument => !argument.startsWith('--') && argument !== process.argv[0] && argument !== process.argv[1]) ?? join(root, 'release', codex ? 'dsh-kline-codex.tgz' : 'dsh-kline.tgz'))
const scratch = await mkdtemp(join(tmpdir(), 'dsh-kline-release-'))
const packageDir = join(scratch, 'package')

// These are deliberately separate allowlists. A DeepSeek Harness install must
// not receive Codex UI/manifest assets, while a Codex plugin must not receive
// the Cordis patch or DSH sidebar bundle. Shared application/runtime modules
// appear in both lists exactly once.
const SHARED_RUNTIME = [
  'LICENSE', 'PROVENANCE.md', 'README.en.md', 'README.md', 'requirements.txt',
  'server.py', 'core', 'services', 'tools', 'config/basic-symbols.json',
  'adapters/__init__.py', 'adapters/host.py', 'scripts/bootstrap.sh', 'scripts/run-dsh-kline.mjs',
]
const DSH_FILES = [
  ...SHARED_RUNTIME, 'CHANGELOG.md', 'chart_service.py', 'cordis.patch.yml',
  'docs/images', 'lib', 'screenshots.json', 'scripts/run-dsh-kline.sh', 'view',
]
const CODEX_FILES = [
  ...SHARED_RUNTIME, 'CHANGELOG.md', 'docs/codex-adapter.md',
  'adapters/mcp_apps.py', 'adapters/mcp-app-bridge.js', 'scripts/run-codex-kline.mjs', 'view',
]
const includes = codex ? CODEX_FILES : DSH_FILES
const FORBIDDEN = codex
  ? ['chart_service.py', 'cordis.patch.yml', 'lib', 'screenshots.json', 'plugins']
  : ['adapters/mcp_apps.py', 'adapters/mcp-app-bridge.js', 'scripts/run-codex-kline.mjs', 'plugins', '.codex-plugin', '.mcp.json', 'docs/codex-adapter.md']
const SKIP_DIRECTORY_NAMES = new Set(['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', 'tests', 'runtime', 'cache', 'credentials'])
const SAFE_FILE_PATTERN = /\.(?:json|yml|yaml|md|txt|js|map|d\.ts|py|sh|html|jpg|jpeg|png)$/i

function safeSource(entry) {
  if (typeof entry !== 'string' || entry === '' || isAbsolute(entry)) throw new Error(`invalid package file entry: ${JSON.stringify(entry)}`)
  const source = resolve(root, entry)
  if (source !== root && !source.startsWith(root + sep)) throw new Error(`package file entry escapes the repository: ${entry}`)
  return source
}

async function collectFiles(entry) {
  const source = safeSource(entry)
  const details = await lstat(source)
  if (details.isSymbolicLink()) throw new Error(`symbolic links are not distributable: ${entry}`)
  if (details.isFile()) return [entry]
  if (!details.isDirectory()) return []
  const output = []
  async function visit(directory, relativeDirectory) {
    for (const name of await readdir(directory, { withFileTypes: true })) {
      const relativePath = `${relativeDirectory}/${name.name}`
      if (name.name.startsWith('.') || SKIP_DIRECTORY_NAMES.has(name.name)) continue
      const absolutePath = join(directory, name.name)
      if (name.isDirectory()) await visit(absolutePath, relativePath)
      else if (name.isFile() && SAFE_FILE_PATTERN.test(name.name)) output.push(relativePath)
    }
  }
  await visit(source, entry)
  return output
}

function isForbidden(relativePath) {
  const segments = relativePath.split('/')
  return segments.includes('__pycache__') || /\.py[cod]$/.test(relativePath)
    || FORBIDDEN.some(entry => relativePath === entry || relativePath.startsWith(`${entry}/`))
}

try {
  await mkdir(packageDir, { recursive: true })
  const tracked = (await Promise.all(includes.map(collectFiles))).flat().filter(path => !isForbidden(path))
  for (const entry of includes) {
    if (!tracked.some(path => path === entry || path.startsWith(`${entry}/`))) throw new Error(`package file entry contains no distributable files: ${entry}`)
  }
  for (const entry of tracked) {
    const target = join(packageDir, entry)
    await mkdir(dirname(target), { recursive: true })
    await cp(safeSource(entry), target, { preserveTimestamps: true })
  }

  if (codex) {
    for (const entry of ['.codex-plugin', '.mcp.json', 'assets']) {
      await cp(join(root, 'plugins/dsh-kline', entry), join(packageDir, entry), { recursive: true })
    }
    const pluginManifest = JSON.parse(await readFile(join(packageDir, '.codex-plugin/plugin.json'), 'utf8'))
    if (pluginManifest.version !== manifest.version) throw new Error('Codex plugin and package versions must match')
  }
  const stagedManifest = { ...manifest, files: includes }
  if (codex) delete stagedManifest.dsh
  await writeFile(join(packageDir, 'package.json'), JSON.stringify(stagedManifest, null, 2) + '\n')

  if (codex) {
    const pluginRoot = join(scratch, 'dsh-kline')
    await cp(packageDir, pluginRoot, { recursive: true })
    await mkdir(dirname(destination), { recursive: true })
    const archive = join(scratch, 'codex.tgz')
    execFileSync('tar', ['-czf', archive, '-C', scratch, 'dsh-kline'])
    await copyFile(archive, destination)
    console.log(`Codex plugin ready: ${destination}`)
  } else {
    const output = execFileSync(process.platform === 'win32' ? 'npm.cmd' : 'npm',
      ['pack', '--ignore-scripts', '--json', '--pack-destination', scratch],
      { cwd: packageDir, encoding: 'utf8', shell: process.platform === 'win32' })
    const packed = JSON.parse(output)[0]
    if (typeof packed?.filename !== 'string') throw new Error('npm pack returned no archive filename')
    await mkdir(dirname(destination), { recursive: true })
    await copyFile(join(scratch, packed.filename), destination)
    console.log(`Release package ready: ${destination}`)
  }
} finally {
  await rm(scratch, { recursive: true, force: true })
}
