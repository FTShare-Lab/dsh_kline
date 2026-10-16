import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Script, runInNewContext } from 'node:vm'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'
import { latestChart, latestChartFromEvents } from '../src/client/conversation.ts'
import { collectDrawingFeedback } from '../src/drawing-feedback.ts'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
test('full inline chart script remains syntactically valid after channel integration', () => {
  const source=html.slice(html.indexOf('<script>')+8,html.lastIndexOf('</script>'))
  assert.doesNotThrow(()=>new Script(source))
})

test('channel mutations select owning snapshot; reads and parameter verification never select charts', () => {
  for(const action of ['create','update','delete']) {
    const name = `mcp__dsh-kline__${action}_channel_ab12`
    const content = [{type:'text',text:`chart_session=${'a'.repeat(32)}`}]
    assert.equal(latestChart([{kind:'tool-result',call:{name},callTime:2,content}])?.session,'a'.repeat(32))
    assert.equal(latestChartFromEvents([
      {type:'event',event:{type:'tool/call',time:2,data:{name,callId:'id'}}},
      {type:'event',event:{type:'tool/result',time:3,data:{message:{content:[{type:'tool-result',toolCallId:'id',content}]}}}},
    ])?.session,'a'.repeat(32))
    assert.equal(latestChart([{kind:'tool-result',call:{name},content,isError:true}]),undefined)
  }
  for(const name of ['get_channels','verify_chart_drawings'])
    assert.equal(latestChart([{kind:'tool-result',call:{name:'mcp__dsh_kline__'+name},content:[{text:`chart_session=${'b'.repeat(32)}`}]}]),undefined)
})

test('mixed snapshot merge replaces AI channels/lines and preserves candles, auto annotations and preferences', () => {
  const candles = {type:'SET_CANDLES',rows:[{time:1}]}, auto = {type:'DRAW_TREND_LINE',id:'auto'}
  const channel = {type:'DRAW_AGENT_CHANNEL',id:'C'}, horizontal = {type:'DRAW_HORIZONTAL_LINE',id:'H'}, trend = {type:'DRAW_AGENT_TREND_LINE',id:'T'}
  const saved = {session:'parent',payload:{symbol:'A',interval:'day',indicators:[],range_key:'custom',chartCommands:[candles,auto,channel,horizontal,trend]}}
  const incoming = {drawing_only:true,drawing_parent_session:'parent',symbol:'A',interval:'day',chartCommands:[{type:'DRAW_AGENT_CHANNEL',id:'C2'},horizontal,trend]}
  const merged = mergeHorizontalLineSnapshot(incoming,saved)
  assert.deepEqual(merged.chartCommands,[candles,auto,...incoming.chartCommands])
  assert.deepEqual(merged.indicators,[]); assert.equal(merged.range_key,'custom')
  assert.equal(mergeHorizontalLineSnapshot({...incoming,symbol:'B'},saved),undefined)
  assert.equal(mergeHorizontalLineSnapshot({...incoming,interval:'week'},saved),undefined)
})

function channel():any {
  return {type:'DRAW_AGENT_CHANNEL',id:'C',interval:'day',geometry_basis:'candle_index_linear_price',
    from:{time:1,price:30},to:{time:4,price:33},parallel:{time:2,price:33},
    upper:{from:{time:1,price:32},to:{time:4,price:35}},lower:{from:{time:1,price:30},to:{time:4,price:33}},
    color:'success',label:'完整上升通道',show_midline:true}
}

test('renderer creates one locked channel overlay with four exact points, atomic ID and stable group', () => {
  const overlays:any[] = [], removed:any[] = []
  const source = html.slice(html.indexOf('function drawAgentChannelCommands('),html.indexOf('function isSupportResistanceLevel('))
  const render = runInNewContext(source+'; drawAgentChannelCommands', {currentInterval:'day',currentCandles:[{time:1},{time:2},{time:3},{time:4}],
    kchart:{removeOverlay:(v:any)=>removed.push(v),createOverlay:(v:any)=>overlays.push(v)}})
  const valid = channel()
  const invalid = [ {...valid,interval:'week'}, {...valid,geometry_basis:'calendar_time'}, {...valid,parallel:{time:1.5,price:33}},
    {...valid,upper:{...valid.upper,to:{time:3,price:35}}}, {...valid,upper:{...valid.upper,to:{time:4,price:36}}},
    {...valid,upper:{...valid.upper,to:{time:4,price:NaN}}}, {...valid,lower:{...valid.lower,to:{time:4,price:-1}}} ]
  render([valid,...invalid])
  assert.equal(overlays.length,1)
  const overlay = overlays[0]
  assert.equal(overlay.id,'C'); assert.equal(overlay.groupId,'agentChannels'); assert.equal(overlay.lock,true)
  assert.deepEqual(Array.from(overlay.points,(p:any)=>[p.timestamp,p.value]),[[1000,32],[4000,35],[1000,30],[4000,33]])
  assert.equal(overlay.extendData.label,'完整上升通道'); assert.equal(overlay.extendData.colorName,'success')
  assert.equal(overlay.extendData.showMidline,true)
  let prevented=false
  assert.equal(overlay.onRightClick({preventDefault(){prevented=true}}),true); assert.equal(prevented,true)
  render([]); assert.equal(removed.length,2); assert.equal(removed[1].groupId,'agentChannels')
})

