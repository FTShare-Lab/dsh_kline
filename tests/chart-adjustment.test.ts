import {test} from 'node:test'
import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {readFileSync} from 'node:fs'
import {runInNewContext} from 'node:vm'
import {normalizeAdjustment} from '../src/chart-adjustment.ts'
import {TEST_PYTHON} from '../scripts/test-runtime.mjs'

test('Node/Python adjustment metadata canonicalization agrees and never guesses unknown values',()=>{
  const inputs:any[]=['none','forward','backward','qfq','hfq',' QFQ ','HFQ',null,'','null','raw','pre','post','unknown',true,1,{},[],'__proto__','constructor']
  const expected=['none','forward','backward','forward','backward','forward','backward',...Array(13).fill(null)]
  assert.deepEqual(inputs.map(normalizeAdjustment),expected)
  const child=spawnSync(TEST_PYTHON,['-c','import json,sys; from core.adjustment import normalize_adjustment; print(json.dumps([normalize_adjustment(v) for v in json.load(sys.stdin)]))'],{input:JSON.stringify(inputs),encoding:'utf8'})
  assert.equal(child.status,0,child.stderr);assert.deepEqual(JSON.parse(child.stdout),expected)
})

test('actual inline ingestion uses effective adjustment for new candles and preserves it for drawing-only input',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const start=html.indexOf('    if (!structured.local_render) {',html.indexOf('async function handleToolResult(')),end=html.indexOf('    const previousSymbol',start)
  const context:any={structured:{interval:'day',adjust:'none',chartCommands:[{type:'SET_CANDLES',rows:[{time:1}]}]},currentAdjust:'forward'}
  const code=html.slice(start,end)
  runInNewContext(code,context);assert.equal(context.currentAdjust,'none')
  context.structured={interval:'day',adjust:'backward',chartCommands:[]}
  runInNewContext(code,context);assert.equal(context.currentAdjust,'none')
  context.structured.chartCommands=[{type:'SET_CANDLES',rows:[{time:1}]}]
  delete context.structured.adjust
  runInNewContext(code,context);assert.equal(context.currentAdjust,'')
  assert.match(html,/currentAdjust = typeof fetched\.adjust === "string" \? fetched\.adjust : ""/)
  assert.match(html,/currentAdjust = typeof tab\.payload\?\.adjust === "string" \? tab\.payload\.adjust : ""/)
  const fetchedStart=html.indexOf('    sourceCandles = fetched.rows.slice();'),fetchedEnd=html.indexOf('    currentSymbol = fetched.symbol',fetchedStart)
  const fetchedContext:any={fetched:{rows:[{time:1}],interval:'day',adjust:'none'},currentAdjust:'forward',options:{}}
  runInNewContext(html.slice(fetchedStart,fetchedEnd),fetchedContext);assert.equal(fetchedContext.currentAdjust,'none')
  delete fetchedContext.fetched.adjust
  runInNewContext(html.slice(fetchedStart,fetchedEnd),fetchedContext);assert.equal(fetchedContext.currentAdjust,'')
})
