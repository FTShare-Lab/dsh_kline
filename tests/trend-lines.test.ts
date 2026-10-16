import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'
import { latestChart } from '../src/client/conversation.ts'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
test('trend mutation selects new chart; read/error never select it', () => {
  for (const action of ['create','update','delete']) {
    const node = {kind:'tool-result',call:{name:`mcp__dsh_kline__${action}_trend_line_ab12`},content:[{text:`chart_session=${'a'.repeat(32)}`}],callTime:2}
    assert.equal(latestChart([node])?.session,'a'.repeat(32))
    assert.equal(latestChart([{...node,isError:true}]),undefined)
  }
  assert.equal(latestChart([{kind:'tool-result',call:{name:'mcp__dsh_kline__get_trend_lines'},content:[{text:`chart_session=${'a'.repeat(32)}`}]}]),undefined)
})

test('mixed edits replace both AI families while preserving automatic lines and toggles', () => {
  const auto = {type:'DRAW_TREND_LINE',id:'auto'}, candles = {type:'SET_CANDLES',rows:[{time:1}]}
  const saved = {session:'parent',payload:{symbol:'A',interval:'day',indicators:[],range_key:'custom',chartCommands:[candles,auto,{type:'DRAW_AGENT_TREND_LINE',id:'old'},{type:'DRAW_HORIZONTAL_LINE',price:31}]}}
  const incoming = {drawing_only:true,drawing_parent_session:'parent',symbol:'A',interval:'day',chartCommands:[{type:'DRAW_HORIZONTAL_LINE',price:31},{type:'DRAW_AGENT_TREND_LINE',id:'new'}]}
  const merged = mergeHorizontalLineSnapshot(incoming,saved)
  assert.deepEqual(merged.chartCommands,[candles,auto,...incoming.chartCommands])
  assert.deepEqual(merged.indicators,[])
  assert.equal(merged.range_key,'custom')
})

test('trend renderer uses two exact anchors, stable ID and separate locked group; no snapping', () => {
  const overlays:any[] = [], removed:any[] = []
  const source = html.slice(html.indexOf('function drawAgentTrendLineCommands('),html.indexOf('function isSupportResistanceLevel('))
  const render = runInNewContext(source + '; drawAgentTrendLineCommands', {currentCandles:[{time:1},{time:2},{time:3}],kchart:{removeOverlay:(v:any)=>removed.push(v),createOverlay:(v:any)=>overlays.push(v)}})
  const line = {type:'DRAW_AGENT_TREND_LINE',id:'T',from:{time:1,price:32},to:{time:3,price:30},label:'T1'}
  render([line,{...line,from:{time:1.5,price:32}},{...line,to:{time:1,price:30}},{...line,to:{time:3,price:NaN}}])
  assert.equal(overlays.length,1)
  assert.deepEqual(Array.from(overlays[0].points,(p:any)=>[p.timestamp,p.value]),[[1000,32],[3000,30]])
  assert.equal(overlays[0].id,'T'); assert.equal(overlays[0].lock,true)
  assert.equal(overlays[0].groupId,'agentTrendLines')
  assert.equal(overlays[0].extendData.agent,true)
  let prevented = false
  assert.equal(overlays[0].onRightClick({preventDefault(){prevented=true}}),true)
  assert.equal(prevented,true)
  render([]); assert.equal(removed.length,2)
})

test('redraw and symbol reset preserve/isolate AI trends; automatic clear never owns them', () => {
  assert.match(html,/\.\.\.lastAgentTrendLines/)
  assert.match(html,/DRAW_AGENT_TREND_LINE"\) lastAgentTrendLines.push/)
  assert.match(html,/lastHorizontalLines = \[\];\s+lastAgentTrendLines = \[\];/)
  const clear = html.slice(html.indexOf('function clearAnalysisAnnotations('),html.indexOf('function clearAnalysisAnnotations(')+1800)
  assert.doesNotMatch(clear,/lastAgentTrendLines|agentTrendLines|DRAW_AGENT_TREND_LINE/)
})
