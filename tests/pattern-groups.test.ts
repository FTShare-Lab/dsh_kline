import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { sanitizePatternGroupCommand } from '../src/pattern-groups.ts'
import { drawingInventory } from '../src/chart-observation.ts'
import { collectDrawingFeedback } from '../src/drawing-feedback.ts'

const rows = [1, 2, 3, 4].map(time => ({time, open:31, high:40, low:29, close:32, volume:100}))
const pattern:any = {type:'DRAW_AGENT_PRICE_PATTERN',id:'pattern_'+'a'.repeat(24),interval:'day',
  geometry_hash:'b'.repeat(64),bar_count:3,rule_version:'price_patterns_v1',as_of:4,label:'双顶',color:'info',
  pattern:{type:'double_top',anchors:[
    {index:0,side:'high',time:1,price:40},{index:1,side:'low',time:2,price:30},{index:2,side:'high',time:3,price:39}],
    status:'candidate',direction:'down',break_direction:null,atr:1,buffer:.25,available_at:3,as_of:4,
    confirmed_at:null,invalidated_at:null,outer:40,neckline:{type:'horizontal',price:30},
    events:[{type:'candidate',time:3,index:2}],volume_evidence:{status:'known',relative_to_preceding_20:0,unit:'shares'}}}
const nine:any = {type:'DRAW_AGENT_NINE_COUNT',id:'nine_'+'c'.repeat(24),interval:'day',
  geometry_hash:'d'.repeat(64),bar_count:1,rule_version:'nine_count_v1',as_of:4,label:'九转',color:'warning',
  marks:[{time:4,index:3,direction:'up',count:1,label:'1',price:29}],events:[]}

