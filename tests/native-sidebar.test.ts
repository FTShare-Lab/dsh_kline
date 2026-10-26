import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { NATIVE_TAB_ID, nativeTabDefinition, nativeTabDescription } from '../src/client/native-sidebar-contract.ts'
import { BODY_SEAT, registerNativeTab } from '../src/client/native-sidebar-register.ts'
import { KLINE_TAB_ID, KLINE_TAB_TITLE_EN, KLINE_TAB_TITLE_ZH, klineTabTitle } from '../src/client/sidebar-integration.ts'

const nativeSource = readFileSync(new URL('../src/client/native-sidebar.tsx', import.meta.url), 'utf8')
const router = readFileSync(new URL('../src/client/index.tsx', import.meta.url), 'utf8')

/** A host stand-in: records what was registered and hands the teardown back on demand. */
function fakeHost(options: { immediate?: boolean; bodyThrows?: Error } = {}) {
  const calls = { type: undefined as any, seats: [] as string[], bodies: [] as any[], opened: [] as string[], disposed: [] as string[] }
  let pending: (() => unknown) | undefined
  let cleanup: (() => void) | undefined
  const host = {
    tabs: {
      register(definition: any) {
        calls.type = definition
        return () => { calls.disposed.push('type') }
      },
    },
    navigation: {
      openTab(kind: string) { calls.opened.push(kind) },
    },
    slots: {
      inject(name: string, factory: () => unknown) {
        calls.seats.push(name)
        if (options.immediate === false) {
          pending = factory
          return () => { cleanup?.(); calls.disposed.push('seat') }
        }
        cleanup = factory() as (() => void) | undefined
        return () => { cleanup?.(); calls.disposed.push('seat') }
      },
      register(registration: any, body: unknown) {
        calls.bodies.push({ ...registration, body })
        if (options.bodyThrows) throw options.bodyThrows
        return () => { calls.disposed.push('body') }
      },
    },
  }
  return {
    host,
    calls,
    /** Play the host declaring the body seat after the plugin registered its type. */
    declareSeat() {
      if (pending === undefined) return
      const factory = pending
      pending = undefined
      cleanup = factory() as (() => void) | undefined
    },
  }
}
const settle = () => new Promise(resolve => setTimeout(resolve, 0))

test('the native tab type keeps the host kind and the product label apart', () => {
  const definition = nativeTabDefinition()
  assert.equal(definition.id, NATIVE_TAB_ID)
  assert.equal(definition.id, '@ftshare-lab/dsh-kline')
  assert.equal(definition.kind, KLINE_TAB_ID)
  assert.equal(definition.priority, 'extension')
  // Collapsing the column or switching tabs must not tear the chart down.
  assert.equal(definition.keepMounted, true)
  assert.equal(definition.title('sidebar://ftshare-kline:chart'), klineTabTitle(globalThis.navigator?.language ?? ''))
  assert.equal(klineTabTitle('zh-CN'), KLINE_TAB_TITLE_ZH)
  assert.equal(klineTabTitle('en-US'), KLINE_TAB_TITLE_EN)
  // A page type: opened by kind through openTab, never claimed by an address glob.
  assert.ok(!('patterns' in definition))
})

test('the guide entry is how a person reaches the chart without any floating launcher', () => {
  const [entry] = nativeTabDefinition().guide ?? []
  assert.ok(entry, 'the type contributes a guide entry')
  assert.equal(entry.id, NATIVE_TAB_ID)
  assert.equal(entry.order, 120)
  assert.equal(entry.title(), klineTabTitle(globalThis.navigator?.language ?? ''))
  assert.equal(entry.description?.(), nativeTabDescription(globalThis.navigator?.language ?? ''))
  assert.equal(nativeTabDescription('zh-CN'), '行情图表与关键点位分析')
  assert.equal(nativeTabDescription('en-US'), 'Market chart and key-level analysis')
})

test('both stages register as one unit and the tab opens by kind', () => {
  const { host, calls } = fakeHost()
  let changes = 0
  const tab = registerNativeTab(host as never, { body: 'BODY', onChange: () => { changes += 1 } })
  assert.equal(calls.type?.id, NATIVE_TAB_ID)
  assert.equal(calls.type?.kind, KLINE_TAB_ID)
  assert.deepEqual(calls.seats, [BODY_SEAT])
  assert.equal(calls.bodies.length, 1)
  assert.equal(calls.bodies[0].name, BODY_SEAT)
  assert.equal(calls.bodies[0].key, NATIVE_TAB_ID)
  assert.equal(calls.bodies[0].body, 'BODY')
  assert.equal(tab.available(), true)
  assert.ok(changes >= 1)
  tab.open()
  assert.deepEqual(calls.opened, [KLINE_TAB_ID])
})

