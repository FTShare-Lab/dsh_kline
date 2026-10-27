import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { sanitizePriceBandCommand } from '../src/price-bands.ts'
import { drawingInventory, sanitizeChartContext } from '../src/chart-observation.ts'

const id='band_'+'a'.repeat(24),hash='b'.repeat(64)
const base={type:'DRAW_AGENT_PRICE_BAND',id,interval:'day',label:'高低价带',color:'warning',bar_count:4,
  upper_source:{kind:'high'},lower_source:{kind:'low'},condition:null,
  upper_values:[12,null,13,14],lower_values:[9,null,10,11],band_hash:hash}
const boll={...base,label:'BOLL20',
  upper_source:{kind:'bbands',output:'upperband',period:20,deviation_up:2,deviation_down:2,matype:0},
  lower_source:{kind:'bbands',output:'lowerband',period:20,deviation_up:2,deviation_down:2,matype:0},
  middle_values:[10,null,11,12]}

test('band source preserves paired gaps and one stable observation identity',()=>{
  const clean=sanitizePriceBandCommand(base,4,'day')
  assert.deepEqual(clean.upper_values,[12,null,13,14])
  const inventory=drawingInventory({interval:'day',chartCommands:[clean]})
  assert.equal(inventory.length,1);assert.equal(inventory[0].band_hash,hash)
  const rows=[1,2,3,4].map(time=>({time,open:10,high:12,low:9,close:11,volume:1}))
  const observed=sanitizeChartContext({state:'ready',symbol:'TEST.X',interval:'day',source_interval:'day',ui_interval:'day',
    adjust:'none',range_key:'custom',source_chart_session:'c'.repeat(32),candles:rows,drawings:inventory,
    visible_range:{available:true,index_from:0,index_to_exclusive:4}})
  assert.equal(observed.drawings[0].band_hash,hash)
  assert.equal(sanitizePriceBandCommand(base,2,'week').interval,'day')
})

test('band source rejects crossed, unmatched, empty and unaligned values',()=>{
  const cases=[{...base,upper_values:[12,null,13,14],lower_values:[9,9,10,11]},
    {...base,upper_values:[12,null,8,14]},
    {...base,upper_values:[null,null,null,null],lower_values:[null,null,null,null]},
    {...base,bar_count:3},{...base,upper_source:{kind:'sma',period:1}}]
  for(const candidate of cases)assert.throws(()=>sanitizePriceBandCommand(candidate,4,'day'))
  assert.throws(()=>sanitizePriceBandCommand(base,3,'day'))
})

test('BBANDS three aligned outputs remain one guarded band identity',()=>{
  const clean=sanitizePriceBandCommand(boll,4,'day')
  assert.deepEqual(clean.middle_values,[10,null,11,12])
  assert.equal(drawingInventory({interval:'day',chartCommands:[clean]}).length,1)
  for(const invalid of [
    {...boll,middle_values:[10,10,11,12]},
    {...boll,middle_values:[10,null,14,12]},
    {...boll,lower_source:{...boll.lower_source,deviation_down:3}},
    {...boll,condition:{left:{kind:'close'},op:'gt',right:{constant:10}}},
    {...boll,middle_values:undefined},
    {...base,middle_values:[10,null,11,12]},
  ])assert.throws(()=>sanitizePriceBandCommand(invalid,4,'day'))
})

