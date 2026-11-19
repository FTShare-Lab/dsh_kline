import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('/* Drawing selection and history.'), html.indexOf('/* End drawing interaction. */'))
function fixture() {
  const context: any = { currentSymbol: 'AAPL.US', currentInterval: 'day', currentAdjust: 'none',
    currentCandles: [{ time: 10, close: 100 }, { time: 20, close: 110 }, { time: 30, close: 105 }],
    lastChartPayload: { chartCommands: [] }, window: { __DSH_KLINE_OBSERVATION__: { context_ref: 'view-1' } },
    document: { getElementById: () => null }, workbenchCopy: (zh: string) => zh, Map, Set }
  const api = runInNewContext(source + ';({ state:drawingInteraction, anchors:drawingAnchors, edit:drawingAnchorEdit, key:drawingInteractionKey, history:drawingHistory, record:drawingRecordApplication, selected:drawingSelectedCommand, render:renderDrawingInteraction, bounds:drawingPlotBounds, editor:renderSelectedAnchorEditor })', context)
  return { api, context }
}
test('dragging ABC changes only the named endpoint under the same object ID', () => {
  const { api } = fixture()
  const points = ['A', 'B', 'C'].map((label, i) => ({ label, time: (i + 1) * 10, price: 100 + i }))
  const edit = api.edit({ type: 'DRAW_AGENT_POLYLINE', id: 'abc-1', points }, 2, { time: 40, price: 95 })
  assert.deepEqual(JSON.parse(JSON.stringify(edit)), { kind: 'labeled_polyline', action: 'update', object_id: 'abc-1', point_label: 'C', point_time: '40', point_price: 95 })
  assert.equal(points[2].price, 102)
})
test('channel drag preserves untouched anchors and Fibonacci retains its object type', () => {
  const { api } = fixture()
  const channel = { type: 'DRAW_AGENT_CHANNEL', id: 'channel-1' }
  assert.equal(api.edit(channel, 2, { time: 20, price: 90 }).parallel_price, 90)
  assert.ok(!('start_time' in api.edit(channel, 2, { time: 20, price: 90 })))
  assert.equal(api.edit({ type: 'DRAW_AGENT_FIBONACCI', id: 'fib-1' }, 0, { time: 10, price: 90 }).kind, 'fibonacci_retracement')
})
test('one confirmed multi-object application is one undo entry; duplicate receipts do not duplicate history', () => {
  const { api } = fixture()
  const entry = { token: 'batch-1', key: api.key(), event: null }
  api.record(entry); api.record(entry)
  assert.equal(api.history().undo.length, 1)
  api.record({ token: 'undo-1', key: api.key(), event: { session: 'batch-1', direction: 'undo' } })
  assert.equal(api.history().undo.length, 0); assert.equal(api.history().redo.length, 1)
  api.record({ token: 'redo-1', key: api.key(), event: { session: 'batch-1', direction: 'redo' } })
  assert.equal(api.history().undo.length, 1); assert.equal(api.history().redo.length, 0)
})
test('a new edit invalidates redo, and another instrument cannot inherit selection or history', () => {
  const { api, context } = fixture()
  api.record({ token: 'one', key: api.key() })
  api.record({ token: 'undo-one', key: api.key(), event: { session: 'one', direction: 'undo' } })
  api.record({ token: 'two', key: api.key() })
  assert.equal(api.history().redo.length, 0)
  context.lastChartPayload.chartCommands = [{ id: 'two', type: 'DRAW_HORIZONTAL_LINE', price: 100 }]
  api.state.selected = { id: 'two', key: api.key() }
  assert.ok(api.selected())
  context.currentSymbol = 'MSFT.US'
  assert.equal(api.selected(), null); assert.equal(api.history().undo.length, 0)
})
test('computed shape groups have no draggable anchors, keeping recognition evidence intact', () => {
  const { api } = fixture()
  assert.equal(api.anchors({ type: 'DRAW_AGENT_PRICE_PATTERN' }).length, 0)
  assert.equal(api.anchors({ type: 'DRAW_AGENT_NINE_COUNT' }).length, 0)
})