test('all automatic candidate drawings use engine order and default to the first result', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function automaticCandidateIndex('), html.indexOf('async function patternAnalyze('))
  const choose = runInNewContext(source + ';automaticCandidateIndex', {})
  const candidates = [{ status: 'breakout_failed' }, { status: 'candidate' }, { status: 'price_confirmed' }]
  assert.equal(choose(candidates), 0)
  assert.equal(choose(candidates, 2), 2)
  assert.equal(choose(candidates, 99), 2)
  assert.equal(choose(candidates, -1), 0)
  assert.equal(choose([]), -1)
})

test('drawing tools share one analysis request contract', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function automaticDrawingRequest('), html.indexOf('function workbenchStatus('))
  const request = runInNewContext(source + ';automaticDrawingRequest', {})
  assert.equal(request('horizontal').function, 'recent_drawing_candidates')
  assert.equal(request('channel').parameters.closed_daily_only, true)
  assert.equal(request('rectangle').parameters.closed_daily_only, true)
  assert.equal(request('pattern_double_bottom').parameters.pattern_types[0], 'double_bottom')
  assert.equal(request('nine_count', { displayBars: 60 }).parameters.display_bars, 60)
  assert.throws(() => request('unknown'), /没有自动分析流程/)
})

test('group commands remain single inventory objects and render as one overlay each',()=>{
  const p=sanitizePatternGroupCommand(pattern,'day'), n=sanitizePatternGroupCommand(nine,'day')
  assert.equal(p.pattern.volume_evidence.relative_to_preceding_20,0)
  const payload:any={interval:'day',chartCommands:[{type:'SET_CANDLES',rows},p,n]}
  assert.deepEqual(drawingInventory(payload).map((x:any)=>x.kind),['price_pattern','nine_count'])
  const overlays=new Map<string,any>(), html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const source=html.slice(html.indexOf('function drawAgentPatternGroupCommands('),html.indexOf('let pendingLiveDrawingPayload'))
  const context:any={currentCandles:rows,currentInterval:'day',patternGroupRegistry:new Map(),automaticNine:{enabled:false,marks:[]},
    kchart:{removeOverlay:()=>overlays.clear(),createOverlay:(x:any)=>{overlays.set(x.id,x);return x.id},
      getOverlayById:(id:string)=>overlays.get(id)}}
  const draw=runInNewContext(source+';drawAgentPatternGroupCommands',context)
  draw(payload.chartCommands,true)
  assert.equal(overlays.size,2)
  assert.equal(overlays.get(p.id).points.length,5)
  assert.equal(overlays.get(p.id).extendData.contextAfterIndex,undefined)
  assert.equal(overlays.get(n.id).points.length,1)
  assert.equal(overlays.get(n.id).points[0].value,40)
  const state:any={state:'ready',candles:rows,interval:'day',ui_interval:'day',
    visible_range:{available:true,index_from:0,index_to_exclusive:4}}
  assert.deepEqual(collectDrawingFeedback(payload,state,context.kchart,[],'applied').items.map((x:any)=>x.status),['created','created'])
  const truncated={...state,candles:rows.slice(2)}
  const feedback=collectDrawingFeedback(payload,truncated,context.kchart,[],'applied').items
  assert.equal(feedback[0].status,'hidden')
  assert.equal(feedback[0].reason,'snapshot_outside_loaded_history')
  draw([{type:'SET_CANDLES',rows}],true)
  assert.equal(overlays.size,0)
})

test('platform drawing anchors its breakout and failure marks to actual closed bars', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function drawAgentPatternGroupCommands('), html.indexOf('let pendingLiveDrawingPayload'))
  let overlay: any
  const context: any = { currentCandles: rows, currentInterval: 'day', patternGroupRegistry: new Map(),
    kchart: { removeOverlay() {}, createOverlay(value: any) { overlay = value; return value.id } } }
  const draw = runInNewContext(source + ';drawAgentPatternGroupCommands', context)
  draw([{ ...pattern, pattern: { type: 'platform', anchors: [], status: 'breakout_failed',
    box: { start_time: 1, end_time: 2, upper_price: 40, lower_price: 29 },
    confirmed_at: 3, invalidated_at: 4, break_direction: 'down' } }], true)
  assert.deepEqual(Array.from(overlay.points, (point: any) => [point.timestamp, point.value]),
    [[1000, 40], [2000, 29], [3000, 32], [4000, 32]])
  assert.equal(overlay.extendData.confirmedAt, 3)
  assert.equal(overlay.extendData.invalidatedAt, 4)
})

test('an unconfirmed platform extends only its frozen borders to the observed cutoff', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function drawAgentPatternGroupCommands('), html.indexOf('let pendingLiveDrawingPayload'))
  let overlay: any
  const context: any = {currentCandles: rows, currentInterval: 'day', patternGroupRegistry: new Map(),
    kchart: {removeOverlay() {}, createOverlay(value: any) {overlay = value; return value.id}}}
  const draw = runInNewContext(source + ';drawAgentPatternGroupCommands', context)
  draw([{...pattern, pattern: {type: 'platform', anchors: [], status: 'candidate', as_of: 4,
    box: {start_time: 1, end_time: 2, upper_price: 40, lower_price: 29},
    confirmed_at: null, invalidated_at: null}}], true)
  assert.deepEqual(Array.from(overlay.points, (point: any) => [point.timestamp, point.value]),
    [[1000, 40], [2000, 29], [4000, 40]])
  assert.equal(overlay.extendData.boundaryEndIndex, 2)
  assert.equal(overlay.extendData.confirmedAt, null)
})

test('double-bottom display names both lows without inventing a straight move to the cutoff', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function drawAgentPatternGroupCommands('), html.indexOf('let pendingLiveDrawingPayload'))
  let overlay: any
  const currentCandles = [
    { time: 1, high: 45, low: 38, close: 39 },
    { time: 2, high: 34, low: 29, close: 30 },
    { time: 3, high: 40, low: 34, close: 38 },
    { time: 4, high: 33, low: 28, close: 30 },
    { time: 5, high: 39, low: 31, close: 36 },
    { time: 6, high: 43, low: 36, close: 42 },
  ]
  const context: any = { currentCandles, currentInterval: 'day', patternGroupRegistry: new Map(),
    kchart: { removeOverlay() {}, createOverlay(value: any) { overlay = value; return value.id } } }
  const draw = runInNewContext(source + ';drawAgentPatternGroupCommands', context)
  draw([{ ...pattern, as_of: 5, pattern: { ...pattern.pattern, type: 'double_bottom', as_of: 5,
    anchors: [
      { time: 2, price: 29 }, { time: 3, price: 40 }, { time: 4, price: 28 },
    ], neckline: { type: 'horizontal', price: 40 } } }], true)
  assert.deepEqual(Array.from(overlay.points, (point: any) => [point.timestamp, point.value]), [
    [2000, 29], [3000, 40], [4000, 28], [2000, 40], [5000, 40], [1000, 45],
  ])
  assert.equal(overlay.extendData.contextBeforeIndex, 5)
  assert.equal(overlay.extendData.contextAfterIndex, undefined)
  assert.deepEqual(Array.from(overlay.extendData.anchorLabels), ['底1', '颈', '底2'])
})

test('confirmed reversal marks its actual closed breakout bar', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function drawAgentPatternGroupCommands('), html.indexOf('let pendingLiveDrawingPayload'))
  let overlay: any
  const context: any = {currentCandles: rows, currentInterval: 'day', patternGroupRegistry: new Map(),
    kchart: {removeOverlay() {}, createOverlay(value: any) {overlay = value; return value.id}}}
  const draw = runInNewContext(source + ';drawAgentPatternGroupCommands', context)
  draw([{...pattern, pattern: {...pattern.pattern, status: 'price_confirmed', confirmed_at: 4,
    break_direction: 'down'}}], true)
  assert.equal(overlay.extendData.confirmedIndex, 5)
  assert.equal(overlay.extendData.confirmedAt, 4)
  assert.equal(overlay.points[5].timestamp, 4000)
  assert.equal(overlay.points[5].value, rows[3].close)
})

test('head-and-shoulders neckline reaches the observed cutoff using bar-index slope', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('function drawAgentPatternGroupCommands('), html.indexOf('let pendingLiveDrawingPayload'))
  const currentCandles = [1, 2, 3, 4, 5, 6, 7].map(time =>
    ({ time, open: 30, high: 40, low: 20, close: 32, volume: 100 }))
  let overlay: any
  const context: any = { currentCandles, currentInterval: 'day', patternGroupRegistry: new Map(),
    kchart: { removeOverlay() {}, createOverlay(value: any) { overlay = value; return value.id } } }
  const draw = runInNewContext(source + ';drawAgentPatternGroupCommands', context)
  const anchors = [
    { time: 1, price: 35 }, { time: 2, price: 30 }, { time: 3, price: 40 },
    { time: 4, price: 34 }, { time: 5, price: 35 },
  ]
  draw([{ ...pattern, as_of: 7, pattern: { ...pattern.pattern, type: 'head_shoulders_top',
    anchors, as_of: 7, neckline: { type: 'sloped', from: { time: 2, price: 30 },
      to: { time: 4, price: 34 } } } }], true)
  assert.deepEqual(Array.from(overlay.points.slice(5), (point: any) => [point.timestamp, point.value]),
    [[2000, 30], [7000, 40]])
  draw([{ ...pattern, as_of: 10, pattern: { ...pattern.pattern, type: 'head_shoulders_top',
    anchors, as_of: 10, neckline: { type: 'sloped', from: { time: 2, price: 30 },
      to: { time: 4, price: 34 } } } }], true)
  assert.deepEqual(Array.from(overlay.points.slice(5), (point: any) => [point.timestamp, point.value]),
    [[2000, 30], [4000, 34]])
})

