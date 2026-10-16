import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'
import { latestChart, latestChartFromEvents } from '../src/client/conversation.ts'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
test('create update delete results select their owning chart; read-only results do not', () => {
  for (const action of ['create', 'update', 'delete']) {
    const name = `mcp__dsh-kline__${action}_horizontal_line`
    const content = [{type:'text', text:`chart_session=${'a'.repeat(32)}`}]
    assert.equal(latestChart([{kind:'tool-result',call:{name},callTime:2,content}])?.session, 'a'.repeat(32))
    assert.equal(latestChartFromEvents([
      {type:'event',event:{type:'tool/call',time:2,data:{name,callId:'id'}}},
      {type:'event',event:{type:'tool/result',time:3,data:{message:{content:[{type:'tool-result',toolCallId:'id',content}]}}}},
    ])?.session, 'a'.repeat(32))
  }
  assert.equal(latestChart([{kind:'tool-result',call:{name:'mcp__dsh-kline__get_horizontal_lines'},content:[{text:`chart_session=${'b'.repeat(32)}`}]}]), undefined)
})

test('drawing-only results preserve cached candles and toggles, replace only AI horizontal lines', () => {
  const candles = {type:'SET_CANDLES', rows:[{time:1,close:30}]}
  const saved = {session:'parent', payload:{symbol:'A',interval:'day',range_key:'custom',indicators:['rsi'],chartCommands:[candles,{type:'DRAW_HORIZONTAL_LINE',id:'old'}]}}
  const line = {type:'DRAW_HORIZONTAL_LINE',id:'A',price:29.5}
  const incoming = {drawing_only:true,drawing_parent_session:'parent',symbol:'A',interval:'day',chartCommands:[{type:'SET_CANDLES',rows:[]},line]}
  const merged = mergeHorizontalLineSnapshot(incoming,saved)
  assert.deepEqual(merged.chartCommands, [candles,line])
  assert.deepEqual(merged.indicators,['rsi'])
  assert.equal(merged.indicators_explicit,false)
  assert.equal(merged.range_key,'custom')
  assert.equal(mergeHorizontalLineSnapshot({...incoming,symbol:'B'},saved),undefined)
  assert.equal(mergeHorizontalLineSnapshot({...incoming,interval:'week'},saved),undefined)
  assert.equal(mergeHorizontalLineSnapshot(incoming,{...saved,session:'other'}),undefined)
})

test('horizontal renderer uses exact price, stable ID and a separate locked group', () => {
  const overlays: any[] = [], removed: any[] = []
  const source = html.slice(html.indexOf('function drawHorizontalLineCommands('),html.indexOf('function isSupportResistanceLevel('))
  const render = runInNewContext(source + '; drawHorizontalLineCommands', {
    currentCandles:[{time:1700000000}], kchart:{removeOverlay:(v:any)=>removed.push(v),createOverlay:(v:any)=>overlays.push(v)},
  })
  render([{type:'DRAW_HORIZONTAL_LINE',id:'A',price:29.5,label:'观察线'}, {type:'TEXT_MARKER',price:31}, {type:'DRAW_HORIZONTAL_LINE',price:NaN}])
  assert.equal(overlays.length,1)
  assert.equal(overlays[0].id,'A')
  assert.equal(overlays[0].points[0].value,29.5)
  assert.equal(overlays[0].extendData.label,'观察线')
  assert.equal(overlays[0].lock,true)
  assert.equal(removed[0].groupId,'agentHorizontalLines')
  render([])
  assert.equal(removed.length,2)
})

test('line template draws across the pane, not a support/resistance text marker', () => {
  const overlays: any[] = []
  let hasPercentAxis = false
  const source = html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))
  // Stop after registering the first overlay; later unrelated indicators need a full chart fixture.
  runInNewContext(source + '; try { registerOverlays() } catch {}', {
    overlaysRegistered:false, window:{klinecharts:{registerOverlay:(v:any)=>{overlays.push(v); if(overlays.length===2)throw Error('stop')}}},
    console:{warn(){}}, colorFor:()=> 'blue',
    document:{getElementById:()=>hasPercentAxis ? {} : null},rightAxisGutterWidth:()=>80,
  })
  const figures = overlays[0].createPointFigures({overlay:{extendData:{label:'A',price:30}},coordinates:[{x:500,y:100}],bounding:{width:800}})
  assert.equal(figures[0].type,'line')
  assert.deepEqual(Array.from(figures[0].attrs.coordinates, (v:any)=>[v.x,v.y]),[[0,100],[800,100]])
  assert.equal(figures[1].attrs.text,'A 30')
  assert.equal(figures[1].styles.color,'#ffffff')
  assert.equal(figures[1].styles.backgroundColor,'blue')
  hasPercentAxis = true
  const productFigures = overlays[0].createPointFigures({overlay:{extendData:{label:'A',price:30}},coordinates:[{x:500,y:100}],bounding:{width:800}})
  assert.equal(productFigures[0].attrs.coordinates[1].x,720)
  assert.equal(productFigures[1].attrs.x,714)
})

test('indicator redraws preserve AI lines and drawing-only tasks skip candle refetch', () => {
  assert.match(html,/\.\.\.lastHorizontalLines/)
  assert.match(html,/!structured.drawing_only && !structured.local_render && isIntradayRange/)
  assert.match(html,/!structured.drawing_only && !structured.local_render && !structured.range_key/)
  const clear = html.slice(html.indexOf('function clearOverlays('), html.indexOf('function formatPrice('))
  assert.doesNotMatch(clear,/agentHorizontalLines/)
})

test('standalone theme observation does not retrigger itself for an unchanged theme', () => {
  let writes = 0, theme = 'light'
  const dataset = Object.defineProperty({}, 'theme', {get:()=>theme,set:value=>{ writes++; theme=value }})
  const source = html.slice(html.indexOf('function applyTheme('),html.indexOf('async function setTheme('))
  const apply = runInNewContext(source + '; applyTheme', {
    document:{documentElement:{dataset}},currentTheme:()=> 'light',refreshChartTheme(){},syncThemeToggle(){},
  })
  apply(); apply()
  assert.equal(writes,0)
  theme = 'dark'; apply(); apply()
  assert.equal(writes,1)
  assert.equal(theme,'light')
})
