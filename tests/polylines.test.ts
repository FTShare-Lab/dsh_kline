import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { sanitizePolylinePoints, polylineOverlayPoints } from '../src/labeled-polyline.ts'
import { drawingInventory, observationKey, sanitizeChartContext } from '../src/chart-observation.ts'
import { sanitizeSourcePayload } from '../src/chart-sources.ts'
import { collectDrawingFeedback, sanitizeDrawingFeedback } from '../src/drawing-feedback.ts'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'

const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
function command():any {return {type:'DRAW_AGENT_POLYLINE',id:'P',interval:'day',label:'ABC样板',color:'info',
  points:[{label:'A',time:1,price:30},{label:'B',time:2,price:34},{label:'C',time:3,price:31}]}}
const rows=[1,2,3,4].map(time=>({time,open:31,high:35,low:29,close:32,volume:1}))
function payload(c=command()):any {return {symbol:'TEST.X',interval:'day',adjust:'none',chartCommands:[{type:'SET_CANDLES',rows},c]}}
function state(p=payload()):any {return sanitizeChartContext({state:'ready',symbol:'TEST.X',interval:'day',interval_value:1,ui_interval:'day',
  source_interval:'day',adjust:'none',candles:rows,drawings:drawingInventory(p),visible_range:{available:true,index_from:0,index_to_exclusive:4}})}
function renderer() {
  const overlays=new Map<string,any>(),removed:any[]=[]
  const render=runInNewContext(html.slice(html.indexOf('function drawAgentPolylineCommands('),html.indexOf('let pendingLiveDrawingPayload'))+
    ';drawAgentPolylineCommands',{currentInterval:'day',currentCandles:rows,kchart:{removeOverlay:(v:any)=>{removed.push(v);overlays.clear()},
      createOverlay:(v:any)=>{overlays.set(v.id,v);return v.id}}})
  return {render,overlays,removed}
}

test('labeled polyline creates one locked object with every point and label intact',()=>{
  const f=renderer(),c=command();f.render([c],true)
  const overlay=f.overlays.get('P')
  assert.equal(overlay.name,'ftvAgentPolyline');assert.equal(overlay.groupId,'agentPolylines');assert.equal(overlay.lock,true)
  assert.deepEqual(Array.from(overlay.points,(p:any)=>({timestamp:p.timestamp,value:p.value})),polylineOverlayPoints(c))
  assert.deepEqual(Array.from(overlay.extendData.pointLabels),['A','B','C']);assert.equal(overlay.extendData.label,'ABC样板')
  let prevented=false;overlay.onRightClick({preventDefault(){prevented=true}});assert.equal(prevented,true)
  f.render([{...c,color:'warning',points:[...c.points.slice(0,2),{label:'C',time:4,price:32}]}],true)
  assert.equal(f.overlays.size,1);assert.equal(f.overlays.get('P').points[2].value,32)
  f.render([],true);assert.equal(f.overlays.size,0)
})

test('shared validator and actual renderer reject malformed paths instead of sorting or truncating',()=>{
  const f=renderer(),c=command(),p=c.points
  for(const bad of [p.slice(0,1),[p[1],p[0]], [p[0],{...p[1],label:'A'}],
    [p[0],{...p[1],price:NaN}], [p[0],{...p[1],time:1.5}], [p[0],{...p[1],label:' B '}],
    [p[0],{...p[1],label:'<script>\n'}],Array.from({length:9},(_,i)=>({label:String(i),time:i+1,price:31}))]) {
    assert.throws(()=>sanitizePolylinePoints(bad));assert.throws(()=>f.render([{...c,points:bad}],true))
  }
  f.render([{...c,interval:'week'}],true);assert.equal(f.overlays.size,0)
  f.render([{...c,points:[p[0],{...p[1],time:9}]}],true);assert.equal(f.overlays.size,0)
})

