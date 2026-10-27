import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { fibonacciOverlayPoints } from '../src/fibonacci.ts'
import { drawingInventory, observationKey, sanitizeChartContext } from '../src/chart-observation.ts'
import { sanitizeSourcePayload } from '../src/chart-sources.ts'
import { collectDrawingFeedback, sanitizeDrawingFeedback } from '../src/drawing-feedback.ts'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'

const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
function command():any {return {type:'DRAW_AGENT_FIBONACCI',id:'F',interval:'day',label:'上涨回撤',color:'success',
  from:{time:1,price:100},to:{time:4,price:200},ratios:[0,.618,1],
  levels:[{ratio:0,price:200},{ratio:.618,price:138.2},{ratio:1,price:100}],geometry_basis:'linear_price_retracement'}}
const rows=[1,2,3,4].map(time=>({time,open:130,high:210,low:90,close:140,volume:1}))
function payload(c=command()):any {return {symbol:'TEST.X',interval:'day',adjust:'none',chartCommands:[{type:'SET_CANDLES',rows},c]}}
function state(p=payload()):any {return sanitizeChartContext({state:'ready',symbol:'TEST.X',interval:'day',interval_value:1,ui_interval:'day',
  source_interval:'day',adjust:'none',candles:rows,drawings:drawingInventory(p),visible_range:{available:true,index_from:0,index_to_exclusive:4}})}
function renderer() {
  const overlays=new Map<string,any>(),removed:any[]=[]
  const render=runInNewContext(html.slice(html.indexOf('function drawAgentFibonacciCommands('),html.indexOf('let pendingLiveDrawingPayload'))+
    ';drawAgentFibonacciCommands',{currentInterval:'day',currentCandles:rows,kchart:{removeOverlay:(v:any)=>{removed.push(v);overlays.clear()},
      createOverlay:(v:any)=>{overlays.set(v.id,v);return v.id}}})
  return {render,overlays,removed}
}

test('one locked Fibonacci object owns exact financial levels and stable identity',()=>{
  const f=renderer(),c=command();f.render([c],true)
  const overlay=f.overlays.get('F')
  assert.equal(overlay.name,'ftvAgentFibonacci');assert.equal(overlay.groupId,'agentFibonacci');assert.equal(overlay.lock,true)
  assert.deepEqual(JSON.parse(JSON.stringify(overlay.points)),fibonacciOverlayPoints(c))
  assert.equal(overlay.points[4].value,138.2);assert.equal(overlay.points.length,8)
  let prevented=false;assert.equal(overlay.onRightClick({preventDefault(){prevented=true}}),true);assert.equal(prevented,true)
  f.render([{...c,color:'danger',label:'修改回撤'}],true)
  assert.equal(f.overlays.size,1);assert.equal(f.overlays.get('F').extendData.label,'修改回撤')
  f.render([],true);assert.equal(f.overlays.size,0)
})

test('renderer and shared validator reject wrong geometry without time snapping',()=>{
  const f=renderer(),c=command()
  for(const changed of [{geometry_basis:'log'}, {ratios:[0,.5,1]}, {to:{time:1,price:200}},
    {levels:[{ratio:0,price:200},{ratio:.618,price:150},{ratio:1,price:100}]}]) {
    const bad={...c,...changed}
    assert.throws(()=>fibonacciOverlayPoints(bad));assert.throws(()=>f.render([bad],true))
  }
  f.render([{...c,interval:'week'}],true);assert.equal(f.overlays.size,0)
  f.render([{...c,to:{time:3.5,price:200}}],true);assert.equal(f.overlays.size,0)
})