test('selecting a visible channel renders all three labelled, draggable handles', () => {
  const { api, context } = fixture()
  const children: any[] = []
  const layer = { replaceChildren: () => { children.length = 0 }, append: (child:any) => children.push(child) }
  context.document = { getElementById: (id:string) => id === 'drawingSelectionLayer' ? layer
    : id === 'klineChart' ? { getBoundingClientRect: () => ({ width: 800, height: 400, top: 0 }) } : null,
    querySelector: () => null, createElement: () => ({ style: {}, dataset: {}, setAttribute() {}, addEventListener() {} }) }
  context.viewLanguage = 'en'; context.workbenchMutationActive = false; context.fmt = (n:number) => String(n)
  context.kchart = { convertToPixel: () => [{ x: 100, y: 120 }], getDom: (_pane:string, position:string) => ({
    getBoundingClientRect: () => position === 'main' ? { left: 60, right: 800, top: 0, bottom: 350 } : { left: 0, right: 800, top: 0, bottom: 350 } }) }
  const originalGet = context.document.getElementById
  context.document.getElementById = (id:string) => id === 'klineChart' ? { getBoundingClientRect: () => ({ left: 0, width: 800, height: 400, top: 0 }) } : originalGet(id)
  context.lastChartPayload.chartCommands = [{ id: 'channel', type: 'DRAW_AGENT_CHANNEL', interval: 'day',
    from: { time: 10, price: 120 }, to: { time: 30, price: 100 }, parallel: { time: 20, price: 90 } }]
  api.state.selected = { id: 'channel', key: api.key() }
  api.render()
  assert.equal(children.length, 3)
  assert.deepEqual(children.map(child => child.title), ['Start · 120', 'End · 100', 'Parallel · 90'])
  assert.equal(children[2].dataset.anchorIndex, '2')
  assert.equal(children[0].style.left, '160px', 'SDK x coordinates must include the left price-axis offset')
})


test('searching another already-open symbol restores its saved drawing payload instead of fetching and erasing it', async () => {
  const source = html.slice(html.indexOf('async function openTickerSymbolChart('), html.indexOf('async function openLauncherDefaultChart('))
  const calls:any[] = []
  const open = runInNewContext(source + ';openTickerSymbolChart', {
    resolveSymbolIdentity: (symbol:string) => ({ symbol }), workspaceTabForSymbol: () => ({ id: 'QQQ.US' }),
    activeWorkspaceTabId: 'AAPL.US', closeSearchResults: () => calls.push('close'),
    selectWorkspaceTab: async (id:string) => calls.push(id), setSecurityTab: (tab:string) => calls.push(tab),
    isIntradayRange: () => false, openSymbol: () => { throw Error('must not refetch saved chart') }
  })
  await open('QQQ.US', 'QQQ')
  assert.deepEqual(calls, ['close', 'QQQ.US', 'chart'])
})


test('selected price editor preserves typing across observations and updates the named ABC endpoint', async () => {
  const { api, context } = fixture()
  const inputs:any[] = [], edits:any[] = []
  const editor = { dataset: {} as any, hidden: true, replaceChildren() { inputs.length = 0 }, append() {}, querySelectorAll: () => inputs }
  context.document = { getElementById: () => editor, createElement: (tag:string) => {
    const node:any = { append() {}, setAttribute() {}, addEventListener(type:string, handler:any) { node[type] = handler } }
    if (tag === 'input') inputs.push(node)
    return node
  }}
  context.viewLanguage = 'en'
  const command = { id:'abc-four', type:'DRAW_AGENT_POLYLINE', points:['0','A','B','C'].map((label,i) => ({label,time:(i+1)*10,price:100+i})) }
  context.lastChartPayload.chartCommands = [command]
  api.state.selected = { id:command.id, key:api.key() }; api.state.editingId = command.id
  context.drawingPerform = async (edit:any) => edits.push(edit)
  api.editor(command, false)
  assert.equal(inputs.length, 4)
  const input = inputs[3]; input.value = '97.5'
  api.editor(command, false)
  assert.equal(inputs[3], input, 'observation heartbeat must not replace a focused input')
  input.change(); await Promise.resolve()
  assert.deepEqual(JSON.parse(JSON.stringify(edits)), [{kind:'labeled_polyline',action:'update',object_id:'abc-four',point_label:'C',point_time:'40',point_price:97.5}])
  assert.equal(command.points[3].price, 103)
})
