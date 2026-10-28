import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { runInNewContext } from 'node:vm'
import { ChartSources, sanitizeSourcePayload } from '../src/chart-sources.ts'
import { ChartContextBroker } from '../src/chart-context.ts'
import { ChartApplications } from '../src/chart-applications.ts'
import { createChartContextPublisher } from '../src/client/chart-context.ts'
import { drawingInventory, observationKey, sanitizeChartContext } from '../src/chart-observation.ts'
import { collectDrawingFeedback } from '../src/drawing-feedback.ts'
import { TEST_PYTHON } from '../scripts/test-runtime.mjs'
import { SOURCE_STATUS_REASONS, sourceStatus, sanitizeSourceStatus, sourceFailure } from '../src/chart-source-status.ts'
import { candleSequenceHash } from '../src/candle-sequence.ts'

test('public forward/backward and legacy aliases pass source metadata checks, but unknown/different adjustments fail',async()=>{
  for(const [value,alias] of [['forward','qfq'],['backward','hfq']]) {
    const f=await fixture()
    try {
      f.v.state={...f.v.state,adjust:value}
      const raw={...payload(),adjust:value}
      assert.equal(sanitizeSourcePayload({...raw,adjust:alias},f.v.state).adjust,value)
      const assessment=await f.sources.assess(f.v,raw)
      assert.notEqual(assessment.status.reason,'source_metadata_unknown')
      assert.ok(assessment.handoff)
      for(const bad of ['none',value==='forward'?'backward':'forward','unknown','',null])assert.throws(()=>sanitizeSourcePayload({...raw,adjust:bad},f.v.state),/source_payload_mismatch/)
      f.v.state.adjust='unknown'
      assert.equal((await f.sources.assess(f.v)).status.reason,'source_metadata_unknown')
    } finally {await f.close()}
  }
})

const parent='b'.repeat(32),viewId='v'.repeat(32),ref='r'.repeat(32)
const daily=[1,2,3,4].map(time=>({time,open:31,high:33,low:30,close:32,volume:1}))
const weekly=[{...daily[1],volume:2},{...daily[3],volume:2}]
const channel={type:'DRAW_AGENT_CHANNEL',id:'C',interval:'day',label:'日线对象',color:'info',show_midline:true,
  from:{time:1,price:30},to:{time:4,price:33},parallel:{time:2,price:33},
  upper:{from:{time:1,price:32},to:{time:4,price:35}},lower:{from:{time:1,price:30},to:{time:4,price:33}},
  width:2,signed_offset:2,slope_per_bar:1,direction:'ascending',geometry_basis:'candle_index_linear_price'}
function payload(interval='week',rows=weekly):any {
  return {symbol:'TEST.X',name:'测试',interval,interval_value:1,adjust:'none',range_key:'custom',
    data_meta:{source:'ftshare'},chartCommands:[{type:'SET_CANDLES',rows},{type:'SET_RANGE',start:rows[0].time,end:rows.at(-1)!.time},
      {type:'SET_INDICATOR_SERIES',name:'ma',pane:'candle',params:{periods:[5]},data:{ma5:{'2':31.5,'4':32}}},channel]}
}
function state(p=payload()):any {
  return sanitizeChartContext({state:'ready',symbol:p.symbol,name:p.name,interval:p.interval,interval_value:1,adjust:'none',
    source_interval:'day',ui_interval:p.interval,range_key:'custom',active_page:'chart',source_chart_session:parent,
    candles:p.chartCommands[0].rows,visible_range:{available:true,index_from:0,index_to_exclusive:p.chartCommands[0].rows.length},
    drawings:drawingInventory(p),indicators:['ma'],data_provenance:{provider:'ftshare',transformation:'local_aggregation',aggregation:{timezone:'Asia/Shanghai'}}})
}
async function fixture() {
  const runtime=await mkdtemp(join(tmpdir(),'kline-source-'))
  await mkdir(join(runtime,'sessions'))
  const original={ok:true,host_process_id:process.pid,session:parent,payload:payload('day',daily)}
  await writeFile(join(runtime,'sessions',parent+'.json'),JSON.stringify(original))
  const sources=new ChartSources(runtime)
  const v:any={ref,conversation:'A',view:viewId,revision:1,active:true,ambiguous:false,applyCapable:true,state:state()}
  return {runtime,sources,v,original,close:()=>rm(runtime,{recursive:true,force:true,maxRetries:5,retryDelay:50})}
}
function py(runtime:string,body:string):any {
  const script=`import asyncio,json,server,chart_service
from tools.chart_edits import ChartEdit
from unittest.mock import patch
with patch('server.fetch_candles',side_effect=AssertionError('no fetch')):
 ${body}
if chart_service._service:
 chart_service._service.httpd.shutdown()
 chart_service._service.httpd.server_close()
`
  const child=spawnSync(TEST_PYTHON,['-c',script],{encoding:'utf8',env:{...process.env,DSH_KLINE_RUNTIME_DIR:runtime,
    DSH_KLINE_HOST_PID:String(process.pid),DSH_KLINE_CHART_PORT:'0'}})
  assert.equal(child.status,0,child.stderr);return JSON.parse(child.stdout)
}
async function until(predicate:()=>boolean) {
  // The source handoff starts a separate Python process.  Five seconds is
  // insufficient on a contended CI worker when Node test files run in
  // parallel, and turns an otherwise successful handshake into a flake.
  const end=Date.now()+15000
  while(!predicate() && Date.now()<end)await new Promise(resolve=>setTimeout(resolve,10))
  assert.equal(predicate(),true,'publisher handshake did not complete')
}

