import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { TEST_PYTHON } from '../scripts/test-runtime.mjs'
import { runInNewContext } from 'node:vm'
import { collectDrawingFeedback, sanitizeDrawingFeedback } from '../src/drawing-feedback.ts'
import { drawingInventory } from '../src/chart-observation.ts'
import { createChartContextPublisher } from '../src/client/chart-context.ts'

const rows=[1,2,3,4].map(time=>({time,open:31,high:33,low:30,close:32,volume:1}))
const horizontal={type:'DRAW_HORIZONTAL_LINE',id:'H',label:'完整H',color:'success',price:31}
const trend={type:'DRAW_AGENT_TREND_LINE',id:'T',label:'完整T',color:'info',from:{time:1,price:30},to:{time:4,price:32}}
const channel={type:'DRAW_AGENT_CHANNEL',id:'C',label:'完整C',color:'warning',interval:'day',geometry_basis:'candle_index_linear_price',
  from:{time:1,price:30},to:{time:4,price:32},parallel:{time:2,price:32},show_midline:false,
  upper:{from:{time:1,price:31},to:{time:4,price:33}},lower:{from:{time:1,price:30},to:{time:4,price:32}}}
const rectangle={type:'DRAW_AGENT_RECTANGLE',id:'R',label:'完整R',color:'danger',interval:'day',start_time:1,end_time:4,
  lower_price:30,upper_price:32,show_fill:false}
const series={type:'DRAW_AGENT_SERIES_LINE',id:'series_'+'a'.repeat(24),label:'条件线',color:'info',interval:'day',
  bar_count:4,source:{kind:'close'},condition:null,values:[32,null,32,32],series_hash:'b'.repeat(64)}
const band={type:'DRAW_AGENT_PRICE_BAND',id:'band_'+'a'.repeat(24),label:'价带',color:'warning',interval:'day',
  bar_count:4,upper_source:{kind:'high'},lower_source:{kind:'low'},condition:null,
  upper_values:[33,null,33,33],lower_values:[30,null,30,30],band_hash:'c'.repeat(64)}
const sticks={type:'DRAW_AGENT_PRICE_STICKS',id:'sticks_'+'a'.repeat(24),label:'柱线',color:'info',interval:'day',
  bar_count:4,start_source:{kind:'high'},end_source:{kind:'low'},condition:null,
  start_values:[33,null,33,33],end_values:[30,null,30,30],sticks_hash:'d'.repeat(64)}
function context(extra:any={}):any {return {state:'ready',candles:rows,interval:'day',ui_interval:'day',
  visible_range:{available:true,index_from:1,index_to_exclusive:3},...extra}}
function payload(commands:any[]=[horizontal,trend,channel,rectangle]):any {return {interval:'day',chartCommands:commands}}
function overlays():any {
  return {H:{id:'H',name:'ftvHorizontalLine',groupId:'agentHorizontalLines',points:[{timestamp:4000,value:31}],extendData:{label:'完整H',colorName:'success'}},
    T:{id:'T',name:'ftvTrendLine',groupId:'agentTrendLines',points:[{timestamp:1000,value:30},{timestamp:4000,value:32}],extendData:{label:'完整T',colorName:'info'}},
    C:{id:'C',name:'ftvAgentChannel',groupId:'agentChannels',points:[{timestamp:1000,value:31},{timestamp:4000,value:33},
      {timestamp:1000,value:30},{timestamp:4000,value:32}],extendData:{label:'完整C',colorName:'warning',showMidline:false}},
    R:{id:'R',name:'ftvAgentRectangle',groupId:'agentRectangles',points:[{timestamp:1000,value:32},{timestamp:4000,value:30}],
      extendData:{label:'完整R',colorName:'danger',showFill:false}}}
}
function report(commands=payload(),ctx=context(),map=overlays(),before:any[]=[]):any {
  return collectDrawingFeedback(commands,ctx,{getOverlayById:(id:string)=>map[id] ?? null},before,'applied')
}

test('four drawing families require matching object IDs, templates, points, labels, colors and style',()=>{
  const result=report();assert.deepEqual(result.items.map((i:any)=>i.status),['created','created','created','created'])
  assert.equal(result.render_verified,false);assert.equal(result.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(result,drawingInventory(payload())).report_status,'reported')
  for(const field of ['id','name','groupId','price','label','color','midline','fill']) {
    const objects=overlays()
    if(['id','name','groupId'].includes(field))objects.H[field]='wrong'
    if(field==='price')objects.H.points[0].value=32
    if(field==='label')objects.H.extendData.label='H'
    if(field==='color')objects.H.extendData.colorName='info'
    if(field==='midline')objects.C.extendData.showMidline=true
    if(field==='fill')objects.R.extendData.showFill=true
    const checked=report(payload(),context(),objects)
    assert.ok(checked.items.some((i:any)=>i.status==='failed' && i.reason==='overlay_mismatch'),field)
  }
})