test('inline band renderer uses price-pane polygon quads without bridging gaps or resetting data',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const snippet=html.slice(html.indexOf('function drawAgentPriceBandCommands('),html.indexOf('let pendingLiveDrawingPayload = null;'))
  const registered:any[]=[],created:any[]=[],removed:any[]=[],registry=new Map()
  const rows=[1,2,3,4].map(time=>({time}))
  const state:any={currentInterval:'day',currentCandles:rows,agentBandRegistry:registry,
    activeAgentBandIndicators:new Set(),registeredAgentBandIndicators:new Set(),
    window:{klinecharts:{registerIndicator:(indicator:any)=>registered.push(indicator)}},
    colorFor:()=> '#aabbcc',kchart:{createIndicator:(...args:any[])=>{created.push(args);return 'ok'},
      removeIndicator:(...args:any[])=>removed.push(args),applyNewData:()=>assert.fail('must not reset candles')}}
  const draw=runInNewContext(snippet+';drawAgentPriceBandCommands',state)
  draw([base],true)
  assert.equal(registered.length,1);assert.equal(created[0][2].id,'candle_pane')
  assert.equal(registry.get(id),hash)
  const calculated=registered[0].calc(rows.map(row=>({timestamp:row.time*1000})),created[0][0])
  assert.equal(calculated[1].upper,undefined)
  const polygon=registered[0].figures[0]
  assert.equal(polygon.type,'polygon')
  assert.equal(polygon.attrs({coordinate:{current:{x:1,upper:12,lower:9},next:{x:2}}}),null)
  const quad=polygon.attrs({coordinate:{current:{x:1,upper:12,lower:9},next:{x:2,upper:13,lower:10}}})
  assert.equal(quad.coordinates.length,4)
  draw([],true)
  assert.equal(registry.size,0);assert.ok(removed.length>0)
})

test('inline BBANDS renderer draws upper, middle and lower as one price-pane indicator',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const snippet=html.slice(html.indexOf('function drawAgentPriceBandCommands('),html.indexOf('let pendingLiveDrawingPayload = null;'))
  const registered:any[]=[],created:any[]=[],registry=new Map()
  const rows=[1,2,3,4].map(time=>({time}))
  const state:any={currentInterval:'day',currentCandles:rows,agentBandRegistry:registry,
    activeAgentBandIndicators:new Set(),registeredAgentBandIndicators:new Set(),
    window:{klinecharts:{registerIndicator:(indicator:any)=>registered.push(indicator)}},
    colorFor:()=> '#aabbcc',kchart:{createIndicator:(...args:any[])=>{created.push(args);return 'ok'},
      removeIndicator:()=>{},applyNewData:()=>assert.fail('must not reset candles')}}
  const draw=runInNewContext(snippet+';drawAgentPriceBandCommands',state)
  draw([boll],true)
  assert.equal(registered.length,1)
  assert.equal(created.length,1)
  assert.equal(created[0][2].id,'candle_pane')
  assert.equal(registry.get(id),hash)
  assert.deepEqual(Array.from(registered[0].figures,(figure:any)=>figure.key),['upper','upper','lower','middle'])
  const calculated=registered[0].calc(rows.map(row=>({timestamp:row.time*1000})),created[0][0])
  assert.equal(calculated[1].middle,undefined)
  assert.equal(calculated[2].middle,11)
  const mid=registered[0].figures[3]
  assert.equal(mid.attrs({coordinate:{current:{x:1,middle:11},next:{x:2}}}),null)
  assert.equal(mid.attrs({coordinate:{current:{x:1,middle:11},next:{x:2,middle:12}}}).coordinates.length,2)
})

test('bundled KLineCharts v9 has the polygon figure required by the band renderer',()=>{
  const exports:any={},module={exports}
  runInNewContext(readFileSync(new URL('../view/vendor/klinecharts.min.js',import.meta.url),'utf8'),{exports,module})
  assert.ok(exports.getSupportedFigures().includes('polygon'))
  exports.registerIndicator({name:'ftvBandCompatibilityTest',shortName:'band',series:'price',
    calc:(dataList:any[])=>dataList.map(()=>({upper:2,lower:1})),
    figures:[{key:'upper',title:'',type:'polygon',attrs:()=>({coordinates:[{x:1,y:1},{x:2,y:1},{x:2,y:2},{x:1,y:2}]}),
      styles:()=>({style:'fill',color:'#aabbcc24'})}]})
  assert.ok(exports.getSupportedIndicators().includes('ftvBandCompatibilityTest'))
})
