import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { testPythonExecutable, isolatedTestEnvironment, PROJECT_ROOT } from '../scripts/test-runtime.mjs'
import { discoverNodeTests, testSuites, runTestSuites } from '../scripts/run-tests.mjs'

test('shared test Python resolution honors explicit overrides and native venv paths, without probing', () => {
  for (const platform of ['darwin', 'linux', 'win32']) {
    const checked = []
    const python = testPythonExecutable({ env: {}, platform, root: PROJECT_ROOT, exists: path => { checked.push(path); return true } })
    assert.equal(python, resolve(PROJECT_ROOT, '.venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python'])))
    assert.equal(checked.length, 1)
    assert.equal(testPythonExecutable({ env: {}, platform, exists: () => false }), platform === 'win32' ? 'python' : 'python3')
    assert.equal(testPythonExecutable({ env: { DSH_KLINE_TEST_PYTHON: 'python with spaces' }, platform,
      exists: () => assert.fail('explicit override cannot silently fall back') }), 'python with spaces')
  }
})

test('test subprocess environment does not inherit live credentials, host identity or cache locations', () => {
  const original = { FTSHARE_API_KEY: 'test-secret', FTSHARE_API_KEY_FILE: 'live-key-file',
    DSH_KLINE_SETTINGS_KEY_FILE: 'live-bridge', DSH_KLINE_HOST_PID: '42', DSH_KLINE_RUNTIME_DIR: 'live-runtime',
    DSH_KLINE_CACHE_DIR: 'live-cache', PATH: 'kept', PYTHONUTF8: '0' }
  const isolated = isolatedTestEnvironment(original, join(tmpdir(), 'test-owned'), 'python')
  for (const key of ['FTSHARE_API_KEY','DSH_KLINE_SETTINGS_KEY_FILE','DSH_KLINE_HOST_PID']) assert.equal(key in isolated, false)
  assert.ok(!JSON.stringify(isolated).includes('live-')); assert.ok(!JSON.stringify(isolated).includes('test-secret'))
  assert.equal(isolated.PATH, 'kept'); assert.equal(isolated.PYTHONUTF8, '1')
  assert.equal(isolated.DSH_KLINE_TEST_PYTHON, 'python'); assert.equal(original.FTSHARE_API_KEY, 'test-secret')
})

test('test discovery includes every top-level TS/MJS test in sorted explicit arguments, not a shell glob', () => {
  const directory = mkdtempSync(join(tmpdir(), 'kline-test-discovery-'))
  try {
    mkdirSync(join(directory, 'tests'))
    assert.throws(() => discoverNodeTests(directory), /No JavaScript/)
    for (const name of ['b.test.ts','a space.test.mjs','ignored.ts','test_python.py']) writeFileSync(join(directory, 'tests', name), '')
    mkdirSync(join(directory, 'tests', 'not-a-file.test.ts'))
    const files = discoverNodeTests(directory)
    assert.deepEqual(files, ['a space.test.mjs','b.test.ts'].map(name => join(directory, 'tests', name)))
    assert.deepEqual(testSuites([], 'python', files).map(s => s.name), ['JavaScript / TypeScript','Python'])
    assert.deepEqual(testSuites(['--node'], 'python', files)[0].args, ['--test', ...files])
    assert.deepEqual(testSuites(['--python'], 'python', files), [{ name: 'Python', command: 'python', args: ['-m','pytest','-q'] }])
    assert.throws(() => testSuites(['--bad'], 'python', files), /Usage/)
    assert.throws(() => testSuites(['--node','--python'], 'python', files), /Usage/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})

test('test runner preserves failure or interruption and never silently skips a failed suite', () => {
  const suites = testSuites([], 'python', ['one file.test.ts'])
  const quiet = {log() {}, error() {}}
  for (const failure of [{ status: 7 }, { status: null, signal: 'SIGTERM' }, { status: null, error: Error('fixture') }]) {
    let count = 0
    assert.equal(runTestSuites(suites, { cwd: PROJECT_ROOT }, (command, args, options) => {
      count++; assert.equal(command, process.execPath); assert.deepEqual(args, ['--test','one file.test.ts'])
      assert.equal(options.shell, false); return failure
    }, quiet), failure.status === 7 ? 7 : 1)
    assert.equal(count, 1)
  }
  let count = 0
  assert.equal(runTestSuites(suites, {}, () => { count++; return { status: 0 } }, quiet), 0)
  assert.equal(count, 2)
})

test('local and both CI workflows share the full-suite command and no test files are omitted', () => {
  const expected = readdirSync(join(PROJECT_ROOT, 'tests')).filter(name => /\.test\.(?:ts|mjs)$/.test(name)).sort()
  assert.deepEqual(discoverNodeTests().map(path => path.slice(join(PROJECT_ROOT, 'tests').length + 1)), expected)
  const pkg = JSON.parse(readFileSync(join(PROJECT_ROOT, 'package.json'), 'utf8'))
  assert.equal(pkg.scripts.test, 'node ./scripts/run-tests.mjs')
  for (const workflow of ['install.yml','release.yml']) {
    const yaml = readFileSync(join(PROJECT_ROOT, '.github','workflows', workflow), 'utf8')
    assert.match(yaml, /DSH_KLINE_TEST_PYTHON: python\s+run: pnpm test/)
    assert.ok(yaml.indexOf('Verify all Node and Python behavior') < yaml.indexOf('pnpm pack:release'))
  }
})
