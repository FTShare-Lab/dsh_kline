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
  assert.equal(overlays.get(n.id).points.length,1)
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

test('automatic nine count uses the shared result and refreshes when the chart revision changes', async () => {
  const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
  const source = html.slice(html.indexOf('const patternState ='), html.indexOf('function patternDate('))
  const overlays: any[] = [], calls: any[] = []
  let revision = 1
  const binding = () => ({ context_ref: 'current', expected_revision: revision, chart_session: 'chart', symbol: '600519.XSHG' })
  const button: any = { textContent: '', setAttribute() {}, classList: { toggle() {} } }
  const context: any = {
    document: { getElementById: () => button }, kchart: { removeOverlay() { overlays.length = 0 },
      createOverlay(value: any) { overlays.push(value) } },
    currentInterval: 'day', currentCandles: [{ time: 10 }, { time: 20 }], lastChartPayload: null,
    workbenchCurrentBinding: binding,
    workbenchTool: async (_name: string, args: any) => {
      calls.push(args)
      return { result_ref: `ref-${revision}`, summary: { marks: [{ time: 10, price: 100, count: revision, direction: 'up' }] } }
    },
    drawAgentPatternGroupCommands() {},
  }
  const api = runInNewContext(source + ';({ set: automaticNineSetEnabled, tick: automaticNineTick, state: automaticNine })', context)
  api.set(true)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 1)
  assert.equal(calls[0].function, 'nine_count')
  assert.equal(overlays[0].extendData.marks[0].count, 1)
  revision = 2
  await api.tick(true)
  assert.equal(calls.length, 2)
  assert.equal(overlays[0].extendData.marks[0].count, 2)
  api.set(false)
  assert.equal(overlays.length, 0)
})