test('source snapshots whitelist render fields and reject different candles, AI inventory, unknown commands and secrets',()=>{
  const raw=payload();raw.api_key='test-secret';raw.data_meta.source_url='test-secret';raw.chartCommands[2].params.password='test-secret'
  const clean=sanitizeSourcePayload(raw,state(raw))
  assert.ok(!JSON.stringify(clean).includes('test-secret'))
  assert.deepEqual(clean.chartCommands, payload().chartCommands)
  const changed=structuredClone(raw);changed.chartCommands[0].rows[0].volume=9
  assert.throws(()=>sanitizeSourcePayload(changed,state(raw)),/source_rows_mismatch/)
  const wrong=structuredClone(raw);wrong.chartCommands[3].parallel.price=34
  assert.throws(()=>sanitizeSourcePayload(wrong,state(raw)),/source_inventory_mismatch/)
  assert.throws(()=>sanitizeSourcePayload({...raw,chartCommands:[...raw.chartCommands,{type:'EXECUTE_SCRIPT'}]},state(raw)),/unsupported/)
})

test('browser-opened local chart bootstraps a confirmed source without Agent quota but never imports unverified AI',async()=>{
  const f=await fixture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
  try {
    const local={...payload('day',daily),local_render:true,
      chartCommands:payload('day',daily).chartCommands.filter(command=>command.type!=='DRAW_AGENT_CHANNEL')}
    const initial={...state(local),source_chart_session:null}
    f.v.state=initial
    assert.equal((await f.sources.assess(f.v)).status.reason,'source_missing')
    assert.equal((await f.sources.assess(f.v,{...local,local_render:false})).status.reason,'source_missing')
    await assert.rejects(f.sources.assess(f.v,{...payload('day',daily),local_render:true}),/source_inventory_mismatch/)
    const first=await broker.publish({conversation_id:'A',view_id:viewId,sequence:1,active:true,
      captured_at_ms:Date.now(),application_protocol:'guarded-view-v1',source_protocol:'browser-source-v1',
      state:initial,source_payload:local})
    assert.equal(first.source_status.reason,'source_handoff_pending')
    const token=first.source_handoff.chart_session
    const sealed=JSON.parse(await readFile(join(f.runtime,'sessions',token+'.json'),'utf8'))
    assert.equal(sealed.payload.drawing_parent_session,undefined)
    assert.equal(sealed.payload.chartCommands.some((command:any)=>command.type==='DRAW_AGENT_CHANNEL'),false)
    const second=await broker.publish({conversation_id:'A',view_id:viewId,sequence:2,active:true,
      captured_at_ms:Date.now(),application_protocol:'guarded-view-v1',source_protocol:'browser-source-v1',
      state:{...initial,source_chart_session:token},source_receipt:{chart_session:token,status:'bound'}})
    assert.equal(second.source_receipt.status,'confirmed')
    assert.equal(second.source_status.reason,'source_matches_view')
    const checked=py(f.runtime,`from tools.chart_functions import run_function; r=run_function('${second.context_ref}',${second.revision},'${token}','TEST.X','parallel_channel',{'start_time':'1','start_price':30,'end_time':'4','end_price':33,'parallel_time':'2','parallel_price':35}); p=server.prepare_guarded_chart_edit('${second.context_ref}',${second.revision},'${token}','TEST.X','bootstrap-channel',ChartEdit(kind='channel',action='create',result_ref=r['result_ref'],name='网页通道')); print(json.dumps({'result_usage':r['result_usage'],'chart_modified':r['chart_modified'],'operation_status':p['operation_status'],'object_id':p['object']['id']}))`)
    assert.equal(checked.result_usage,'guarded_drawing')
    assert.equal(checked.chart_modified,false)
    assert.equal(checked.operation_status,'prepared')
    assert.match(checked.object_id,/^channel_/)
  } finally {await f.close()}
})