test('unsupported periods and missing loaded anchors are hidden by explicit rendering rules',()=>{
  const outside={...trend,to:{time:9,price:32}}
  const result=report(payload([outside,channel,rectangle]),context({ui_interval:'week'}),{})
  assert.deepEqual(result.items.map((i:any)=>i.reason),['anchors_not_loaded','period_mismatch','period_mismatch'])
  assert.ok(result.items.every((i:any)=>i.status==='hidden' && i.visibility==='not_applicable'))
  const conflict=report(payload([channel]),context({ui_interval:'week'}),overlays())
  assert.equal(conflict.items[0].status,'unknown');assert.equal(conflict.items[0].reason,'overlay_mismatch')
})

test('viewport geometry does not treat a crossing segment as hidden or assume a price envelope is the y-axis',()=>{
  const before={...trend,to:{time:2,price:32}}, objects=overlays()
  objects.T.points[1].timestamp=2000
  const result=report(payload([before]),context({visible_range:{available:true,index_from:3,index_to_exclusive:4}}),objects)
  assert.equal(result.items[0].status,'created');assert.equal(result.items[0].visibility,'outside_time_viewport')
  assert.equal(result.items[0].time_range_overlap,false)
  const crossing=report(payload([trend]))
  assert.equal(crossing.items[0].time_range_overlap,true)
  assert.equal(report(payload([trend])).items[0].visibility,'unknown')
  const high={...horizontal,price:100}, highObject=overlays();highObject.H.points[0].value=100
  const warning=report(payload([high]),context(),highObject).items[0]
  assert.equal(warning.status,'created');assert.equal(warning.visibility,'unknown');assert.equal(warning.outside_loaded_price_envelope,true)
  assert.equal(warning.time_range_overlap,true)
})

test('unknown APIs, thrown reads, missing objects, invalid geometry and not-ready context stay distinct',()=>{
  assert.equal(collectDrawingFeedback(payload([horizontal]),context(),{}).items[0].reason,'overlay_api_unavailable')
  const inaccessible={};Object.defineProperty(inaccessible,'getOverlayById',{get(){throw Error('private getter')}})
  assert.equal(collectDrawingFeedback(payload([horizontal]),context(),inaccessible).items[0].reason,'overlay_api_unavailable')
  const thrown=collectDrawingFeedback(payload([horizontal]),context(),{getOverlayById:()=>{throw Error('private detail')}})
  assert.equal(thrown.items[0].status,'unknown');assert.equal(thrown.items[0].reason,'overlay_lookup_failed')
  assert.equal(report(payload([horizontal]),context(),{}).items[0].reason,'overlay_missing')
  assert.equal(report(payload([{...horizontal,price:-1}])).items[0].reason,'invalid_geometry')
  assert.equal(report(payload([horizontal]),context({state:'loading',candles:[]})).items[0].reason,'context_not_ready')
  const getter=overlays();Object.defineProperty(getter.H,'points',{get(){throw Error('private getter')}})
  assert.equal(report(payload([horizontal]),context(),getter).items[0].reason,'overlay_lookup_failed')
})

test('deletions require actual object absence; rolled-back attempts cannot claim desired graphics were created',()=>{
  const deleted=report(payload([]),context(),{},[horizontal])
  assert.equal(deleted.items[0].status,'removed')
  assert.equal(report(payload([]),context(),overlays(),[horizontal]).items[0].reason,'overlay_still_present')
  assert.equal(collectDrawingFeedback(payload([]),context(),{},[horizontal]).items[0].reason,'overlay_api_unavailable')
  const inaccessible=collectDrawingFeedback(payload([]),context(),{getOverlayById:()=>{throw Error('private')}},[horizontal])
  assert.equal(inaccessible.items[0].status,'unknown');assert.equal(inaccessible.items[0].reason,'overlay_lookup_failed')
  assert.equal(report(payload([]),context({state:'loading',candles:[]}),{},[horizontal]).items[0].reason,'context_not_ready')
  for(const phase of ['rolled_back','rollback_unknown']) {
    const result=collectDrawingFeedback(payload([horizontal]),context(),{getOverlayById:()=>overlays().H},[trend],phase)
    assert.ok(result.items.every((i:any)=>i.status==='unknown'))
    assert.ok(!result.items.some((i:any)=>i.status==='created' || i.status==='removed'))
  }
})

test('series feedback reports registry acceptance, hidden period and deletion, never pixels',()=>{
  const registry=new Map([[series.id,series.series_hash]])
  const chart:any={__dshSeriesLineRegistry:registry}
  const accepted=collectDrawingFeedback(payload([series]),context(),chart,[],'applied')
  assert.equal(accepted.evidence_scope,'indicator_registry')
  assert.equal(accepted.items[0].reason,'indicator_registered')
  assert.equal(accepted.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(accepted,drawingInventory(payload([series]))).report_status,'reported')
  const hidden=collectDrawingFeedback(payload([series]),context({ui_interval:'week'}),chart,[],'applied')
  assert.equal(hidden.items[0].status,'hidden')
  assert.equal(hidden.items[0].reason,'period_mismatch')
  registry.clear()
  const removed=collectDrawingFeedback(payload([]),context(),chart,[series],'applied')
  assert.equal(removed.items[0].reason,'indicator_removed')
})