test('generic labels support arbitrary two-to-eight-point paths, not hard-coded ABC/1-5 templates',()=>{
  for(const count of [2,5,8]) {
    const points=Array.from({length:count},(_,i)=>({label:i===0?'起点':String(i),time:i+1,price:30+i%2}))
    assert.equal(sanitizePolylinePoints(points).length,count)
    assert.equal(polylineOverlayPoints({points}).length,count)
  }
  assert.equal(sanitizePolylinePoints([{label:'🚀'.repeat(16),time:1,price:30},{label:'终点',time:2,price:31}])[0].label,'🚀'.repeat(16))
})

test('template renders all segments and plain-text labels/prices in the same object',()=>{
  const templates:any[]=[]
  runInNewContext(html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))+';registerOverlays()',{
    overlaysRegistered:false,window:{klinecharts:{registerOverlay:(v:any)=>{templates.push(v);if(v.name==='ftvAgentPolyline')throw Error('stop')}}},
    console:{warn(){}},colorFor:()=> '#123456',formatPrice:(v:number)=>v.toFixed(2),currentTheme:()=> 'light'})
  const template=templates.find(t=>t.name==='ftvAgentPolyline');assert.ok(template)
  const coordinates=[{x:10,y:90},{x:100,y:10},{x:180,y:70}]
  const figures=template.createPointFigures({overlay:{points:polylineOverlayPoints(command()),
    extendData:{pointLabels:['A','B','C'],label:'ABC样板',colorName:'info'}},coordinates,bounding:{width:240,height:130}})
  const labels=figures.filter((f:any)=>f.type==='text')
  assert.equal(labels.length,3);assert.equal(figures.filter((f:any)=>f.type==='line' && !f.ignoreEvent).length,2)
  assert.equal(figures.filter((f:any)=>f.type==='line' && !f.ignoreEvent)[1].attrs.coordinates[1],coordinates[2])
  assert.equal(figures.filter((f:any)=>f.type==='line' && f.styles.size===4).length,2)
  assert.equal(labels[0].attrs.text,'A · 30.00');assert.equal(labels[2].attrs.text,'C · 31.00')
  assert.equal(labels[2].styles.color,'#ffffff');assert.equal(template.needDefaultPointFigure,false)
  assert.ok(labels.every((f:any)=>!f.attrs.text.includes('ABC样板')))
})

test('nearby ABC peaks get separate bounded labels without changing path anchors',()=>{
  const templates:any[]=[]
  runInNewContext(html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))+';registerOverlays()',{
    overlaysRegistered:false,window:{klinecharts:{registerOverlay:(v:any)=>{templates.push(v);if(v.name==='ftvAgentPolyline')throw Error('stop')}}},
    console:{warn(){}},colorFor:()=> '#123456',formatPrice:(v:number)=>v.toFixed(2),currentTheme:()=> 'light'})
  const template=templates.find(t=>t.name==='ftvAgentPolyline')
  const coordinates=[{x:90,y:55},{x:135,y:18},{x:164,y:24},{x:215,y:95}]
  const overlay={points:coordinates.map((_,i)=>({value:[31.75,35.77,35.47,27.5][i]})),
    extendData:{pointLabels:['A','顶','B','C'],label:'紫金矿业 abc浪',colorName:'info'}}
  const original=JSON.stringify(coordinates)
  const figures=template.createPointFigures({overlay,coordinates,bounding:{width:260,height:120}})
  const labels=figures.filter((f:any)=>f.type==='text')
  assert.equal(labels.length,4)
  const boxes=labels.map((f:any)=>({x:f.attrs.x,y:f.attrs.y,
    width:Array.from(f.attrs.text).reduce((sum:number,char:any)=>sum+(/[^\u0000-\u00ff]/.test(char)?11:6.5),0)+12,height:19}))
  for (let i=0;i<boxes.length;i++) {
    const a=boxes[i]
    assert.ok(a.x>=4 && a.y>=4 && a.x+a.width<=256 && a.y+a.height<=116)
    for(let j=i+1;j<boxes.length;j++) {
      const b=boxes[j]
      assert.ok(a.x+a.width<=b.x || b.x+b.width<=a.x || a.y+a.height<=b.y || b.y+b.height<=a.y)
    }
  }
  assert.equal(JSON.stringify(coordinates),original)
  assert.deepEqual(Array.from(figures.filter((f:any)=>f.type==='line' && !f.ignoreEvent),
    (f:any)=>f.attrs.coordinates[1]),coordinates.slice(1))
})

