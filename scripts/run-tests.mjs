import { readdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import { PROJECT_ROOT, testPythonExecutable, isolatedTestEnvironment } from './test-runtime.mjs'

export function discoverNodeTests(root = PROJECT_ROOT) {
  const files = readdirSync(join(root, 'tests'), { withFileTypes: true })
    .filter(entry => entry.isFile() && /\.test\.(?:ts|mjs)$/.test(entry.name))
    .map(entry => join(root, 'tests', entry.name)).sort()
  if (!files.length) throw Error('No JavaScript/TypeScript test files found')
  return files
}

export function testSuites(args, python, files) {
  if (args.length > 1 || args.length === 1 && !['--node', '--python'].includes(args[0])) {
    throw Error('Usage: node scripts/run-tests.mjs [--node|--python]')
  }
  return [
    ...(!args.includes('--python') ? [{ name: 'JavaScript / TypeScript', command: process.execPath, args: ['--test', '--test-concurrency=2', ...files] }] : []),
    ...(!args.includes('--node') ? [{ name: 'Python', command: python, args: ['-m', 'pytest', '-q'] }] : []),
  ]
}

export function runTestSuites(suites, options, spawn = spawnSync, log = console) {
  for (const suite of suites) {
    log.log(`Running ${suite.name} tests`)
    const result = spawn(suite.command, suite.args, { ...options, stdio: 'inherit', shell: false, windowsHide: true })
    if (result.error || result.signal || result.status !== 0) {
      log.error(`${suite.name} tests did not pass${result.signal ? ` (${result.signal})` : ''}.`)
      if (result.error) log.error('Could not start test process; check Node/Python availability and DSH_KLINE_TEST_PYTHON.')
      return Number.isInteger(result.status) && result.status > 0 ? result.status : 1
    }
  }
  return 0
}

export function main(args = process.argv.slice(2)) {
  const python = testPythonExecutable()
  const suites = testSuites(args, python, discoverNodeTests())
  const directory = mkdtempSync(join(tmpdir(), 'dsh-kline-tests-'))
  try {
    return runTestSuites(suites, { cwd: PROJECT_ROOT, env: isolatedTestEnvironment(process.env, directory, python) })
  } finally {
    // This exact directory was created for this run; never clean a user cache.
    rmSync(directory, { recursive: true, force: true })
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { process.exitCode = main() }
  catch (error) { console.error(error.message); process.exitCode = 1 }
}