test('price band registry feedback is separate from canvas visibility',()=>{
  const registry=new Map([[band.id,band.band_hash]])
  const chart:any={__dshPriceBandRegistry:registry}
  const accepted=collectDrawingFeedback(payload([band]),context(),chart,[],'applied')
  assert.equal(accepted.items[0].reason,'indicator_registered')
  assert.equal(accepted.evidence_scope,'indicator_registry')
  assert.equal(accepted.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(accepted,drawingInventory(payload([band]))).report_status,'reported')
  const hidden=collectDrawingFeedback(payload([band]),context({ui_interval:'week'}),chart,[],'applied')
  assert.equal(hidden.items[0].reason,'period_mismatch')
  registry.clear()
  assert.equal(collectDrawingFeedback(payload([]),context(),chart,[band],'applied').items[0].reason,'indicator_removed')
})

test('price sticks feedback confirms registry only, with hidden period and deletion',()=>{
  const registry=new Map([[sticks.id,sticks.sticks_hash]])
  const chart:any={__dshPriceSticksRegistry:registry}
  const accepted=collectDrawingFeedback(payload([sticks]),context(),chart,[],'applied')
  assert.equal(accepted.items[0].reason,'indicator_registered')
  assert.equal(accepted.evidence_scope,'indicator_registry')
  assert.equal(accepted.pixel_verified,false)
  assert.equal(sanitizeDrawingFeedback(accepted,drawingInventory(payload([sticks]))).report_status,'reported')
  const hidden=collectDrawingFeedback(payload([sticks]),context({ui_interval:'week'}),chart,[],'applied')
  assert.equal(hidden.items[0].reason,'period_mismatch')
  registry.clear()
  assert.equal(collectDrawingFeedback(payload([]),context(),chart,[sticks],'applied').items[0].reason,'indicator_removed')
})

test('feedback whitelist rejects foreign/duplicate/missing IDs and contradictory claims, and strips private fields',()=>{
  const allowed=drawingInventory(payload([horizontal])), raw=report(payload([horizontal]))
  raw.service_token='private';raw.items[0].secret='private';raw.pixel_verified=true
  const safe=sanitizeDrawingFeedback(raw,allowed)
  assert.equal(safe.report_status,'reported');assert.ok(!JSON.stringify(safe).includes('private'));assert.equal(safe.pixel_verified,false)
  for(const items of [[],[...raw.items,...raw.items],[{...raw.items[0],id:'manual:X'}],[{...raw.items[0],reason:'period_mismatch'}],
    [{...raw.items[0],visibility:'outside_time_viewport'}],[{...raw.items[0],time_range_overlap:'yes'}]]) {
    assert.equal(sanitizeDrawingFeedback({...raw,items},allowed).report_status,'invalid')
  }
  assert.equal(sanitizeDrawingFeedback(null,allowed).report_status,'not_reported')
})

test('real bundled KLineCharts overlay instances expose the object API used by feedback (no DOM or canvas)',()=>{
  const exports:any={}, module={exports}
  runInNewContext(readFileSync(new URL('../view/vendor/klinecharts.min.js',import.meta.url),'utf8'),{exports,module})
  exports.registerOverlay({name:'ftvHorizontalLine',totalStep:1})
  const Overlay=exports.getOverlayClass('ftvHorizontalLine'), instance=new Overlay()
  instance.setId('H');instance.setGroupId('agentHorizontalLines');instance.setPoints([{timestamp:4000,value:31}])
  instance.setExtendData({label:'完整H',colorName:'success'})
  const result=collectDrawingFeedback(payload([horizontal]),context(),{getOverlayById:()=>instance})
  assert.equal(result.items[0].status,'created');assert.equal(result.pixel_verified,false)
})

test('JavaScript and Python feedback contracts agree without upgrading browser reports into pixels',()=>{
  const raw=report(), allowed=drawingInventory(payload())
  const child=spawnSync(TEST_PYTHON,['-c',
    'import json,sys; from tools.drawing_feedback import sanitize_drawing_feedback; x=json.load(sys.stdin); print(json.dumps(sanitize_drawing_feedback(x["raw"],x["allowed"])))'],
    {encoding:'utf8',input:JSON.stringify({raw,allowed})})
  assert.equal(child.status,0,child.stderr);assert.deepEqual(JSON.parse(child.stdout),sanitizeDrawingFeedback(raw,allowed))
})

test('telemetry failures do not stop chart observation or expose exception text, and disposal does not read it',async()=>{
  const calls:any[]=[];let captures=0
  const publisher=createChartContextPublisher({conversationId:'A',viewId:'v'.repeat(32),capture:()=>context(),isActive:()=>true,
    feedback:()=>{captures++;throw Error('private-secret')},transport:async body=>{calls.push(body);return {ok:true}}})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(calls.length,1);assert.equal(calls[0].drawing_feedback.report_status,'invalid')
  assert.equal(calls[0].state.state,'ready');assert.ok(!JSON.stringify(calls).includes('private-secret'))
  publisher.dispose();await new Promise(resolve=>setImmediate(resolve))
  assert.equal(captures,1);assert.equal(calls[1].active,false)
})