test('renderer tolerates floating-point cancellation without accepting converging boundaries', () => {
  const overlays:any[] = []
  const source = html.slice(html.indexOf('function drawAgentChannelCommands('),html.indexOf('function isSupportResistanceLevel('))
  const render = runInNewContext(source+'; drawAgentChannelCommands', {currentInterval:'day',currentCandles:[{time:1},{time:2},{time:4}],
    kchart:{removeOverlay(){},createOverlay:(v:any)=>overlays.push(v)}})
  const large=channel(); large.upper={from:{time:1,price:1e8+.001},to:{time:4,price:2e8+.001}}
  large.lower={from:{time:1,price:1e8},to:{time:4,price:2e8}}
  render([large]); assert.equal(overlays.length,1)
})

test('daily channel survives a day-week-day aggregation round trip without snapping anchors or changing style', () => {
  const times=['2026-09-10','2026-09-11','2026-09-14','2026-09-15'].map(d=>Date.parse(d+'T15:00:00+08:00')/1000)
  const rows=times.map((time,i)=>({time,open:31+i,high:33+i,low:30+i,close:32+i,volume:i+1}))
  const c=channel()
  for(const edge of ['upper','lower']){c[edge].from.time=times[0];c[edge].to.time=times[3]}
  c.from.time=times[0];c.to.time=times[3];c.parallel.time=times[1]
  const original=JSON.stringify(c),objects=new Map<string,any>()
  const state:any={exchangeTimezone:'Asia/Shanghai',currentInterval:'day',currentCandles:rows,kchart:{
    removeOverlay:()=>objects.clear(),createOverlay:(o:any)=>{objects.set(o.id,o);return o.id},getOverlayById:(id:string)=>objects.get(id)??null}}
  const source=html.slice(html.indexOf('function aggregateRowsForInterval('),html.indexOf('function localFiniteMap('))
    +html.slice(html.indexOf('function drawAgentChannelCommands('),html.indexOf('function isSupportResistanceLevel('))
  const api=runInNewContext(source+'; ({aggregateRowsForInterval,drawAgentChannelCommands})',state)
  const inspect=()=>collectDrawingFeedback({chartCommands:[c]}, {state:'ready',interval:state.currentInterval,
    ui_interval:state.currentInterval,candles:state.currentCandles,visible_range:{available:false}},state.kchart)
  api.drawAgentChannelCommands([c],true)
  const daily=JSON.stringify(objects.get(c.id));assert.equal(inspect().items[0].status,'created')
  state.currentInterval='week';state.currentCandles=api.aggregateRowsForInterval(rows,'week')
  assert.equal(state.currentCandles.length,2)
  assert.deepEqual(JSON.parse(JSON.stringify(state.currentCandles)),[
    {time:times[1],open:31,high:34,low:30,close:33,volume:3},
    {time:times[3],open:33,high:36,low:32,close:35,volume:7}])
  api.drawAgentChannelCommands([c],true)
  assert.equal(objects.size,0)
  assert.equal(inspect().items[0].reason,'period_mismatch')
  assert.equal(inspect().items[0].status,'hidden')
  state.currentInterval='day';state.currentCandles=api.aggregateRowsForInterval(rows,'day')
  api.drawAgentChannelCommands([c],true)
  assert.equal(JSON.stringify(objects.get(c.id)),daily)
  assert.equal(JSON.stringify(c),original)
  assert.equal(inspect().items[0].status,'created')
  assert.equal(inspect().pixel_verified,false)
})

test('channel template draws two parallel edges, optional dashed midpoint and full white label', () => {
  const templates:any[] = []
  const source = html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))
  runInNewContext(source+'; registerOverlays()', {overlaysRegistered:false,
    window:{klinecharts:{registerOverlay:(v:any)=>{templates.push(v);if(v.name==='ftvAgentChannel')throw Error('stop')}}},console:{warn(){}},colorFor:()=> 'green'})
  const template=templates.find(t=>t.name==='ftvAgentChannel')
  assert.ok(template); assert.equal(template.needDefaultPointFigure,false)
  assert.equal(template.totalStep,5) // vendor totalStep includes the completion step
  const coordinates=[{x:10,y:20},{x:100,y:80},{x:10,y:40},{x:100,y:100}]
  const figures=template.createPointFigures({overlay:{extendData:{label:'完整上升通道',showMidline:true,colorName:'success'}},coordinates})
  assert.equal(figures.length,4)
  assert.equal(figures[0].type,'line'); assert.equal(figures[1].type,'line')
  assert.deepEqual(Array.from(figures[2].attrs.coordinates,(p:any)=>[p.x,p.y]),[[10,30],[100,90]])
  assert.equal(figures[2].styles.style,'dashed')
  assert.equal(figures[3].attrs.text,'完整上升通道'); assert.equal(figures[3].styles.color,'#ffffff')
  assert.equal(template.createPointFigures({overlay:{extendData:{showMidline:false}},coordinates}).length,2)
  assert.equal(template.createPointFigures({overlay:{extendData:{}},coordinates:[]}).length,0)
})

test('channels persist in redraw/cache and reset with symbol; automatic analysis clear never removes them', () => {
  assert.match(html,/DRAW_AGENT_CHANNEL"\) lastAgentChannels.push/)
  assert.match(html,/\.\.\.lastAgentChannels/)
  assert.match(html,/lastAgentTrendLines = \[\];\s+lastAgentChannels = \[\];/)
  assert.match(html,/drawAgentChannelCommands\(cmds\)/)
  const clear = html.slice(html.indexOf('function clearAnalysisAnnotations('),html.indexOf('function clearAnalysisAnnotations(')+1800)
  assert.doesNotMatch(clear,/DRAW_AGENT_CHANNEL|lastAgentChannels|agentChannels/)
})