test('a seat that the host declares later still becomes the body, and open waits for it', () => {
  const { host, calls, declareSeat } = fakeHost({ immediate: false })
  const tab = registerNativeTab(host as never, { body: 'BODY' })
  assert.equal(tab.available(), false, 'type alone must not claim availability')
  tab.open()
  assert.deepEqual(calls.opened, [], 'nothing to open into before the body exists')
  declareSeat()
  assert.equal(tab.available(), true)
  tab.open()
  assert.deepEqual(calls.opened, [KLINE_TAB_ID])
})

test('a failing body registration rolls the type back instead of leaving an empty pane', async () => {
  for (const immediate of [true, false]) {
    const { host, calls, declareSeat } = fakeHost({ immediate, bodyThrows: Error('seat unavailable') })
    const tab = registerNativeTab(host as never, { body: 'BODY' })
    if (!immediate) declareSeat()
    await settle()
    assert.equal(tab.available(), false, `immediate=${immediate}`)
    assert.ok(calls.disposed.includes('type'), `immediate=${immediate}: the type must be disposed`)
    tab.open()
    assert.deepEqual(calls.opened, [])
  }
})

test('dispose tears the body down before the type, and is idempotent', () => {
  const { host, calls } = fakeHost()
  let changes = 0
  const tab = registerNativeTab(host as never, { body: 'BODY', onChange: () => { changes += 1 } })
  tab.dispose()
  assert.deepEqual(calls.disposed, ['body', 'seat', 'type'])
  assert.equal(tab.available(), false)
  const seen = changes
  tab.dispose()
  assert.deepEqual(calls.disposed, ['body', 'seat', 'type'])
  assert.equal(changes, seen)
})

test('one throwing teardown does not block the rest of the rollback', () => {
  let typeDisposed = false
  const host = {
    tabs: { register() { return () => { typeDisposed = true; throw Error('type teardown failed') } } },
    navigation: { openTab() {} },
    slots: {
      inject(_name: string, factory: () => unknown) {
        const cleanup = factory() as () => void
        return () => { cleanup(); throw Error('seat teardown failed') }
      },
      register() { return () => { throw Error('body teardown failed') } },
    },
  }
  const tab = registerNativeTab(host as never, { body: 'BODY' })
  assert.doesNotThrow(() => tab.dispose())
  assert.equal(typeDisposed, true, 'the type teardown still runs after the seat teardown threw')
})

test('open never throws when the host refuses the navigation', () => {
  const { host } = fakeHost()
  host.navigation.openTab = () => { throw Error('no session on screen') }
  const tab = registerNativeTab(host as never, { body: 'BODY' })
  assert.doesNotThrow(() => tab.open())
})

test('the body receives the session through the seat inject function', () => {
  const { host, calls } = fakeHost()
  const sessions = { list: { subscribe: () => () => {}, getSnapshot: () => ({}) } }
  registerNativeTab(host as never, { body: 'BODY', bodyProps: (sessionId: string) => ({ sessionId, sessions }) })
  assert.deepEqual(calls.bodies[0].inject?.('session-1'), { sessionId: 'session-1', sessions })
})

test('without a usable host the plugin registers nothing and disposes safely', () => {
  const empty = {
    tabs: { register() { throw Error('must not register without a host') } },
    navigation: { openTab() {} },
    slots: { inject() { throw Error('must not inject without a host') }, register() { throw Error('unreachable') } },
  }
  const tab = registerNativeTab(empty as never, { body: 'BODY' })
  assert.equal(tab.available(), false)
  assert.doesNotThrow(() => tab.dispose())
})

test('the body keeps the chart mounted and passes visibility down', () => {
  assert.match(nativeSource, /const visible = useTabInfo\(\)\.tab\.visible/)
  assert.match(nativeSource, /<KlineTabContent key=\{sessionId\} sessions=\{sessions\} conversationId=\{sessionId\} visible=\{visible\} \/>/)
  assert.ok(!nativeSource.includes('{visible && <KlineTabContent'))
})

test('the launcher follows Sessions, not the host UI language, and auto-open stays in tab mode', () => {
  assert.match(router, /const showClassicLauncher = mode === 'classic' \|\| conversation === undefined/)
  assert.match(router, /\{nativeTab && mode === 'better-sidebar' && <NativeSidebarBridgeView bridge=\{native\} sessions=\{ctx\.sessions\} \/>\}/)
  assert.ok(!router.includes('hostRightSidebarAvailable'))
  assert.ok(!router.includes('Open right sidebar'))
  assert.ok(!router.includes('Collapse right sidebar'))
  assert.match(router, /cleanClassicTabs\(service\)/)
})