test('source handoff and observation preserve labels and reject duplicate or changed point identity',()=>{
  const p=payload(),s=state(p)
  p.chartCommands[1].points[0].secret='not-for-output'
  const cleaned=sanitizeSourcePayload({...p,secret:'not-for-output'},s)
  assert.ok(!JSON.stringify(cleaned).includes('not-for-output'))
  assert.equal(observationKey(s),observationKey({...s,drawings:drawingInventory(cleaned)}))
  assert.deepEqual(cleaned.chartCommands[1].points,command().points)
  const changed=payload();changed.chartCommands[1].points[2].label='D'
  assert.throws(()=>sanitizeSourcePayload(changed,s),/source_inventory_mismatch/)
  const duplicate=payload();duplicate.chartCommands[1].points[2].label='A'
  assert.throws(()=>sanitizeSourcePayload(duplicate,s))
  const week=state(p);week.interval='week';week.ui_interval='week'
  const preserved=sanitizeSourcePayload({...p,interval:'week'},week)
  assert.equal(preserved.chartCommands[1].interval,'day');assert.deepEqual(preserved.chartCommands[1].points,command().points)
})

test('feedback requires exact point geometry and labels and distinguishes hidden, missing and deleted groups',()=>{
  const c=command(),p=payload(c),s=state(p),f=renderer();f.render([c],true)
  const chart={getOverlayById:(id:string)=>f.overlays.get(id)}
  const report=collectDrawingFeedback(p,s,chart)
  assert.equal(report.items[0].status,'created');assert.equal(report.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(report,s.drawings).report_status,'reported')
  f.overlays.get('P').extendData.pointLabels[2]='D'
  assert.equal(collectDrawingFeedback(p,s,chart).items[0].reason,'overlay_mismatch')
  f.render([c],true);f.overlays.get('P').points[2].value=32
  assert.equal(collectDrawingFeedback(p,s,chart).items[0].reason,'overlay_mismatch')
  const empty={getOverlayById:()=>null}
  assert.equal(collectDrawingFeedback(p,{...s,ui_interval:'week'},empty).items[0].reason,'period_mismatch')
  assert.equal(collectDrawingFeedback(p,{...s,candles:rows.slice(0,2)},empty).items[0].reason,'anchors_not_loaded')
  assert.equal(collectDrawingFeedback(p,s,empty).items[0].reason,'overlay_missing')
  assert.equal(collectDrawingFeedback({...p,chartCommands:[]},s,empty,[c],'applied').items[0].status,'removed')
})

test('snapshot merge, redraw, symbol reset and automatic clear preserve or remove the entire owning group only',()=>{
  const p=payload(),source='b'.repeat(32),other={type:'DRAW_HORIZONTAL_LINE',id:'H',price:29}
  p.chartCommands.push(other)
  const merged=mergeHorizontalLineSnapshot({symbol:p.symbol,interval:p.interval,drawing_only:true,
    drawing_parent_session:source,chartCommands:[other,{...command(),color:'warning'}]},{session:source,payload:p})
  assert.equal(merged.chartCommands[0],p.chartCommands[0]);assert.equal(merged.chartCommands[1],other)
  assert.equal(merged.chartCommands[2].id,'P');assert.equal(merged.chartCommands[2].color,'warning')
  assert.match(html,/DRAW_AGENT_POLYLINE"\) lastAgentPolylines.push/)
  assert.match(html,/\.\.\.lastAgentPolylines/);assert.match(html,/drawAgentPolylineCommands\(cmds\)/)
  assert.match(html,/lastAgentFibonacci = \[\];\s+lastAgentPolylines = \[\];/)
  const clear=html.slice(html.indexOf('function clearAnalysisAnnotations('),html.indexOf('function clearAnalysisAnnotations(')+1800)
  assert.doesNotMatch(clear,/DRAW_AGENT_POLYLINE|agentPolylines|lastAgentPolylines/)
})
