import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sanitizePriceSeriesCommand } from '../src/price-series.ts'
import { drawingInventory, sanitizeChartContext } from '../src/chart-observation.ts'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const id='series_'+'a'.repeat(24)
const hash='b'.repeat(64)
const base={type:'DRAW_AGENT_SERIES_LINE',id,interval:'day',label:'条件线',color:'info',bar_count:4,
  source:{kind:'sma',period:3},condition:{left:{kind:'close'},op:'gt',right:{constant:10}},
  values:[null,null,11,null],series_hash:hash}

test('series command preserves null gaps and has one inventory identity',()=>{
  const clean=sanitizePriceSeriesCommand(base,4,'day')
  assert.deepEqual(clean.values,[null,null,11,null])
  const inventory=drawingInventory({interval:'day',chartCommands:[clean]})
  assert.equal(inventory.length,1)
  assert.equal(inventory[0].id,id)
  assert.equal(inventory[0].series_hash,hash)
  const rows=[1,2,3,4].map(time=>({time,open:10,high:12,low:9,close:11,volume:1}))
  const context=sanitizeChartContext({state:'ready',symbol:'TEST.X',interval:'day',source_interval:'day',ui_interval:'day',
    adjust:'none',range_key:'custom',source_chart_session:'c'.repeat(32),candles:rows,drawings:inventory,
    visible_range:{available:true,index_from:0,index_to_exclusive:4}})
  assert.equal(context.drawings[0].bar_count,4)
  assert.equal(context.drawings[0].series_hash,hash)
})

test('series command rejects wrong bars, period, condition, values and empty lines',()=>{
  const cases=[
    [{...base,bar_count:3},4,'day'],
    [{...base,values:[null,null,null,null]},4,'day'],
    [{...base,values:[null,0,11,null]},4,'day'],
    [{...base,source:{kind:'sma',period:201}},4,'day'],
    [{...base,condition:{left:{kind:'close'},op:'eq',right:{constant:10}}},4,'day'],
    [{...base,condition:{left:{kind:'close'},op:'gt',right:{constant:10,source:{kind:'low'}}}},4,'day'],
    [base,4001,'day'],
  ] as const
  for(const [candidate,bars,interval] of cases)assert.throws(()=>sanitizePriceSeriesCommand(candidate,bars,interval))
  assert.equal(sanitizePriceSeriesCommand(base,2,'week').interval,'day')
})

test('selected EMA uses the same bounded price-line source contract',()=>{
  const ema={...base,source:{kind:'ema',period:17},condition:null,
    values:[null,10,11,12]}
  assert.deepEqual(sanitizePriceSeriesCommand(ema,4,'day').source,{kind:'ema',period:17})
  assert.throws(()=>sanitizePriceSeriesCommand({...ema,source:{kind:'ema',period:201}},4,'day'))
  assert.throws(()=>sanitizePriceSeriesCommand({...ema,source:{kind:'ema',period:17,code:'x'}},4,'day'))
})

test('inline renderer registers one candle-pane indicator without resetting candles or crossing null gaps',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const snippet=html.slice(html.indexOf('function drawAgentSeriesLineCommands('),html.indexOf('let pendingLiveDrawingPayload = null;'))
  const registered:any[]=[],created:any[]=[],removed:any[]=[], registry=new Map()
  const bars=[1,2,3,4].map(time=>({time}))
  const state:any={currentInterval:'day',currentCandles:bars,agentSeriesRegistry:registry,
    activeAgentSeriesIndicators:new Set(),registeredAgentSeriesIndicators:new Set(),
    window:{klinecharts:{registerIndicator:(indicator:any)=>registered.push(indicator)}},
    colorFor:()=> 'blue',kchart:{createIndicator:(...args:any[])=>{created.push(args);return 'ok'},
      removeIndicator:(...args:any[])=>removed.push(args),applyNewData:()=>assert.fail('must not reset history')}}
  const draw=runInNewContext(snippet+';drawAgentSeriesLineCommands',state)
  draw([base],true)
  assert.equal(registered.length,1)
  assert.equal(created.length,1)
  assert.equal(created[0][2].id,'candle_pane')
  assert.equal(registry.get(id),hash)
  const values=registered[0].calc(bars.map(row=>({timestamp:row.time*1000})),created[0][0])
  assert.deepEqual(Array.from(values,(value:any)=>value.value??null),[null,null,11,null])
  const attrs=registered[0].figures[0].attrs
  assert.equal(attrs({coordinate:{current:{x:1,value:11},next:{x:2}}}),null)
  draw([],true)
  assert.equal(registry.size,0)
  assert.ok(removed.length>0)
})
