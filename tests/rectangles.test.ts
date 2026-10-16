import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'
import { latestChart, latestChartFromEvents } from '../src/client/conversation.ts'

const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
test('rectangle mutations select their own latest snapshot; reads and failed calls never select a chart', () => {
  for(const action of ['create','update','delete']) {
    const name=`mcp__dsh-kline__${action}_rectangle_ab12`, content=[{type:'text',text:`chart_session=${'a'.repeat(32)}`}]
    assert.equal(latestChart([{kind:'tool-result',call:{name},callTime:2,content}])?.session,'a'.repeat(32))
    assert.equal(latestChartFromEvents([
      {type:'event',event:{type:'tool/call',time:2,data:{name,callId:'id'}}},
      {type:'event',event:{type:'tool/result',time:3,data:{message:{content:[{type:'tool-result',toolCallId:'id',content}]}}}},
    ])?.session,'a'.repeat(32))
    assert.equal(latestChart([{kind:'tool-result',call:{name},content,isError:true}]),undefined)
  }
  assert.equal(latestChart([{kind:'tool-result',call:{name:'mcp__dsh_kline__get_rectangles'},content:[{text:`chart_session=${'b'.repeat(32)}`}]}]),undefined)
})

test('mixed cache merge replaces/deletes AI rectangles and retains lines/channels, candles and preferences', () => {
  const candles={type:'SET_CANDLES',rows:[{time:1}]}, auto={type:'DRAW_TREND_LINE',id:'auto'}
  const others=[{type:'DRAW_HORIZONTAL_LINE',id:'H'},{type:'DRAW_AGENT_TREND_LINE',id:'T'},{type:'DRAW_AGENT_CHANNEL',id:'C'}]
  const old={type:'DRAW_AGENT_RECTANGLE',id:'R',lower_price:30}, next={...old,lower_price:29.5}
  const saved={session:'parent',payload:{symbol:'A',interval:'day',indicators:[],range_key:'custom',chartCommands:[candles,auto,...others,old]}}
  const incoming={drawing_only:true,drawing_parent_session:'parent',symbol:'A',interval:'day',chartCommands:[...others,next]}
  const merged=mergeHorizontalLineSnapshot(incoming,saved)
  assert.deepEqual(merged.chartCommands,[candles,auto,...others,next])
  assert.deepEqual(merged.indicators,[]); assert.equal(merged.range_key,'custom')
  assert.deepEqual(mergeHorizontalLineSnapshot({...incoming,chartCommands:others},saved).chartCommands,[candles,auto,...others])
  assert.equal(mergeHorizontalLineSnapshot({...incoming,symbol:'B'},saved),undefined)
  assert.equal(mergeHorizontalLineSnapshot({...incoming,interval:'week'},saved),undefined)
})

function rectangle():any {
  return {type:'DRAW_AGENT_RECTANGLE',id:'R',interval:'day',start_time:1,end_time:4,lower_price:30,upper_price:33,
    label:'完整整理平台',color:'warning',show_fill:true}
}

test('renderer creates one locked lower-z rectangle with exact bounds, stable ID and no snapping', () => {
  const overlays:any[]=[], removed:any[]=[]
  const source=html.slice(html.indexOf('function drawAgentRectangleCommands('),html.indexOf('function isSupportResistanceLevel('))
  const render=runInNewContext(source+'; drawAgentRectangleCommands',{currentInterval:'day',currentCandles:[{time:1},{time:2},{time:3},{time:4}],
    kchart:{removeOverlay:(v:any)=>removed.push(v),createOverlay:(v:any)=>overlays.push(v)}})
  const valid=rectangle()
  render([valid,{...valid,interval:'week'},{...valid,start_time:1.5},{...valid,end_time:1},{...valid,lower_price:33},
    {...valid,upper_price:NaN},{...valid,lower_price:-1}])
  assert.equal(overlays.length,1)
  const r=overlays[0]
  assert.equal(r.id,'R'); assert.equal(r.groupId,'agentRectangles'); assert.equal(r.lock,true); assert.equal(r.zLevel,-1)
  assert.deepEqual(Array.from(r.points,(p:any)=>[p.timestamp,p.value]),[[1000,33],[4000,30]])
  assert.equal(r.extendData.label,'完整整理平台'); assert.equal(r.extendData.colorName,'warning'); assert.equal(r.extendData.showFill,true)
  let prevented=false
  assert.equal(r.onRightClick({preventDefault(){prevented=true}}),true); assert.equal(prevented,true)
  render([]); assert.equal(removed.length,2); assert.equal(removed[1].groupId,'agentRectangles')
  render([{...valid,show_fill:false}]); assert.equal(overlays.at(-1).extendData.showFill,false)
})

test('rectangle template has four-edge border, matching translucent fill and full white label; fill can be disabled', () => {
  const templates:any[]=[]
  const source=html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))
  runInNewContext(source+'; registerOverlays()',{overlaysRegistered:false,
    window:{klinecharts:{registerOverlay:(v:any)=>{templates.push(v);if(v.name==='ftvAgentRectangle')throw Error('stop')}}},
    console:{warn(){}},colorFor:()=> '#ff7a00'})
  const template=templates.find(t=>t.name==='ftvAgentRectangle')
  assert.ok(template); assert.equal(template.totalStep,3); assert.equal(template.needDefaultPointFigure,false)
  const coordinates=[{x:10,y:20},{x:100,y:80}]
  const figures=template.createPointFigures({overlay:{extendData:{label:'完整整理平台',showFill:true}},coordinates})
  assert.equal(figures.length,2); assert.equal(figures[0].type,'rect')
  assert.equal(figures[0].attrs.x,10); assert.equal(figures[0].attrs.y,20)
  assert.equal(figures[0].attrs.width,90); assert.equal(figures[0].attrs.height,60)
  assert.equal(figures[0].styles.style,'stroke_fill'); assert.equal(figures[0].styles.borderColor,'#ff7a00')
  assert.equal(figures[0].styles.color,'#ff7a0018')
  assert.equal(figures[1].attrs.text,'完整整理平台'); assert.equal(figures[1].styles.color,'#ffffff')
  const outline=template.createPointFigures({overlay:{extendData:{showFill:false}},coordinates})
  assert.equal(outline.length,1); assert.equal(outline[0].styles.style,'stroke')
  assert.equal(template.createPointFigures({overlay:{extendData:{}},coordinates:[]}).length,0)
})

test('rectangle style uses vendor-supported border/fill modes, not fill-only mode which drops borders', () => {
  const vendor=readFileSync(new URL('../view/vendor/klinecharts.min.js',import.meta.url),'utf8')
  assert.match(vendor,/StrokeFill="stroke_fill"/)
  assert.match(vendor,/Stroke="stroke"/)
  assert.match(html,/style: ex.showFill \? "stroke_fill" : "stroke"/)
})

test('rectangles persist in redraw/cache and reset on symbol; automatic analysis clear never owns them', () => {
  assert.match(html,/DRAW_AGENT_RECTANGLE"\) lastAgentRectangles.push/)
  assert.match(html,/\.\.\.lastAgentRectangles/)
  assert.match(html,/lastAgentChannels = \[\];\s+lastAgentRectangles = \[\];/)
  assert.match(html,/drawAgentRectangleCommands\(cmds\)/)
  const clear=html.slice(html.indexOf('function clearAnalysisAnnotations('),html.indexOf('function clearAnalysisAnnotations(')+1800)
  assert.doesNotMatch(clear,/DRAW_AGENT_RECTANGLE|lastAgentRectangles|agentRectangles/)
})
