import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { readDisplayMode, resolveDisplayMode, readAutoOpen, DISPLAY_MODE_KEY, UI_SEEN_KEY, AUTO_OPEN_KEY } from '../src/client/mode-preferences.ts'
import { hasPreviousUsage, classifyOnboarding, acknowledgeOnboarding, ONBOARDING_KEY } from '../src/client/ui-onboarding.ts'
import { cleanClassicTabs, isSidebarUsable, KLINE_TAB_ID, KLINE_TAB_TITLE, migrateKlineTabTitle } from '../src/client/sidebar-integration.ts'
import type { BetterSidebarService } from 'dsh-better-sidebar'
import { isNewerStableVersion } from '../src/client/version.ts'

function storage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial))
  return { get length() { return data.size }, key: i => [...data.keys()][i] ?? null,
    getItem: key => data.get(key) ?? null, setItem: (key, value) => { data.set(key, value) },
    removeItem: key => { data.delete(key) }, clear: () => data.clear() }
}
for (const preference of ['auto', 'classic', 'better-sidebar'] as const) {
  for (const available of [false, true]) test(`${preference}, sidebar ${available}: one deterministic shell`, () => {
    assert.equal(resolveDisplayMode(preference, available), available && preference !== 'classic' ? 'better-sidebar' : 'classic')
  })
}
test('missing, corrupt and inaccessible preference storage safely defaults to automatic', () => {
  assert.equal(readDisplayMode(storage()), 'auto')
  assert.equal(readDisplayMode(storage({[DISPLAY_MODE_KEY]: 'unknown'})), 'auto')
  assert.equal(readDisplayMode({getItem() { throw Error('denied') }} as unknown as Storage), 'auto')
  assert.equal(readDisplayMode(storage({[DISPLAY_MODE_KEY]: 'better-sidebar'})), 'better-sidebar')
})
test('auto-open is independent from display mode', () => {
  const s = storage({[DISPLAY_MODE_KEY]: 'classic', [AUTO_OPEN_KEY]: 'false'})
  assert.equal(readAutoOpen(s), false)
  s.setItem(DISPLAY_MODE_KEY, 'better-sidebar')
  assert.equal(readAutoOpen(s), false)
  assert.equal(readAutoOpen(storage()), true)
})
test('first-install and legacy users receive different onboarding', () => {
  assert.equal(hasPreviousUsage(storage()), false)
  for (const entry of [{'dsh_kline_welcome_seen_v1':'1'}, {'dsh-kline:conversation:A':'{}'}, {'dsh-kline.workspace.v1':'{}'}]) {
    assert.equal(hasPreviousUsage(storage(entry)), true)
  }
  assert.equal(classifyOnboarding(storage(), false), 'first')
  assert.equal(classifyOnboarding(storage(), true), 'upgrade')
})
test('acknowledging onboarding is once per device and does not erase chart or key state', () => {
  const s = storage({'dsh-kline:conversation:A':'snapshot', 'dsh-kline.workspace.v1':'drawings', 'credential':'unchanged'})
  acknowledgeOnboarding(s)
  assert.equal(s.getItem(UI_SEEN_KEY), '1')
  assert.equal(s.getItem(ONBOARDING_KEY), '0.2.0')
  assert.equal(classifyOnboarding(s, false), 'none')
  assert.equal(classifyOnboarding(s, true), 'none')
  assert.equal(s.getItem('dsh-kline:conversation:A'), 'snapshot')
  assert.equal(s.getItem('dsh-kline.workspace.v1'), 'drawings')
  assert.equal(s.getItem('credential'), 'unchanged')
})
const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
test('UI entry is text only, remains visible on narrow screens, and retains the product name', () => {
  const button = html.match(/<button[^>]*id="interfaceBtn"[^>]*>(.*?)<\/button>/)?.[1]
  assert.equal(button, '<span data-i18n="interfaceLabel">UI</span>')
  assert.ok(!html.includes('interface-label') && !html.includes('interface-new'))
  assert.ok(html.includes('productName: "非凸K线助手"'))
  assert.ok(html.includes('productName: "dsh_kline"'))
  const tab = readFileSync(new URL('../src/client/BetterSidebarTab.tsx', import.meta.url), 'utf8')
  assert.ok(tab.includes('title: KLINE_TAB_TITLE'))
  assert.equal(KLINE_TAB_TITLE, '非凸K线助手 / dsh_kline')
  assert.ok(tab.includes('const dispose = service.registerTab(') && tab.includes('stopDefaults(); dispose()'))
  assert.match(tab, /service\.subscribeState\(listener\)/)
  assert.match(tab, /sidebar\.sessionId === scope\.sessionId/)
  assert.match(tab, /only an analysis result that arrives while this view is live may/)
})
test('saved legacy titles migrate only in their own active session and preserve custom names', () => {
  const updates: unknown[] = []
  const service = {features:['updateTab','stateSubscription'], getSnapshot:() => ({sessionId:'A'}),
    updateTab:(...args: unknown[]) => updates.push(args)} as unknown as BetterSidebarService
  const tab = {id:'kline',type:KLINE_TAB_ID,title:'K线分析 / K-line'}
  migrateKlineTabTitle(service, tab, 'B')
  migrateKlineTabTitle(service, {...tab,title:'我的研究'}, 'A')
  migrateKlineTabTitle(service, {...tab,type:'editor'}, 'A')
  assert.equal(updates.length, 0)
  migrateKlineTabTitle(service, tab, 'A')
  assert.deepEqual(updates, [['kline',{title:KLINE_TAB_TITLE}]])
})
test('interface popup stays inside a narrow chart even when the trigger is not at its right edge', () => {
  const start = html.indexOf('function positionInterfacePopover()')
  const end = html.indexOf('\nfunction initInterfaceControls', start)
  const panel = {offsetWidth:350, style:{} as Record<string,string>}
  const elements = {viewShell:{getBoundingClientRect: () => ({top:0,right:390,width:390,height:600})}, interfaceBtn:{getBoundingClientRect: () => ({bottom:40,right:328})}, interfacePopover:panel}
  const position = runInNewContext(`(${html.slice(start,end)})`, {document:{getElementById:(id: keyof typeof elements) => elements[id]}})
  position()
  assert.equal(panel.style.right, '28px')
  assert.equal(panel.style.top, '46px')
  assert.equal(panel.style.maxHeight, '542px')
})
test('missing or older sidebar APIs never block the classic shell', () => {
  assert.equal(isSidebarUsable(), false)
  assert.equal(isSidebarUsable({registerTab() {}, openTab() {}, features:[]} as unknown as BetterSidebarService), false)
  assert.equal(isSidebarUsable({registerTab() {}, openTab() {}, features:['targetedOpen']} as unknown as BetterSidebarService), true)
})
test('RC users can see the stable release without treating older stable or another RC as an upgrade', () => {
  assert.equal(isNewerStableVersion('0.2.0', '0.2.0-rc.1'), true)
  assert.equal(isNewerStableVersion('0.2.0', '0.2.0'), false)
  assert.equal(isNewerStableVersion('0.1.8', '0.2.0-rc.1'), false)
  assert.equal(isNewerStableVersion('0.2.0-rc.2', '0.2.0-rc.1'), false)
  assert.equal(isNewerStableVersion('0.2.1', '0.2.0'), true)
})
test('classic mode removes only owned stale tabs in every public layout and respects disposal', async () => {
  const tab = (id: string, type = KLINE_TAB_ID) => ({id, type})
  let listener = () => {}, unsubscribed = false
  const closed: unknown[] = []
  const state = {splits:{kind:'split', children:[{kind:'leaf', tabs:[tab('right'), tab('file','editor')]}]}, bottomSplits:{kind:'leaf', tabs:[tab('bottom')]}, floats:[{tab:tab('float')}, {tab:tab('terminal','terminal')}]}
  const service = {features:['stateSubscription'], getSnapshot: () => ({sessionId:'A', state}), subscribeState: (fn: () => void) => {listener = fn; return () => {unsubscribed = true}}, closeTab:(id: string, scope: unknown) => closed.push([id,scope])} as unknown as BetterSidebarService
  const dispose = cleanClassicTabs(service)
  await Promise.resolve()
  assert.deepEqual(closed, [['right',{sessionId:'A'}],['bottom',{sessionId:'A'}],['float',{sessionId:'A'}]])
  listener(); dispose(); await Promise.resolve()
  assert.equal(closed.length, 3)
  assert.equal(unsubscribed, true)
})
test('classic cleanup tolerates missing, malformed and cyclic layouts without closing foreign tabs', async () => {
  const cycle: any = {kind:'split', children:[]}
  cycle.children = [cycle, {tabs:[null, {id:'owned', type:KLINE_TAB_ID}, {id:9, type:KLINE_TAB_ID}, {id:'editor', type:'editor'}]}]
  const closed: string[] = []
  let state: any = {splits:cycle, floats:[null, {}, {tab:{id:'float',type:KLINE_TAB_ID}}]}
  let listener = () => {}
  const service = {features:['stateSubscription'], getSnapshot: () => ({sessionId:'A', state}),
    subscribeState: (fn: () => void) => {listener = fn; return () => {}},
    closeTab: (id: string) => {closed.push(id); if (id === 'owned') throw Error('stale tab')} } as unknown as BetterSidebarService
  const dispose = cleanClassicTabs(service)
  await Promise.resolve()
  assert.deepEqual(closed, ['owned','float'])
  for (const malformed of [{}, {splits:null}, {splits:{kind:'split'}}, {bottomSplits:{}, floats:{} }]) {
    state = malformed; listener(); await Promise.resolve()
  }
  assert.equal(closed.length, 2)
  dispose()
})
test('classic cleanup contains optional service failures, including teardown', async () => {
  for (const failSubscription of [true, false]) {
    const dispose = cleanClassicTabs({features:['stateSubscription'], closeTab() {}, getSnapshot() {throw Error('disposed')},
      subscribeState() {if (failSubscription) throw Error('unavailable'); return () => {throw Error('disposed')}},
    } as unknown as BetterSidebarService)
    await Promise.resolve()
    assert.doesNotThrow(dispose)
  }
})
test('interface save validates preference, persists separate auto-open and reloads only on success', () => {
  const start = html.indexOf('function initInterfaceControls()')
  const end = html.indexOf('\nfunction renderHelpPopover', start)
  const handlers = new Map<string, Function>()
  const s = storage()
  let selection = 'better-sidebar', reloads = 0, acknowledged = 0
  const nodes = new Map<string, any>()
  const node = (id: string) => {
    if (!nodes.has(id)) nodes.set(id, {hidden:false, checked:false, addEventListener: (event: string, fn: Function) => handlers.set(id + ':' + event, fn)})
    return nodes.get(id)
  }
  const init = runInNewContext(`(${html.slice(start, end)})`, {
    window: {__DSH_KLINE_INTERFACE__: {onboardingKind: () => 'none'}, localStorage:s, location:{reload: () => reloads++}, addEventListener() {}},
    document: {getElementById:node, querySelector:(query: string) => query.includes(':checked') ? {value:selection} : node('badge'), addEventListener() {}},
    acknowledgeInterface: () => acknowledged++, closeInterfaceUpgrade() {}, setInterfaceOpen() {}, t:(key: string) => key,
  })
  init()
  const save = handlers.get('interfaceSave:click')!
  save()
  assert.equal(s.getItem(DISPLAY_MODE_KEY), 'better-sidebar')
  assert.equal(s.getItem(AUTO_OPEN_KEY), 'false')
  assert.equal(reloads, 1)
  assert.equal(acknowledged, 1)
  selection = 'invalid'; save(); assert.equal(reloads, 1)
  selection = 'classic'; s.setItem = () => { throw Error('denied') }
  save(); assert.equal(reloads, 1)
  assert.equal(node('interfaceSaveStatus').textContent, 'interfaceSaveFailed')
})