test('template uses pre-mapped price coordinates, not interpolation between endpoint pixels',()=>{
  const templates:any[]=[]
  runInNewContext(html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))+';registerOverlays()',{
    overlaysRegistered:false,window:{klinecharts:{registerOverlay:(v:any)=>{templates.push(v);if(v.name==='ftvAgentFibonacci')throw Error('stop')}}},
    console:{warn(){}},colorFor:()=> '#123456',formatPrice:(v:number)=>v.toFixed(2)})
  const template=templates.find(t=>t.name==='ftvAgentFibonacci');assert.ok(template)
  // Deliberately non-linear mapping: the .618 coordinate is y=77, NOT
  // a pixel interpolation of endpoint coordinates y=10 and y=90.
  const coordinates=[{x:10,y:90},{x:100,y:10},{x:10,y:10},{x:100,y:10},
    {x:10,y:77},{x:100,y:77},{x:10,y:90},{x:100,y:90}]
  const figures=template.createPointFigures({overlay:{extendData:{levels:command().levels,label:'回撤',colorName:'success'}},coordinates})
  assert.equal(figures.length,5);assert.equal(figures[2].attrs.coordinates[0].y,77)
  assert.equal(figures[2].styles.size,2);assert.match(figures[3].attrs.text,/0.618 · 138.20/)
  assert.equal(figures[3].styles.color,'#ffffff')
  const crowdedLevels=[0,.236,.382,.5,.618,.786,1].map((ratio,index)=>({ratio,price:200-index*5}))
  const crowdedCoordinates=[{x:10,y:90},{x:100,y:10},...crowdedLevels.flatMap((_,index)=>[{x:10,y:50+index*7},{x:100,y:50+index*7}])]
  const crowded=template.createPointFigures({overlay:{extendData:{levels:crowdedLevels,label:'重复名称',colorName:'success'}},coordinates:crowdedCoordinates})
  assert.equal(crowded.filter((figure:any)=>figure.type==='line').length,7)
  assert.ok(crowded.filter((figure:any)=>figure.type==='text').length<7)
  assert.ok(crowded.filter((figure:any)=>figure.type==='text').every((figure:any)=>!figure.attrs.text.includes('重复名称')))
})

test('Fibonacci observation, source sanitizer and feedback preserve exact levels and reject forged ones',()=>{
  const p=payload(),s=state(p),f=renderer();f.render([command()],true)
  const cleaned=sanitizeSourcePayload({...p,secret:'not-for-output'},s)
  assert.equal(observationKey(s),observationKey({...s,drawings:drawingInventory(cleaned)}))
  assert.ok(!JSON.stringify(cleaned).includes('not-for-output'))
  const report=collectDrawingFeedback(p,s,{getOverlayById:(id:string)=>f.overlays.get(id)})
  assert.equal(report.items[0].status,'created');assert.equal(report.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(report,s.drawings).report_status,'reported')
  f.overlays.get('F').points[4].value=150
  assert.equal(collectDrawingFeedback(p,s,{getOverlayById:(id:string)=>f.overlays.get(id)}).items[0].reason,'overlay_mismatch')
  const forged=payload({...command(),levels:[{ratio:0,price:200},{ratio:.618,price:150},{ratio:1,price:100}]})
  assert.throws(()=>sanitizeSourcePayload(forged,s))
  const hidden=collectDrawingFeedback(p,{...s,ui_interval:'week'},{getOverlayById:()=>null})
  assert.equal(hidden.items[0].status,'hidden');assert.equal(hidden.items[0].reason,'period_mismatch')
})

test('legacy snapshot merges retain and delete Fibonacci atomically without replacing market data',()=>{
  const p=payload(),source='b'.repeat(32)
  const candidate={...p,drawing_only:true,drawing_parent_session:source,chartCommands:[{...command(),color:'danger'}]}
  const merged=mergeHorizontalLineSnapshot(candidate,{session:source,payload:p})
  assert.equal(merged.chartCommands[0],p.chartCommands[0]);assert.equal(merged.chartCommands.length,2)
  assert.equal(merged.chartCommands[1].color,'danger')
  assert.deepEqual(mergeHorizontalLineSnapshot({...candidate,chartCommands:[]},{session:source,payload:p}).chartCommands,[p.chartCommands[0]])
})

test('redraw, live apply, recovery cleanup and symbol resets include Fibonacci but annotation clear does not own it',()=>{
  assert.match(html,/DRAW_AGENT_FIBONACCI"\) lastAgentFibonacci.push/)
  assert.match(html,/\.\.\.lastAgentFibonacci/);assert.match(html,/drawAgentFibonacciCommands\(cmds\)/)
  assert.match(html,/lastAgentRectangles = \[\];\s+lastAgentFibonacci = \[\];/)
  const clear=html.slice(html.indexOf('function clearAnalysisAnnotations('),html.indexOf('function clearAnalysisAnnotations(')+1800)
  assert.doesNotMatch(clear,/DRAW_AGENT_FIBONACCI|agentFibonacci|lastAgentFibonacci/)
})
