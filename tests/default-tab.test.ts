import {test} from 'node:test'
import assert from 'node:assert/strict'
import type {BetterSidebarService} from 'dsh-better-sidebar'
import {installDefaultKlineTabs} from '../src/client/default-tab.ts'
import {KLINE_TAB_ID} from '../src/client/sidebar-integration.ts'

function harness() {
  const saved = new Map<string,string>()
  const storage = {getItem:(key:string) => saved.get(key) ?? null, setItem:(key:string,value:string) => {saved.set(key,value)}}
  const calls: string[] = [], listeners = new Set<() => void>()
  let sessionId = 'A', enabled = true
  let state: any = {activePane:'right',panelOpen:false,bottomOpen:false,splits:{kind:'leaf',id:'right',active:'file',tabs:[{id:'file',type:'editor'}]},bottomSplits:{kind:'leaf',id:'bottom',active:null,tabs:[]},floats:[]}
  const notify = () => listeners.forEach(fn => fn())
  const service = {features:['stateSubscription'],isTabEnabled:() => enabled,getSnapshot:() => ({sessionId,state}),
    subscribeState:(fn:()=>void) => {listeners.add(fn); return () => {listeners.delete(fn)}},
    openTab:(_:unknown,scope:any) => {calls.push(`open:${scope.sessionId}`);state.splits.tabs.push({id:KLINE_TAB_ID,type:KLINE_TAB_ID});state.splits.active=KLINE_TAB_ID;notify()},
    activateTab:(id:string) => {calls.push(`activate:${id}`);state.splits.active=id;notify()},
  } as unknown as BetterSidebarService
  return {service,storage,calls,notify,get state(){return state},switchSession:(id:string) => {sessionId=id;state={...state,splits:{...state.splits,tabs:[{id:'file',type:'editor'}],active:'file'}};notify()},enable:(value:boolean) => {enabled=value;notify()}}
}
test('default tab is added once without expanding panels or replacing the active tab', async () => {
  const h=harness(), dispose=installDefaultKlineTabs(h.service,h.storage)
  await Promise.resolve(); await Promise.resolve()
  assert.deepEqual(h.calls,['open:A','activate:file'])
  assert.equal(h.state.panelOpen,false);assert.equal(h.state.bottomOpen,false);assert.equal(h.state.splits.active,'file')
  h.notify();await Promise.resolve();assert.equal(h.calls.length,2)
  h.switchSession('B');await Promise.resolve();assert.equal(h.calls[2],'open:B')
  dispose()
})
test('manual close remains closed across refresh and conversation switches', async () => {
  const h=harness();let dispose=installDefaultKlineTabs(h.service,h.storage)
  await Promise.resolve();h.state.splits.tabs=[{id:'file',type:'editor'}];h.notify();await Promise.resolve()
  dispose();dispose=installDefaultKlineTabs(h.service,h.storage);await Promise.resolve()
  h.switchSession('B');await Promise.resolve();h.switchSession('A');await Promise.resolve()
  assert.equal(h.calls.filter(c=>c==='open:A').length,1);dispose()
})
test('existing floating chart is not reactivated or duplicated', async () => {
  const h=harness();h.state.floats=[{tab:{id:KLINE_TAB_ID,type:KLINE_TAB_ID}}]
  const dispose=installDefaultKlineTabs(h.service,h.storage);await Promise.resolve()
  assert.deepEqual(h.calls,[]);dispose()
})
test('disabled plugin and disposed subscription cannot create tabs', async () => {
  const h=harness();h.enable(false)
  const dispose=installDefaultKlineTabs(h.service,h.storage);await Promise.resolve();assert.deepEqual(h.calls,[])
  h.enable(true);dispose();await Promise.resolve();assert.deepEqual(h.calls,[])
})
test('blocked local storage falls back to one insertion per mounted session', async () => {
  const h=harness(), bad={getItem(){throw Error('denied')},setItem(){throw Error('denied')}}
  const dispose=installDefaultKlineTabs(h.service,bad);await Promise.resolve();h.notify();await Promise.resolve()
  assert.equal(h.calls.filter(c=>c==='open:A').length,1);dispose()
})
