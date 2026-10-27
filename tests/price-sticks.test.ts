import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {runInNewContext} from 'node:vm'
import {sanitizePriceSticksCommand} from '../src/price-sticks.ts'
import {drawingInventory, sanitizeChartContext} from '../src/chart-observation.ts'

const id='sticks_'+'a'.repeat(24),hash='b'.repeat(64)
const base={type:'DRAW_AGENT_PRICE_STICKS',id,interval:'day',label:'高低柱线',color:'warning',bar_count:4,
  start_source:{kind:'high'},end_source:{kind:'low'},condition:null,
  start_values:[12,null,13,14],end_values:[9,null,10,11],sticks_hash:hash}

test('stick command keeps paired gaps and one stable inventory identity',()=>{
  const clean=sanitizePriceSticksCommand(base,4,'day')
  assert.deepEqual(clean.start_values,[12,null,13,14])
  const inventory=drawingInventory({interval:'day',chartCommands:[clean]})
  assert.equal(inventory.length,1);assert.equal(inventory[0].sticks_hash,hash)
  const rows=[1,2,3,4].map(time=>({time,open:10,high:12,low:9,close:11,volume:1}))
  const observed=sanitizeChartContext({state:'ready',symbol:'TEST.X',interval:'day',source_interval:'day',ui_interval:'day',
    adjust:'none',range_key:'custom',source_chart_session:'c'.repeat(32),candles:rows,drawings:inventory,
    visible_range:{available:true,index_from:0,index_to_exclusive:4}})
  assert.equal(observed.drawings[0].sticks_hash,hash)
  assert.equal(sanitizePriceSticksCommand(base,2,'week').interval,'day')
})

test('stick source rejects mismatched gaps, equal endpoints and wrong candle counts',()=>{
  const cases=[{...base,start_values:[12,null,13,14],end_values:[9,9,10,11]},
    {...base,end_values:[9,null,13,11]},
    {...base,start_values:[null,null,null,null],end_values:[null,null,null,null]},
    {...base,bar_count:3},{...base,start_source:{kind:'sma',period:1}}]
  for(const candidate of cases)assert.throws(()=>sanitizePriceSticksCommand(candidate,4,'day'))
  assert.throws(()=>sanitizePriceSticksCommand(base,3,'day'))
})

test('price-pane stick renderer draws independent vertical segments and preserves candles',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const snippet=html.slice(html.indexOf('function drawAgentPriceStickCommands('),html.indexOf('let pendingLiveDrawingPayload = null;'))
  const registered:any[]=[],created:any[]=[],removed:any[]=[],registry=new Map()
  const rows=[1,2,3,4].map(time=>({time}))
  const state:any={currentInterval:'day',currentCandles:rows,agentStickRegistry:registry,
    activeAgentStickIndicators:new Set(),registeredAgentStickIndicators:new Set(),
    window:{klinecharts:{registerIndicator:(indicator:any)=>registered.push(indicator)}},
    colorFor:()=> '#aabbcc',kchart:{createIndicator:(...args:any[])=>{created.push(args);return 'ok'},
      removeIndicator:(...args:any[])=>removed.push(args),applyNewData:()=>assert.fail('must not reset candles')}}
  const draw=runInNewContext(snippet+';drawAgentPriceStickCommands',state)
  draw([base],true)
  assert.equal(registered.length,1);assert.equal(created[0][2].id,'candle_pane')
  assert.equal(registry.get(id),hash)
  const calculated=registered[0].calc(rows.map(row=>({timestamp:row.time*1000})),created[0][0])
  assert.equal(calculated[1].start,undefined)
  const segments:any[]=[],ctx:any={beginPath:()=>segments.push(['begin']),moveTo:(x:number,y:number)=>segments.push(['move',x,y]),
    lineTo:(x:number,y:number)=>segments.push(['line',x,y]),stroke:()=>segments.push(['stroke'])}
  assert.equal(registered[0].draw({ctx,indicator:{result:calculated},visibleRange:{from:0,to:4},
    xAxis:{convertToPixel:(bar:number)=>bar*10},yAxis:{convertToPixel:(price:number)=>price*2}}),true)
  assert.deepEqual(segments,[['begin'],['move',0,24],['line',0,18],['move',20,26],['line',20,20],
    ['move',30,28],['line',30,22],['stroke']])
  assert.equal(ctx.strokeStyle,'#aabbcc')
  assert.equal(ctx.lineWidth,2)
  assert.equal(registered[0].figures.length,2)
  draw([],true)
  assert.equal(registry.size,0);assert.ok(removed.length>0)
})

test('bundled KLineCharts v9 accepts paired figure keys with custom draw override',()=>{
  const exports:any={},module={exports}
  runInNewContext(readFileSync(new URL('../view/vendor/klinecharts.min.js',import.meta.url),'utf8'),{exports,module})
  assert.ok(exports.getSupportedFigures().includes('line'))
  exports.registerIndicator({name:'ftvStickCompatibilityTest',shortName:'sticks',series:'price',
    calc:(dataList:any[])=>dataList.map(()=>({start:2,end:1})),
    figures:[{key:'start',title:'',type:'line'},{key:'end',title:'',type:'line'}],
    draw:()=>true})
  assert.ok(exports.getSupportedIndicators().includes('ftvStickCompatibilityTest'))
})