test('pattern labels sit outside their high or low pivots', () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
  const start = html.indexOf('window.klinecharts.registerOverlay({\n      name: "ftvPatternGroup"')
  const end = html.indexOf('window.klinecharts.registerOverlay({\n      name: "ftvAgentFibonacci"', start)
  assert.ok(start > 0 && end > start)
  let template: any
  runInNewContext(html.slice(start, end), {
    window: {klinecharts: {registerOverlay: (value: any) => {template = value}}},
    colorFor: () => '#09f', rightAxisGutterWidth: () => 40,
  })
  const coordinates = [
    {x: 40, y: 190}, {x: 90, y: 100}, {x: 140, y: 220},
    {x: 190, y: 105}, {x: 240, y: 195}, {x: 90, y: 100}, {x: 240, y: 105},
  ]
  const render = (sides: string[], patternType: string) => template.createPointFigures({
    overlay: {extendData: {anchorCount: 5, anchorSides: sides,
      anchorLabels: ['左肩', '', '头', '', '右肩'], patternType, status: '候选'}},
    coordinates, bounding: {width: 400},
  })
  const bottom = render(['low', 'high', 'low', 'high', 'low'], 'head_shoulders_bottom')
  const bottomLabels = bottom.filter((figure: any) => ['左肩', '头', '右肩'].includes(figure.attrs?.text))
  assert.deepEqual(Array.from(bottomLabels, (figure: any) => figure.attrs.y), [206, 236, 211])
  assert.ok(bottomLabels.every((figure: any) => figure.attrs.baseline === 'top'))
  const status = bottom.find((figure: any) => figure.attrs?.text === '头肩底 · 候选')
  assert.equal(status.attrs.y, 170)
  const nearBottom = template.createPointFigures({overlay: {extendData: {anchorCount: 5,
    anchorSides: ['low', 'high', 'low', 'high', 'low'],
    anchorLabels: ['左肩', '', '头', '', '右肩'], patternType: 'head_shoulders_bottom'}},
    coordinates, bounding: {width: 400, height: 240}})
  const head = nearBottom.find((figure: any) => figure.attrs?.text === '头')
  assert.equal(head.attrs.y, 204)
  assert.equal(head.attrs.baseline, 'bottom')
  const top = render(['high', 'low', 'high', 'low', 'high'], 'head_shoulders_top')
  const topLabels = top.filter((figure: any) => ['左肩', '头', '右肩'].includes(figure.attrs?.text))
  assert.deepEqual(Array.from(topLabels, (figure: any) => figure.attrs.y), [174, 204, 179])
  assert.ok(topLabels.every((figure: any) => figure.attrs.baseline === 'bottom'))
  const doubleBottom = template.createPointFigures({overlay: {extendData: {
    anchorCount: 3, anchorSides: ['low', 'high', 'low'],
    anchorLabels: ['底1', '颈', '底2'], confirmedIndex: 5, confirmedAt: 1762819200,
    breakDirection: 'up', patternType: 'double_bottom', status: '候选'}},
    coordinates: [{x: 40, y: 180}, {x: 90, y: 100}, {x: 140, y: 190},
      {x: 40, y: 100}, {x: 210, y: 100}, {x: 200, y: 75}],
    bounding: {width: 400, height: 260}})
  assert.ok(doubleBottom.some((figure: any) => figure.attrs?.text === '底1' && figure.attrs.y > 180))
  assert.ok(doubleBottom.some((figure: any) => figure.attrs?.text === '底2' && figure.attrs.y > 190))
  assert.ok(doubleBottom.some((figure: any) => figure.attrs?.text === '双底 · 候选'
    && figure.attrs.y === 160 && figure.attrs.baseline === 'bottom'))
  assert.ok(doubleBottom.some((figure: any) => figure.attrs?.text?.startsWith('突破 ') && figure.attrs.y === 84))
  assert.ok(!doubleBottom.some((figure: any) => figure.type === 'line'
    && figure.attrs?.coordinates?.[0]?.x === 140 && figure.attrs?.coordinates?.[1]?.x === 200))
  const box = template.createPointFigures({overlay: {extendData: {platform: true,
    boundaryEndIndex: 2, status: '候选'}}, coordinates: [
    {x: 40, y: 100}, {x: 100, y: 200}, {x: 220, y: 100},
  ], bounding: {width: 400}})
  const extensions = box.filter((figure: any) => figure.type === 'line' && figure.styles?.style === 'dashed')
  assert.deepEqual(Array.from(extensions, (figure: any) => Array.from(figure.attrs.coordinates, (point: any) => point.y)),
    [[100, 100], [200, 200]])
})