test('offered source is immutable but unconfirmed; dirty, inactive, expired and foreign receipts never confirm it',async()=>{
  for(const change of ['rows','viewport','inactive','foreign','expired']) {
    const f=await fixture()
    try {
      const offer=await f.sources.offer(f.v,payload());assert.ok(offer)
      assert.equal((await f.sources.offer(f.v,payload())).chart_session,offer.chart_session)
      const snapshot=JSON.parse(await readFile(join(f.runtime,'sessions',offer.chart_session+'.json'),'utf8'))
      assert.equal(snapshot.payload.view_source_guard.protocol,'browser-source-v1')
      const before=await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8')
      f.v.state={...f.v.state,source_chart_session:offer.chart_session}
      if(change==='rows')f.v.state.candles=[{...weekly[0],volume:9},weekly[1]]
      if(change==='viewport')f.v.state.visible_range={available:false}
      if(change==='inactive')f.v.active=false
      if(change==='foreign')f.v.conversation='B'
      if(change==='expired')offer.expires_at_ms=Date.now()-1
      const ack=await f.sources.acknowledge(f.v,{chart_session:offer.chart_session,status:'bound'})
      assert.equal(ack.status,'rejected')
      assert.equal(await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8'),before)
    } finally {await f.close()}
  }
})

test('matching sources create no replacement; stale parents, hidden geometry changes, pending drawings and ambiguity fail closed',async()=>{
  const f=await fixture()
  try {
    assert.equal(await f.sources.offer({...f.v,state:state(payload('day',daily))},payload('day',daily)),undefined)
    assert.equal(await f.sources.offer({...f.v,ambiguous:true},payload()),undefined)
    const altered=payload();altered.chartCommands[3]={...channel,width:99}
    await assert.rejects(f.sources.offer(f.v,altered),/source_ai_changed/)
    const saved={...f.original,host_process_id:process.pid+1}
    await writeFile(join(f.runtime,'sessions',parent+'.json'),JSON.stringify(saved))
    await assert.rejects(f.sources.offer(f.v,payload()),/source_parent_unavailable/)
    await writeFile(join(f.runtime,'sessions',parent+'.json'),JSON.stringify(f.original))
    const directory=join(f.runtime,'edits',String(process.pid),ref)
    await mkdir(join(directory,'applications'),{recursive:true})
    await writeFile(join(directory,'pending.json'),JSON.stringify({candidate_chart_session:'c'.repeat(32)}))
    await writeFile(join(directory,'applications','c'.repeat(32)+'.json'),JSON.stringify({status:'outcome_unknown'}))
    assert.equal(await f.sources.offer(f.v,payload()),undefined)
    assert.equal((await f.sources.acknowledge({...f.v,ref:'s'.repeat(32)},{chart_session:'x'.repeat(32),status:'bound'})).status,'rejected')
  } finally {await f.close()}
})

test('returning to a larger daily window never checks the new viewport against shorter old source rows',async()=>{
  for(const interval of ['week','day']) {
    const f=await fixture()
    try {
      const shorter={...f.original,payload:payload(interval,weekly)}
      await writeFile(join(f.runtime,'sessions',parent+'.json'),JSON.stringify(shorter))
      const current=payload('day',daily)
      f.v.state=state(current)
      assert.equal(f.v.state.visible_range.index_to_exclusive,4)
      const offered=await f.sources.offer(f.v,current)
      assert.ok(offered)
      const sealed=JSON.parse(await readFile(join(f.runtime,'sessions',offered.chart_session+'.json'),'utf8'))
      assert.deepEqual(sealed.payload.chartCommands[0].rows,daily)
      assert.deepEqual(sealed.payload.chartCommands.at(-1),channel)
      assert.deepEqual(JSON.parse(await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8')),shorter)
    } finally {await f.close()}
  }
})

test('daily sequence remains a hidden immutable object on weekly view and restores on unchanged daily rows',async()=>{
  const f=await fixture()
  try {
    const line={type:'DRAW_AGENT_SERIES_LINE',id:'series_'+'a'.repeat(24),interval:'day',label:'日线条件线',color:'info',
      bar_count:daily.length,row_hash:candleSequenceHash(daily),source:{kind:'close'},condition:null,
      values:[null,32,null,32],series_hash:'b'.repeat(64)}
    const sticks={type:'DRAW_AGENT_PRICE_STICKS',id:'sticks_'+'a'.repeat(24),interval:'day',label:'日线柱线',color:'warning',
      bar_count:daily.length,row_hash:candleSequenceHash(daily),start_source:{kind:'high'},end_source:{kind:'low'},
      condition:null,start_values:[33,null,33,null],end_values:[30,null,30,null],sticks_hash:'c'.repeat(64)}
    const day={...payload('day',daily),chartCommands:[...payload('day',daily).chartCommands,line,sticks]}
    const week={...payload(),chartCommands:[...payload().chartCommands,line,sticks]}
    await writeFile(join(f.runtime,'sessions',parent+'.json'),JSON.stringify({...f.original,payload:day}))
    f.v.state=state(week)
    const offered=await f.sources.assess(f.v,week)
    assert.equal(offered.status.reason,'source_handoff_pending')
    const weeklyToken=offered.handoff.chart_session
    assert.equal((await f.sources.acknowledge({...f.v,state:{...f.v.state,source_chart_session:weeklyToken}},
      {chart_session:weeklyToken,status:'bound'})).status,'confirmed')
    const returnedState={...state(day),source_chart_session:weeklyToken}
    const returned=await f.sources.assess({...f.v,state:returnedState},day)
    assert.equal(returned.status.reason,'source_handoff_pending')
    const sealed=JSON.parse(await readFile(join(f.runtime,'sessions',returned.handoff.chart_session+'.json'),'utf8'))
    assert.equal(sealed.payload.chartCommands.at(-2).row_hash,line.row_hash)
    assert.equal(sealed.payload.chartCommands.at(-1).sticks_hash,sticks.sticks_hash)
    const changed=structuredClone(day);changed.chartCommands[0].rows[1].volume=9
    const changedState={...state(changed),source_chart_session:weeklyToken}
    await assert.rejects(f.sources.assess({...f.v,state:changedState},changed),/source_sequence_rows_mismatch/)
  } finally {await f.close()}
})

test('range-only viewport change retains sequence source without weakening candle checks',async()=>{
  const f=await fixture()
  try {
    const line={type:'DRAW_AGENT_SERIES_LINE',id:'series_'+'a'.repeat(24),interval:'day',label:'条件线',color:'info',
      bar_count:daily.length,row_hash:candleSequenceHash(daily),source:{kind:'close'},condition:null,
      values:[null,32,null,32],series_hash:'b'.repeat(64)}
    const day={...payload('day',daily),chartCommands:[...payload('day',daily).chartCommands,line]}
    await writeFile(join(f.runtime,'sessions',parent+'.json'),JSON.stringify({...f.original,payload:day}))
    const short={...day,range_key:'30d',chartCommands:[day.chartCommands[0],
      {type:'SET_RANGE',start:daily[2].time,end:daily[3].time},...day.chartCommands.slice(2)]}
    const shortState={...state(short),range_key:'30d'}
    f.v.state=shortState
    assert.equal(sanitizeSourcePayload(short,shortState).chartCommands.at(-1).id,line.id)
    assert.equal((await f.sources.assess(f.v,short)).status.reason,'source_matches_view')
    const changed=structuredClone(short)
    changed.chartCommands[0].rows[2].close=31.5
    assert.throws(()=>sanitizeSourcePayload(changed,shortState),/source_rows_mismatch/)
    const changedState={...state(changed),range_key:'30d'}
    await assert.rejects(f.sources.assess({...f.v,state:changedState},changed),/source_sequence_rows_mismatch/)
  } finally {await f.close()}
})

test('source diagnostics are identical allowlists across Node/Python, strip secrets and never grant authority',()=>{
  const cases=[...Object.keys(SOURCE_STATUS_REASONS).map(reason=>({schema_version:1,reason,edit_authorized:true,url:'test-secret',phase:'forged'})),
    null,{schema_version:true,reason:'source_matches_view'},{schema_version:1,reason:'__proto__'}, {schema_version:1,reason:['source_matches_view']}]
  const child=spawnSync(TEST_PYTHON,['-c','import json,sys;from tools.chart_source_status import sanitize_source_status;print(json.dumps([sanitize_source_status(x) for x in json.loads(sys.argv[1])]))',JSON.stringify(cases)],{encoding:'utf8',env:process.env})
  assert.equal(child.status,0,child.stderr)
  const cleaned=cases.map(sanitizeSourceStatus)
  assert.deepEqual(cleaned,JSON.parse(child.stdout));assert.ok(!JSON.stringify(cleaned).includes('test-secret'))
  assert.ok(cleaned.every(s=>s.edit_authorized===false))
  assert.equal(sourceFailure(Error('source_parent_unavailable')).reason,'source_owner_mismatch')
  assert.equal(sourceFailure(Error('private-token-path')).reason,'source_handoff_unavailable')
})

test('read-only source assessment distinguishes limits, metadata and unknown/pending drawings without creating snapshots',async()=>{
  const f=await fixture()
  try {
    const before=await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8')
    for(const [patch,reason] of [[{active:false},'view_inactive'],[{ambiguous:true},'ambiguous_views'],[{applyCapable:false},'client_unsupported'],
      [{state:{...f.v.state,state:'loading'}},'chart_not_ready'],[{state:{...f.v.state,source_chart_session:null}},'source_missing'],
      [{state:{...f.v.state,adjust:''}},'source_metadata_unknown'],[{state:{...f.v.state,candles:Array(4001).fill(daily[0])}},'source_limit_exceeded']] as any[]) {
      assert.equal((await f.sources.assess({...f.v,...patch})).status.reason,reason)
    }
    assert.equal((await f.sources.assess(f.v)).status.reason,'source_snapshot_mismatch')
    assert.equal((await f.sources.assess({...f.v,state:state(payload('day',daily))})).status.phase,'aligned')
    const dir=join(f.runtime,'edits',String(process.pid),ref)
    await mkdir(join(dir,'applications'),{recursive:true})
    await writeFile(join(dir,'pending.json'),JSON.stringify({candidate_chart_session:'c'.repeat(32)}))
    assert.equal((await f.sources.assess(f.v,payload())).status.reason,'drawing_outcome_unknown')
    for(const status of ['queued','delivered','outcome_unknown','invalid']) {
      await writeFile(join(dir,'applications','c'.repeat(32)+'.json'),JSON.stringify({status}))
      const r=await f.sources.assess(f.v,payload());assert.equal(r.handoff,undefined)
      assert.equal(r.status.reason,['queued','delivered'].includes(status)?'drawing_pending':'drawing_outcome_unknown')
    }
    assert.equal(await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8'),before)
  } finally {await f.close()}
})

test('broker publishes specific diagnostics to real Python context without revising data or trusting browser-forged status',async()=>{
  const f=await fixture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
  try {
    const raw:any={view_id:viewId,conversation_id:'A',sequence:1,active:true,captured_at_ms:Date.now(),state:state(),
      application_protocol:'guarded-view-v1',source_protocol:'browser-source-v1',source_payload:{...payload(),chartCommands:[{type:'BAD'}]},
      source_status:{schema_version:1,reason:'source_matches_view'}}
    const rejected=await broker.publish(raw)
    assert.equal(rejected.source_status.reason,'source_payload_invalid')
    const heartbeat=await broker.publish({...raw,sequence:2,state:null,source_payload:undefined})
    assert.equal(heartbeat.revision,rejected.revision);assert.deepEqual(heartbeat.source_status,rejected.source_status)
    const read=py(f.runtime,`r=asyncio.run(server.get_chart_context('${rejected.context_ref}',candle_scope='loaded'));print(json.dumps(r.structuredContent))`)
    assert.deepEqual(read.source_status,rejected.source_status)
    assert.match(broker.prompt((()=>{const agent={session:{id:'A'}};return {agent,scope:agent}})()),/source_payload_invalid/)
    assert.equal(read.source_snapshot_alignment,'not_verified');assert.equal(read.live_view_editable,false)
    const retry=await broker.publish({...raw,sequence:3,source_payload:payload()})
    assert.equal(retry.source_status.phase,'checking');assert.equal(retry.revision,rejected.revision)
    assert.ok(retry.source_handoff)
  } finally {await f.close()}
})

test('explicit source retry only rechecks current state, while unchanged rejected handoffs do not loop',async()=>{
  for(const fail of ['invalid_payload','expired_offer']) {
    const f=await fixture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
    let current=state(),publisher:any,bad=true,offers=0,binds=0,confirms=0,failSeen=false
    const statuses:any[]=[],sent:any[]=[]
    let releaseFinalStatus:()=>void=()=>{}
    const finalStatusGate=new Promise<void>(resolve=>{releaseFinalStatus=resolve})
    try {
      publisher=createChartContextPublisher({conversationId:'A',viewId,isActive:()=>true,capture:()=>current,
        captureSource:()=>bad && fail==='invalid_payload'?{...payload(),chartCommands:[{type:'BAD'}]}:payload(),
        apply:()=>assert.fail('recheck must not execute a drawing'),onSourceStatus:s=>statuses.push(s),
        bindSource:token=>{binds++;current={...current,source_chart_session:token}},confirmSource:(_,confirmed)=>{if(confirmed)confirms++},
        transport:async raw=>{sent.push(raw);const response=await broker.publish(raw)
          // Hold the observation after confirmation: the callback alone does
          // not mean the following source-status publication has settled.
          if(confirms===1 && raw.active!==false)await finalStatusGate
          if(response.source_handoff) {offers++;if(bad && fail==='expired_offer')return {...response,source_handoff:{...response.source_handoff,expires_at_ms:Date.now()-1}}}
          if(response.source_status.phase==='blocked')failSeen=true
          return response}})
      await until(()=>failSeen);await new Promise(resolve=>setTimeout(resolve,30))
      publisher.notify();await new Promise(resolve=>setTimeout(resolve,30))
      assert.equal(binds,0);assert.equal(confirms,0);assert.equal(offers,fail==='expired_offer'?1:0)
      bad=false;publisher.retrySource();await until(()=>confirms===1)
      assert.equal(binds,1);assert.deepEqual(current.candles,weekly)
      assert.equal(statuses.at(-1).phase,'checking')
      releaseFinalStatus();await until(()=>statuses.at(-1)?.phase==='aligned')
      assert.ok(statuses.some(s=>s.phase==='checking'));assert.equal(statuses.at(-1).phase,'aligned')
      assert.ok(sent.every(raw=>!raw.edit && !raw.candidate_chart_session && !raw.request_id))
    } finally {releaseFinalStatus();publisher?.dispose();await new Promise(resolve=>setTimeout(resolve,50));await f.close()}
  }
})

test('actual bilingual source status UI uses text only and its retry cannot fetch quotes or resend drawings',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const elements:any=Object.fromEntries(['sourceHandoffStatus','sourceHandoffText','sourceHandoffRetry'].map(id=>[id,{dataset:{},hidden:true,textContent:''}]))
  let retries=0
  const context:any={viewLanguage:'en',window:{__DSH_KLINE_RETRY_SOURCE__:()=>retries++},document:{getElementById:(id:string)=>elements[id]},
    fetch:()=>assert.fail('status UI must not fetch')}
  const render=runInNewContext(html.slice(html.indexOf('let liveSourceStatus ='),html.indexOf('function captureLiveChartSource()'))+';renderLiveSourceStatus',context)
  for(const lang of ['en','zh']) {
    context.viewLanguage=lang
    for(const reason of Object.keys(SOURCE_STATUS_REASONS)) {
      const status=sourceStatus(reason as any);render({...status,message:'<script>test-secret</script>'})
      assert.ok(elements.sourceHandoffText.textContent.length>0)
      assert.ok(!elements.sourceHandoffText.textContent.includes('test-secret'))
      assert.equal(elements.sourceHandoffRetry.hidden,status.next_action!=='retry_observation')
      assert.equal(elements.sourceHandoffStatus.hidden,reason==='chart_not_ready' || reason==='source_matches_view')
    }
  }
  render(sourceStatus('drawing_outcome_unknown'));assert.equal(elements.sourceHandoffRetry.hidden,true)
  render(sourceStatus('source_payload_invalid'));elements.sourceHandoffRetry.onclick()
  assert.equal(retries,1);assert.equal(elements.sourceHandoffStatus.dataset.phase,'checking')
  assert.equal(elements.sourceHandoffRetry.hidden,true)
  context.window.__DSH_KLINE_DISPOSED__=true;const before=elements.sourceHandoffText.textContent
  render(sourceStatus('source_matches_view'));assert.equal(elements.sourceHandoffText.textContent,before)
})

test('a delayed aligned response for a prior chart never labels the changed chart aligned',async()=>{
  let current=state(),publisher:any
  const calls:any[]=[],statuses:any[]=[],releases:Array<(value:any)=>void>=[]
  try {
    publisher=createChartContextPublisher({conversationId:'A',viewId,isActive:()=>true,capture:()=>current,
      onSourceStatus:s=>statuses.push(s),transport:raw=>{
        calls.push(raw)
        if(raw.active===false)return Promise.resolve({ok:true})
        return new Promise(resolve=>releases.push(resolve))
      }})
    await until(()=>releases.length===1)
    current={...current,candles:[{...weekly[0],volume:99},weekly[1]]}
    releases[0]({ok:true,source_status:sourceStatus('source_matches_view')})
    await until(()=>releases.length===2)
    assert.equal(statuses.at(-1).phase,'checking');assert.equal(statuses.some(s=>s.phase==='aligned'),false)
    assert.deepEqual(calls[1].state.candles,current.candles)
    releases[1]({ok:true,source_status:sourceStatus('source_matches_view')})
    await until(()=>statuses.at(-1)?.phase==='aligned')
    assert.equal(statuses.filter(s=>s.phase==='aligned').length,1)
  } finally {publisher?.dispose();await new Promise(resolve=>setTimeout(resolve,30))}
})

test('publisher never binds a changed/disposed view or confirms removed UI after a delayed source acknowledgment',async()=>{
  for(const scenario of ['changed','disposed_offer','disposed_ack']) {
    const f=await fixture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
    let current=state(),publisher:any,bound=0,confirmed=0,finished=false,handled=false
    try {
      publisher=createChartContextPublisher({conversationId:'A',viewId,isActive:()=>true,capture:()=>current,
        apply:()=>assert.fail('source handshake must never invoke a drawing application'),
        captureSource:()=>payload(),bindSource:token=>{bound++;current={...current,source_chart_session:token}},
        confirmSource:()=>{confirmed++},transport:async raw=>{
          const response=await broker.publish(raw)
          if(response.source_handoff && !handled) {
            handled=true
            if(scenario==='changed')current={...current,candles:[{...weekly[0],volume:9},weekly[1]]}
            if(scenario==='disposed_offer')publisher.dispose()
          }
          if(response.source_receipt && scenario==='disposed_ack')publisher.dispose()
          if(response.source_receipt || raw.active===false)finished=true
          return response
        }})
      await until(()=>finished)
      await new Promise(resolve=>setTimeout(resolve,20))
      assert.equal(bound,scenario==='disposed_ack'?1:0,scenario)
      assert.equal(confirmed,scenario==='changed'?1:0,scenario)
    } finally {publisher?.dispose();await new Promise(resolve=>setTimeout(resolve,50));await f.close()}
  }
})

test('real browser source handoff → Python guarded weekly drawing → receipt and recovery preserve hidden daily geometry and actual indicators',async()=>{
  const f=await fixture(), saved:any[]=[],overlays=new Map<string,any>(),responses:any[]=[],mutations:any[]=[]
  let publisher:any
  try {
    const current={...payload(),local_render:true,_live_chart_session:parent,_live_application_pending:false}
    const context:any={lastChartPayload:current,currentCandles:weekly,currentSymbol:'TEST.X',currentName:'测试',
      activeAgentSeriesIndicators:new Set(),agentSeriesRegistry:new Map(),registeredAgentSeriesIndicators:new Set(),
      activeAgentBandIndicators:new Set(),agentBandRegistry:new Map(),registeredAgentBandIndicators:new Set(),
      activeAgentStickIndicators:new Set(),agentStickRegistry:new Map(),registeredAgentStickIndicators:new Set(),
      currentInterval:'week',currentAdjust:'none',currentRangeKey:'custom',sourceCandleInterval:'day',activeSecurityTab:'chart',
      exchangeTimezone:'Asia/Shanghai',openingSymbol:false,userDrawings:[],customLevels:[],analysisLevels:[],currentSelection:null,
      maVisible:true,vwapVisible:false,volVisible:false,macdVisible:false,kdjVisible:false,bollVisible:false,rsiVisible:false,atrVisible:false,
      volumeUnit:'wan',chartDataStatus:'delayed',rememberWorkspaceTab:()=>{},rememberAnalysisCommands:()=>{},
      window:{__DSH_KLINE_SAVE_VIEW__:(p:any)=>saved.push(p)},
      kchart:{removeOverlay:({groupId}:any)=>{mutations.push(groupId);for(const [id,o] of overlays)if(o.groupId===groupId)overlays.delete(id)},
        createOverlay:(o:any)=>{overlays.set(o.id,o);return o.id},getOverlayById:(id:string)=>overlays.get(id)??null,
        getVisibleRange:()=>({from:0,to:2}),applyNewData:()=>assert.fail('handoff/edit must not reset candles')}}
    const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
    const render=html.slice(html.indexOf('function drawHorizontalLineCommands('),html.indexOf('function isSupportResistanceLevel('))
    const collect=html.slice(html.indexOf('function captureChartContext('),html.indexOf('function refreshMirrorAxes('))
    const api=runInNewContext(render+collect+';({capture:()=>captureChartContext(lastChartPayload._live_chart_session),captureSource:captureLiveChartSource,bindSource:bindLiveChartSource,confirmSource:confirmLiveChartSource,apply:applyLiveDrawingCommands,confirm:confirmLiveDrawingApplication})',context)
    context.window.__DSH_KLINE_DRAWING_FEEDBACK__=(p:any,b:any[],phase:string)=>collectDrawingFeedback(p,api.capture(),context.kchart,b,phase)
    const initial=api.capture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
    let lostSourceAck=false
    publisher=createChartContextPublisher({conversationId:'A',viewId,isActive:()=>true,...api,
      transport:async(raw:any)=>{const response=await broker.publish(raw)
        if(response.source_receipt?.status==='confirmed' && !lostSourceAck) {lostSourceAck=true;throw Error('test lost acknowledgment')}
        responses.push(response);return response}})
    await until(()=>responses.some(r=>r.source_receipt?.status==='confirmed'))
    const bound=api.capture().source_chart_session,latest=responses.find(r=>r.source_receipt?.status==='confirmed')
    assert.notEqual(bound,parent);assert.equal(mutations.length,0);assert.equal(saved.length,1)
    assert.equal(lostSourceAck,true);assert.equal(responses.filter(r=>r.source_handoff).length,1)
    assert.equal(observationKey({...api.capture(),source_chart_session:parent}),observationKey(initial))
    const source=JSON.parse(await readFile(join(f.runtime,'sessions',bound+'.json'),'utf8'))
    assert.deepEqual(source.payload.chartCommands,payload().chartCommands)
    const read=py(f.runtime,`r=asyncio.run(server.get_chart_context('${latest.context_ref}',candle_scope='loaded'));print(json.dumps(r.structuredContent))`)
    assert.equal(read.source_chart_session,bound);assert.equal(read.interval,'week')
    const rejected=py(f.runtime,`r=asyncio.run(server.prepare_chart_edit('${latest.context_ref}',${read.revision},'${bound}','TEST.X','wrong-period',ChartEdit(kind='channel',action='update',object_id='C',color='orange')));print(json.dumps(r.structuredContent))`)
    assert.equal(rejected.error,'drawing_interval_mismatch')
    const prepared=py(f.runtime,`r=asyncio.run(server.prepare_chart_edit('${latest.context_ref}',${read.revision},'${bound}','TEST.X','weekly-line',ChartEdit(kind='horizontal_line',action='create',price=31,name='周线观察',color='green')));print(json.dumps(r.structuredContent))`)
    assert.equal(prepared.ok,true,JSON.stringify(prepared))
    const queued=py(f.runtime,`r=asyncio.run(server.apply_chart_edit('${latest.context_ref}','${prepared.chart_session}'));print(json.dumps(r.structuredContent))`)
    assert.equal(queued.apply_status,'queued');publisher.notify()
    await until(()=>responses.some(r=>r.receipt?.apply_status==='applied'))
    assert.equal(overlays.get(prepared.object.id).extendData.label,'周线观察');assert.ok(!overlays.has('C'))
    assert.equal(context.currentCandles,weekly);assert.equal(context.maVisible,true)
    assert.deepEqual(context.lastChartPayload.chartCommands.find((c:any)=>c.type==='DRAW_AGENT_CHANNEL'),channel)
    assert.deepEqual(context.lastChartPayload.chartCommands[2],current.chartCommands[2])
    const recovered=await new ChartApplications(f.runtime).recover('A')
    assert.equal(recovered.payload.interval,'week');assert.ok(recovered.recovery_source_sessions.includes(parent))
    assert.deepEqual(recovered.payload.chartCommands.find((c:any)=>c.type==='SET_INDICATOR_SERIES'),current.chartCommands[2])
    assert.equal(recovered.payload.view_source_guard,undefined)
    assert.deepEqual(JSON.parse(await readFile(join(f.runtime,'sessions',parent+'.json'),'utf8')),f.original)
  } finally {publisher?.dispose();await new Promise(resolve=>setTimeout(resolve,50));await f.close()}
})