test('automatic nine count updates one chart object when candles change', async () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const requestSource = html.slice(html.indexOf('function automaticDrawingRequest('), html.indexOf('function workbenchStatus('))
  const source = requestSource + html.slice(html.indexOf('const patternState ='), html.indexOf('function patternDate('))
  const overlays: any[] = [], calls: any[] = [], edits: any[] = []
  let revision = 1
  let sourceKey = 'candles-v1'
  const binding = () => ({ context_ref: 'current', expected_revision: revision, chart_session: 'chart', symbol: '600519.XSHG' })
  const button: any = { textContent: '', setAttribute() {}, classList: { toggle() {} } }
  const context: any = {
    document: { getElementById: () => button }, kchart: { removeOverlay() { overlays.length = 0 },
      createOverlay(value: any) { overlays.push(value) } },
    currentInterval: 'day', currentCandles: [{ time: 10 }, { time: 20 }], lastChartPayload: null,
    workbenchCurrentBinding: binding,
    // A successful edit rotates the source chart session without changing the candles.
    workbenchDataKey: () => JSON.stringify(['current', `chart-${revision}`, '600519.XSHG',
      JSON.stringify({ source_chart_session: `chart-${revision}`, candles: sourceKey })]),
    workbenchTool: async (_name: string, args: any) => {
      calls.push(args)
      return { result_ref: `ref-${revision}`, summary: { marks: [{ time: 10, price: 100, count: revision, direction: 'up' }] } }
    },
    workbenchApplyProposal: async (proposal: any) => {
      edits.push(proposal.edit)
      context.lastChartPayload = { chartCommands: [{ type: 'DRAW_AGENT_NINE_COUNT', id: 'nine-1', interval: 'day', color: 'warning' }] }
      return { prepared: { object: { id: 'nine-1' } }, status: { apply_status: 'applied' } }
    },
    drawAgentPatternGroupCommands() {},
  }
  const api = runInNewContext(source + ';({ set: automaticNineSetEnabled, tick: automaticNineTick, state: automaticNine })', context)
  api.set(true)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 1)
  assert.equal(calls[0].function, 'nine_count')
  assert.equal(edits[0].action, 'create')
  assert.equal(edits[0].result_ref, 'ref-1')
  assert.equal(overlays.length, 0)
  revision = 2
  await api.tick(false)
  assert.equal(calls.length, 1)
  sourceKey = 'candles-v2'
  revision = 3
  await api.tick(true)
  assert.equal(calls.length, 2)
  assert.equal(edits[1].action, 'update')
  assert.equal(edits[1].object_id, 'nine-1')
  assert.equal(edits[1].result_ref, 'ref-3')
  api.set(false)
  assert.equal(overlays.length, 0)
})
