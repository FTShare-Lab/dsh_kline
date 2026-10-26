import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { runInNewContext } from 'node:vm'
import { ChartContextBroker } from '../src/chart-context.ts'
import { ChartApplications } from '../src/chart-applications.ts'
import { createChartApplyController } from '../src/client/chart-apply.ts'
import { createChartContextPublisher } from '../src/client/chart-context.ts'
import { sanitizeChartContext, observationKey, drawingInventory } from '../src/chart-observation.ts'
import { mergeHorizontalLineSnapshot } from '../src/client/horizontal-lines.ts'
import { collectDrawingFeedback } from '../src/drawing-feedback.ts'
import { TEST_PYTHON } from '../scripts/test-runtime.mjs'
import { createServer } from 'node:http'
import { sourceStatus } from '../src/chart-source-status.ts'
import { fibonacciOverlayPoints } from '../src/fibonacci.ts'
import { polylineOverlayPoints } from '../src/labeled-polyline.ts'

const original='b'.repeat(32), view='v'.repeat(32)
function base():any {
  return {state:'ready',symbol:'TEST.X',name:'测试',interval:'day',interval_value:1,adjust:'none',source_interval:'day',ui_interval:'day',
    data_provenance:{provider:'unknown',transformation:'none'},
    display_volume_unit:'wan',range_key:'custom',active_page:'chart',source_chart_session:original,
    candles:[1,2,3,4].map(time=>({time,open:31,high:33,low:30,close:32,volume:1})),
    visible_range:{available:true,index_from:1,index_to_exclusive:3},indicators:['vol'],data_status:'delayed',selection:null,
    drawings:[{id:'H',kind:'horizontal_line',origin:'ai',name:'H',color:'info',interval:'day',price:31}]}
}
function command(state=base()):any {
  return {candidate_chart_session:'c'.repeat(32),lease_id:'l'.repeat(32),context_ref:'a'.repeat(32),conversation_id:'A',view_id:view,
    expected_revision:1,expires_at_ms:Date.now()+30000,base_state:state,
    payload:{symbol:'TEST.X',interval:'day',chartCommands:[{type:'DRAW_HORIZONTAL_LINE',id:'H',label:'完整观察线',color:'success',price:30}]}}
}
function publication(sequence:number,state:any,receipt?:any):any {
  return {conversation_id:'A',view_id:view,sequence,active:true,application_protocol:'guarded-view-v1',captured_at_ms:Date.now(),state,...(receipt ? {receipt} : {})}
}
function py(runtime:string,script:string):any {
  const child=spawnSync(TEST_PYTHON,['-c',`import asyncio,json,server,chart_service
from tools.chart_edits import ChartEdit
${script}
if chart_service._service:
 chart_service._service.httpd.shutdown()
 chart_service._service.httpd.server_close()
`],{encoding:'utf8',env:{...process.env,DSH_KLINE_RUNTIME_DIR:runtime,DSH_KLINE_HOST_PID:String(process.pid),DSH_KLINE_CHART_PORT:'0'}})
  assert.equal(child.status,0,child.stderr);return JSON.parse(child.stdout)
}
function prepare(runtime:string,ref:string,revision:number,source=original,request='R',extra="kind='horizontal_line',action='create',price=32,name='完整A'") {
  const result=py(runtime,`r=asyncio.run(server.prepare_chart_edit('${ref}',${revision},'${source}','TEST.X','${request}',ChartEdit(${extra}))); print(json.dumps(r.structuredContent))`)
  assert.equal(result.ok,true,JSON.stringify(result));return result
}
function queue(runtime:string,ref:string,token:string) {
  return py(runtime,`r=asyncio.run(server.apply_chart_edit('${ref}','${token}')); print(json.dumps(r.structuredContent))`)
}
function status(runtime:string,ref:string,token:string) {
  return py(runtime,`r=asyncio.run(server.get_chart_edit_status('${ref}','${token}')); print(json.dumps(r.structuredContent))`)
}
async function fixture() {
  const runtime=await mkdtemp(join(tmpdir(),'kline-apply-'))
  const broker=new ChartContextBroker(join(runtime,'views',String(process.pid)),()=>Date.now(),runtime)
  const state=base(), payload={symbol:'TEST.X',interval:'day',interval_value:1,adjust:'none',range_key:'custom',count:4,
    chartCommands:[{type:'SET_CANDLES',rows:state.candles},{type:'DRAW_HORIZONTAL_LINE',id:'H',label:'H',color:'info',price:31}]}
  await mkdir(join(runtime,'sessions'))
  await writeFile(join(runtime,'sessions',original+'.json'),JSON.stringify({ok:true,session:original,host_process_id:process.pid,payload}))
  const observed=await broker.publish(publication(1,state))
  return {runtime,broker,state,payload,ref:observed.context_ref,revision:observed.revision,
    cleanup:()=>rm(runtime,{recursive:true,force:true})}
}
async function until(predicate:()=>boolean) {
  const end=Date.now()+5000
  while(!predicate() && Date.now()<end)await new Promise(resolve=>setTimeout(resolve,5))
  assert.equal(predicate(),true,'expected transport transition did not complete')
}

test('a hung publication has a bounded failure and a late valid delivery cannot reach the drawing controller',async()=>{
  const c=command(),statuses:any[]=[],calls:any[]=[],signals:any[]=[]
  let release:(value:any)=>void=()=>{},applied=0
  const publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:base,isActive:()=>true,
    publicationTimeoutMs:30,onSourceStatus:s=>statuses.push(s),apply:()=>{applied++},
    transport:(body,signal)=>{calls.push(body);signals.push(signal)
      if(calls.length===1)return new Promise(resolve=>{release=resolve})
      return Promise.resolve({ok:true,source_status:sourceStatus('source_matches_view')})}})
  try {
    await until(()=>statuses.at(-1)?.reason==='context_transport_unavailable')
    assert.equal(signals[0].aborted,true);assert.equal(applied,0)
    release({ok:true,context_ref:c.context_ref,revision:1,application:c,source_status:sourceStatus('source_matches_view')})
    await new Promise(resolve=>setTimeout(resolve,15))
    assert.equal(applied,0);assert.equal(statuses.some(s=>s.phase==='aligned'),false)
    publisher.notify();await until(()=>statuses.at(-1)?.phase==='aligned')
    assert.equal(calls.length,2);assert.ok(calls[1].state)
  } finally {publisher.dispose();await new Promise(resolve=>setTimeout(resolve,20))}
})

test('disposing a hung transport aborts it and sends bounded inactive reporting without touching removed UI',async()=>{
  const calls:any[]=[],statuses:any[]=[],signals:any[]=[];let release:(value:any)=>void=()=>{},applied=0
  const publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:base,isActive:()=>true,
    publicationTimeoutMs:500,onSourceStatus:s=>statuses.push(s),apply:()=>{applied++},
    transport:(body,signal)=>{calls.push(body);signals.push(signal)
      return body.active?new Promise(resolve=>{release=resolve}):Promise.resolve({ok:true})}})
  await until(()=>calls.length===1)
  publisher.dispose();await until(()=>calls.length===2)
  assert.equal(signals[0].aborted,true);assert.equal(calls[1].active,false)
  release({ok:true,context_ref:command().context_ref,revision:1,application:command()})
  await new Promise(resolve=>setTimeout(resolve,20))
  assert.equal(applied,0);assert.equal(statuses.length,0)
})

test('timed-out application acknowledgment retries only the same receipt, never the local drawing',async()=>{
  const c=command(),calls:any[]=[],statuses:any[]=[];let current=base(),applied=0,confirmed=0,late:(value:any)=>void=()=>{}
  const ack={candidate_chart_session:c.candidate_chart_session,lease_id:c.lease_id,apply_status:'applied',confirmed_chart_session:c.candidate_chart_session}
  const publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:()=>current,isActive:()=>true,
    publicationTimeoutMs:30,onSourceStatus:s=>statuses.push(s),
    apply:(p,token)=>{applied++;current={...current,source_chart_session:token,drawings:drawingInventory(p)}},confirm:()=>{confirmed++},
    transport:body=>{calls.push(body)
      if(calls.length===1)return Promise.resolve({ok:true,context_ref:c.context_ref,revision:1,application:c})
      if(calls.length===2)return new Promise(resolve=>{late=resolve})
      return Promise.resolve({ok:true,receipt:body.receipt?ack:undefined,source_status:sourceStatus('source_matches_view')})}})
  try {
    await until(()=>statuses.at(-1)?.reason==='context_transport_unavailable')
    assert.equal(applied,1);assert.equal(confirmed,0)
    publisher.notify();await until(()=>confirmed===1)
    assert.equal(applied,1);assert.deepEqual(calls[1].receipt,calls[2].receipt)
    late({ok:true,receipt:ack});await new Promise(resolve=>setTimeout(resolve,15))
    assert.equal(applied,1);assert.equal(confirmed,1)
  } finally {publisher.dispose();await new Promise(resolve=>setTimeout(resolve,20))}
})

test('real HTTP socket loss after real broker delivery stays unconfirmed and subsequent posts do not resend it',async()=>{
  const f=await fixture(),broker=new ChartContextBroker(join(f.runtime,'views',String(process.pid)),()=>Date.now(),f.runtime)
  const nativeFetch=globalThis.fetch,published:any[]=[],statuses:any[]=[],bodies:any[]=[]
  let publisher:any,applied=0,lost=0
  const server=createServer(async(req,res)=>{
    try {
      const chunks=[];for await(const chunk of req)chunks.push(chunk)
      const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));bodies.push(body)
      const response=await broker.publish(body);published.push(response)
      if(response.application) {lost++;res.destroy();return}
      res.setHeader('Content-Type','application/json');res.end(JSON.stringify(response))
    } catch {res.statusCode=500;res.end('{"ok":false}')}
  })
  try {
    await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
    const address=server.address() as any
    globalThis.fetch=((input:any,init:any)=>{assert.equal(input,'/dsh-kline/context');return nativeFetch(`http://127.0.0.1:${address.port}/dsh-kline/context`,init)}) as any
    publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:()=>f.state,isActive:()=>true,
      // Socket-loss behavior is under test here, not the separate timeout path.
      // Mac CI may spend tens of seconds in the synchronous Python fixture.
      publicationTimeoutMs:90000,onSourceStatus:s=>statuses.push(s),apply:()=>{applied++}})
    await until(()=>statuses.at(-1)?.reason==='not_checked')
    // Seed the immutable queue record directly: this test exercises real HTTP
    // delivery/loss, while Python prepare/queue is covered by the separate
    // end-to-end test. Slow subprocess startup must not consume the browser's
    // deliberately bounded 8-second publication timeout here.
    const observed=published[0],token='c'.repeat(32),requestId='socket-loss-test'
    const guard={protocol:'prepared-only-v1',context_ref:observed.context_ref,conversation_id:'A',view_id:view,
      expected_revision:observed.revision,request_id:requestId}
    const candidate={...f.payload,drawing_guard:guard}
    const edits=join(f.runtime,'edits',String(process.pid),observed.context_ref)
    await mkdir(join(edits,'applications'),{recursive:true})
    await writeFile(join(f.runtime,'sessions',token+'.json'),JSON.stringify({ok:true,session:token,
      host_process_id:process.pid,payload:candidate}))
    await writeFile(join(edits,'applications',token+'.json'),JSON.stringify({host_process_id:process.pid,
      context_ref:observed.context_ref,candidate_chart_session:token,conversation_id:'A',view_id:view,
      expected_revision:observed.revision,request_id:requestId,status:'queued',created_at_ms:Date.now(),
      expires_at_ms:Date.now()+30_000,base_state:sanitizeChartContext(f.state)}))
    await writeFile(join(edits,'pending.json'),JSON.stringify({candidate_chart_session:token}))
    publisher.notify();await until(()=>statuses.at(-1)?.reason==='context_transport_unavailable')
    assert.equal(lost,1);assert.equal(applied,0)
    const record=async()=>JSON.parse(await readFile(join(edits,'applications',token+'.json'),'utf8'))
    assert.equal((await record()).status,'delivered')
    const count=published.length;publisher.notify();await until(()=>published.length>count)
    assert.equal(published.at(-1).application,undefined);assert.equal(lost,1);assert.equal(applied,0)
    assert.equal((await record()).status,'delivered')
    assert.ok(bodies.every(b=>!b.receipt));assert.deepEqual(f.state,base())
  } finally {
    publisher?.dispose();await new Promise(resolve=>setTimeout(resolve,50));globalThis.fetch=nativeFetch
    server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))
    await f.cleanup()
  }
})

test('local guard rejects dirty, inactive, expired, foreign or mismatched deliveries before touching a chart',()=>{
  for(const mode of ['dirty','inactive','expired','conversation','view','revision','reference']) {
    const state=base(), c=command(), publication={context_ref:c.context_ref,revision:1};let calls=0
    if(mode==='dirty')state.range_key='changed'
    if(mode==='expired')c.expires_at_ms=1
    if(mode==='conversation')c.conversation_id='B'
    if(mode==='view')c.view_id='w'.repeat(32)
    if(mode==='revision')publication.revision=2
    if(mode==='reference')publication.context_ref='x'.repeat(32)
    const controller=createChartApplyController({conversationId:'A',viewId:view,capture:()=>state,isActive:()=>mode!=='inactive',apply:()=>{calls++}})
    const receipt=controller.consume(c,publication)
    assert.equal(receipt.status,'rejected',mode);assert.equal(calls,0,mode)
  }
})

test('unconfirmed payloads cannot enter recovery cache and ordinary snapshots do not inherit stale live provenance',()=>{
  const generator=readFileSync(new URL('../scripts/generate-client-view.mjs',import.meta.url),'utf8')
  const snippet=generator.slice(generator.indexOf('  dependencies.saveView = next => {'),generator.indexOf('  dependencies.storage = {'))
  const writes:any[]=[], dependencies:any={chartSession:original}
  runInNewContext(snippet,{dependencies,controller:{signal:{aborted:false}},viewKey:'test-view',
    globalThis:{localStorage:{setItem:(key:string,value:string)=>writes.push(JSON.parse(value))}}})
  dependencies.saveView({_live_chart_session:'c'.repeat(32),_live_application_pending:true,symbol:'TEST.X'})
  assert.equal(writes.length,0)
  dependencies.saveView({_live_chart_session:'c'.repeat(32),_live_application_pending:false,symbol:'TEST.X'})
  assert.equal(writes.length,1);assert.equal(writes[0].session,original)
  const merged=mergeHorizontalLineSnapshot({drawing_only:true,drawing_parent_session:original,symbol:'TEST.X',interval:'day',chartCommands:[]},
    {session:original,payload:{...writes[0].payload,interval:'day',chartCommands:[]}})
  assert.equal(merged._live_chart_session,undefined);assert.equal(merged._live_application_pending,undefined)
})

test('one local delivery applies once, confirms once and does not claim pixels',()=>{
  let state=base(), calls=0, confirms=0;const c=command()
  const controller=createChartApplyController({conversationId:'A',viewId:view,capture:()=>state,isActive:()=>true,
    apply:(payload,token)=>{calls++;state={...state,source_chart_session:token,drawings:drawingInventory(payload)}},confirm:()=>{confirms++}})
  const receipt=controller.consume(c,{context_ref:c.context_ref,revision:1})
  assert.equal(receipt.status,'applied');assert.deepEqual(controller.consume(c,{context_ref:c.context_ref,revision:2}),receipt)
  assert.equal(calls,1)
  const ack={...receipt,apply_status:'applied',confirmed_chart_session:c.candidate_chart_session}
  controller.confirm({...ack,lease_id:'wrong'});controller.confirm(ack);controller.confirm(ack)
  assert.equal(confirms,1)
})

test('rollback success and rollback uncertainty are distinct, and silent state mismatch is not success',()=>{
  for(const mode of ['rolled_back','unknown','silent']) {
    const c=command(), controller=createChartApplyController({conversationId:'A',viewId:view,capture:base,isActive:()=>true,
      apply:()=>{if(mode!=='silent')throw Object.assign(Error('renderer failed'),{rolledBack:mode==='rolled_back'})}})
    assert.equal(controller.consume(c,{context_ref:c.context_ref,revision:1}).status,mode==='rolled_back' ? 'failed' : 'outcome_unknown')
  }
})

test('real Node → Python prepare/queue → inline view drawing-only apply → receipt → next edit preserves source and viewport',async()=>{
  const f=await fixture()
  try {
    const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8'), overlays=new Map<string,any>(), saved:any[]=[]
    overlays.set('manual:T',{groupId:'manual'})
    const context:any={lastChartPayload:f.payload,currentCandles:f.state.candles,currentSymbol:'TEST.X',currentName:'测试',
      activeAgentSeriesIndicators:new Set(),agentSeriesRegistry:new Map(),registeredAgentSeriesIndicators:new Set(),
      activeAgentBandIndicators:new Set(),agentBandRegistry:new Map(),registeredAgentBandIndicators:new Set(),
      activeAgentStickIndicators:new Set(),agentStickRegistry:new Map(),registeredAgentStickIndicators:new Set(),
      currentInterval:'day',currentAdjust:'none',currentRangeKey:'custom',sourceCandleInterval:'day',activeSecurityTab:'chart',
      openingSymbol:false,userDrawings:[],customLevels:[],analysisLevels:[],currentSelection:null,maVisible:false,vwapVisible:false,
      volVisible:true,macdVisible:false,kdjVisible:false,bollVisible:false,rsiVisible:false,atrVisible:false,volumeUnit:'wan',chartDataStatus:'delayed',
      kchart:{removeOverlay:({groupId}:any)=>{for(const [id,o] of overlays)if(o.groupId===groupId)overlays.delete(id)},
        createOverlay:(o:any)=>{overlays.set(o.id,o);return o.id},getOverlayById:(id:string)=>overlays.get(id) ?? null,
        getVisibleRange:()=>({from:1,to:3}),applyNewData:()=>assert.fail('must preserve candles')},
      rememberWorkspaceTab:()=>{},rememberAnalysisCommands:()=>{},window:{__DSH_KLINE_SAVE_VIEW__:(p:any)=>saved.push(p)}}
    const render=html.slice(html.indexOf('function drawHorizontalLineCommands('),html.indexOf('function isSupportResistanceLevel('))
    const collect=html.slice(html.indexOf('function captureChartContext('),html.indexOf('function refreshMirrorAxes('))
    const api=runInNewContext(render+collect+';({apply:applyLiveDrawingCommands,confirm:confirmLiveDrawingApplication,capture:()=>captureChartContext(lastChartPayload?._live_chart_session || "'+original+'")})',context)
    context.window.__DSH_KLINE_DRAWING_FEEDBACK__=(p:any,before:any[],phase:string)=>collectDrawingFeedback(p,api.capture(),context.kchart,before,phase)
    assert.equal(observationKey(api.capture()),observationKey(f.state))
    const controller=createChartApplyController({conversationId:'A',viewId:view,capture:api.capture,isActive:()=>true,apply:api.apply,confirm:api.confirm})
    const first=prepare(f.runtime,f.ref,f.revision)
    assert.equal(queue(f.runtime,f.ref,first.chart_session).apply_status,'queued')
    assert.equal(queue(f.runtime,f.ref,first.chart_session).apply_status,'queued')
    const delivered=await f.broker.publish(publication(2,null))
    assert.ok(delivered.application);assert.equal(status(f.runtime,f.ref,first.chart_session).apply_status,'delivered')
    const receipt=controller.consume(delivered.application,delivered)
    assert.equal(receipt.status,'applied');assert.equal(saved.length,0)
    assert.equal(receipt.drawing_feedback.report_status,'reported')
    assert.ok(receipt.drawing_feedback.items.every((i:any)=>i.status==='created'))
    const ack=await f.broker.publish(publication(3,api.capture(),receipt))
    controller.confirm(ack.receipt)
    assert.equal(ack.receipt.apply_status,'applied');assert.equal(ack.receipt.render_verified,false)
    assert.equal(saved.length,1);assert.equal(overlays.get(first.object.id).extendData.label,'完整A')
    assert.ok(overlays.has('manual:T'));assert.equal(context.currentCandles,f.state.candles)
    assert.deepEqual(context.kchart.getVisibleRange(),{from:1,to:3});assert.equal(context.volVisible,true)
    const second=prepare(f.runtime,f.ref,ack.revision,first.chart_session,'R2',`kind='horizontal_line',action='update',object_id='${first.object.id}',price=30.5`)
    assert.equal(queue(f.runtime,f.ref,second.chart_session).apply_status,'queued')
    const next=await f.broker.publish(publication(4,null))
    const secondReceipt=controller.consume(next.application,next)
    const final=await f.broker.publish(publication(5,api.capture(),secondReceipt));controller.confirm(final.receipt)
    assert.equal(final.receipt.apply_status,'applied');assert.ok(final.revision>ack.revision)
    assert.equal(overlays.get(first.object.id).points[0].value,30.5);assert.equal(overlays.get('H').points[0].value,31)
    assert.equal(saved.length,2);assert.equal(status(f.runtime,f.ref,second.chart_session).confirmation_scope,'view_state_only')
    let revision=final.revision, source=second.chart_session, sequence=5
    for(const kind of ['trend_line','channel','rectangle','fibonacci_retracement','labeled_polyline']) {
      const parameters=kind==='rectangle' ? "start_time='1',end_time='4',lower_price=30,upper_price=32"
        : "start_time='1',start_price=30,end_time='4',end_price=32"+(kind==='channel' ? ",parallel_time='2',parallel_price=32" : '')
      let id='', originalPoints:any[]=[]
      for(const action of ['create','update','delete']) {
        const fields=action==='create' ? parameters : `object_id='${id}'`+(action==='update'
          ? kind==='rectangle' ? ',show_fill=False' : kind==='channel' ? ',show_midline=False'
            : kind==='labeled_polyline' ? ",point_label='C',point_time='4',point_price=32.5" : ',end_price=32.5' : '')
        const prepared=kind==='fibonacci_retracement' && action!=='delete'
          ? py(f.runtime,`from tools.chart_functions import ChartFunctionParameters
c=asyncio.run(server.run_chart_function('${f.ref}',${revision},'${source}','TEST.X','fibonacci_retracement',ChartFunctionParameters(start_time='1',start_price=30,end_time='4',end_price=${action==='create'?32:32.5},ratios=[0,.618,1]))).structuredContent
r=asyncio.run(server.prepare_chart_edit('${f.ref}',${revision},'${source}','TEST.X','${kind}-${action}',ChartEdit(kind='${kind}',action='${action}',result_ref=c['result_ref']${action==='update'?`,object_id='${id}'`:''}))); print(json.dumps(r.structuredContent))`)
          : kind==='labeled_polyline' && action==='create'
            ? py(f.runtime,`from tools.chart_functions import ChartFunctionParameters
c=asyncio.run(server.run_chart_function('${f.ref}',${revision},'${source}','TEST.X','labeled_polyline',ChartFunctionParameters(points=[dict(label='A',time='1',price=30),dict(label='B',time='2',price=32),dict(label='C',time='3',price=31)]))).structuredContent
r=asyncio.run(server.prepare_chart_edit('${f.ref}',${revision},'${source}','TEST.X','${kind}-${action}',ChartEdit(kind='${kind}',action='create',result_ref=c['result_ref'],name='ABC样板')));print(json.dumps(r.structuredContent))`)
          : prepare(f.runtime,f.ref,revision,source,kind+'-'+action,`kind='${kind}',action='${action}',${fields}`)
        assert.equal(prepared.ok,true,JSON.stringify(prepared))
        if(kind==='labeled_polyline') {
          if(action==='create')originalPoints=prepared.object.points
          if(action==='update') {
            assert.deepEqual(prepared.object.points.slice(0,2),originalPoints.slice(0,2))
            assert.deepEqual(prepared.change.point_changes.map((p:any)=>p.label),['C'])
            assert.equal(prepared.change.other_ai_drawings_unchanged,true)
          }
        }
        id=prepared.object.id;assert.equal(queue(f.runtime,f.ref,prepared.chart_session).apply_status,'queued')
        const delivery=await f.broker.publish(publication(++sequence,null))
        const localReceipt=controller.consume(delivery.application,delivery)
        assert.equal(localReceipt.status,'applied',kind+' '+action)
        const acknowledgment=await f.broker.publish(publication(++sequence,api.capture(),localReceipt));controller.confirm(acknowledgment.receipt)
        assert.equal(acknowledgment.receipt.apply_status,'applied');assert.equal(overlays.has(id),action!=='delete')
        assert.equal(acknowledgment.receipt.drawing_feedback.items.find((i:any)=>i.id===id).status,action==='delete' ? 'removed' : 'created')
        revision=acknowledgment.revision;source=prepared.chart_session
        if(kind==='fibonacci_retracement' && action==='update') {
          const recovery=await new ChartApplications(f.runtime).recover('A')
          const fib=recovery.payload.chartCommands.find((c:any)=>c.id===id)
          assert.equal(fib.type,'DRAW_AGENT_FIBONACCI');assert.equal(fib.ratios.length,3)
          assert.deepEqual(fibonacciOverlayPoints(fib),Array.from(overlays.get(id).points,(p:any)=>({timestamp:p.timestamp,value:p.value})))
        }
        if(kind==='labeled_polyline' && action==='update') {
          const recovery=await new ChartApplications(f.runtime).recover('A')
          const path=recovery.payload.chartCommands.find((c:any)=>c.id===id)
          assert.equal(path.type,'DRAW_AGENT_POLYLINE');assert.equal(path.points[2].label,'C')
          assert.deepEqual(polylineOverlayPoints(path),Array.from(overlays.get(id).points,(p:any)=>({timestamp:p.timestamp,value:p.value})))
        }
      }
    }
    assert.equal(saved.length,17);assert.equal(context.currentCandles,f.state.candles)
    assert.equal(overlays.get('H').points[0].value,31);assert.equal(overlays.get(first.object.id).points[0].value,30.5)
    assert.ok(overlays.has('manual:T'))
    const live=collectDrawingFeedback(context.lastChartPayload,api.capture(),context.kchart)
    const current=await f.broker.publish({...publication(++sequence,null),drawing_feedback:live})
    assert.equal(current.revision,revision)
    const read=py(f.runtime,`r=asyncio.run(server.get_chart_context('${f.ref}')); print(json.dumps(r.structuredContent))`)
    assert.equal(read.drawing_feedback.phase,'current');assert.equal(read.drawing_feedback.report_status,'reported')
    assert.equal(read.drawing_feedback.items.length,2);assert.equal(read.drawing_feedback.pixel_verified,false)
    const recovery=await new ChartApplications(f.runtime).recover('A')
    assert.equal(recovery.session,source);assert.equal(recovery.recovery_scope,'confirmed_historical_chart')
    assert.equal(recovery.payload.drawing_guard,undefined);assert.equal(recovery.payload._live_application_pending,false)
    assert.ok(recovery.recovery_source_sessions.includes(original));assert.equal(recovery.recovery_source_sessions.length,17)
    assert.equal(drawingInventory(recovery.payload).length,2)
    assert.ok(!JSON.stringify(recovery).includes('lease_id'));assert.ok(!JSON.stringify(recovery).includes('base_state'))
    await assert.rejects(new ChartApplications(f.runtime).recover('another-conversation'))
    const recoveryProof=join(f.runtime,'edits',String(process.pid),f.ref,'applications',source+'.json')
    const validProof=JSON.parse(await readFile(recoveryProof,'utf8'))
    for(const corruption of [{status:'delivered'},{status:'outcome_unknown'},{host_process_id:process.pid+1},{conversation_id:'foreign'}]) {
      await writeFile(recoveryProof,JSON.stringify({...validProof,...corruption}))
      await assert.rejects(new ChartApplications(f.runtime).recover('A'))
    }
    await writeFile(recoveryProof,JSON.stringify(validProof))
    const originalSnapshot=JSON.parse(await readFile(join(f.runtime,'sessions',original+'.json'),'utf8'))
    assert.deepEqual(originalSnapshot.payload,f.payload)
  } finally {await f.cleanup()}
})

test('inline drawing failure restores prior AI state, and a failed restore stays explicitly uncertain',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const render=html.slice(html.indexOf('function drawHorizontalLineCommands('),html.indexOf('function isSupportResistanceLevel('))
  for(const mode of ['throw','silent','rollback_failed']) {
    const overlays=new Map<string,any>();overlays.set('manual:T',{groupId:'manual'})
    const previous={symbol:'TEST.X',interval:'day',chartCommands:[{type:'SET_CANDLES',rows:base().candles},
      {type:'DRAW_HORIZONTAL_LINE',id:'H',label:'H',color:'info',price:31}]}
    const context:any={lastChartPayload:previous,currentCandles:base().candles,currentSymbol:'TEST.X',currentInterval:'day',openingSymbol:false,
      activeAgentSeriesIndicators:new Set(),agentSeriesRegistry:new Map(),registeredAgentSeriesIndicators:new Set(),
      activeAgentBandIndicators:new Set(),agentBandRegistry:new Map(),registeredAgentBandIndicators:new Set(),
      activeAgentStickIndicators:new Set(),agentStickRegistry:new Map(),registeredAgentStickIndicators:new Set(),
      rememberAnalysisCommands:()=>{},kchart:{removeOverlay:({groupId}:any)=>{for(const [id,o] of overlays)if(o.groupId===groupId)overlays.delete(id)},
        createOverlay:(o:any)=>{
          if(mode==='rollback_failed' || o.extendData.label==='fail') {
            if(mode==='silent')return null
            throw Error('renderer unavailable')
          }
          overlays.set(o.id,o);return o.id
        }}}
    const apply=runInNewContext(render+'; applyLiveDrawingCommands',context)
    assert.throws(()=>apply({symbol:'TEST.X',chartCommands:[{type:'DRAW_HORIZONTAL_LINE',id:'H',label:'fail',price:32}]},'c'.repeat(32)),
      (error:any)=>error.rolledBack===(mode!=='rollback_failed'))
    assert.equal(context.lastChartPayload,previous);assert.ok(overlays.has('manual:T'))
    if(mode!=='rollback_failed')assert.equal(overlays.get('H').points[0].value,31)
  }
})

test('delivery is not resent after a lost reply; expiration becomes unknown, not applied',async()=>{
  const f=await fixture()
  try {
    const prepared=prepare(f.runtime,f.ref,1);queue(f.runtime,f.ref,prepared.chart_session)
    const delivered=await f.broker.publish(publication(2,null));assert.ok(delivered.application)
    const retry=await f.broker.publish(publication(3,null));assert.equal(retry.application,undefined)
    assert.equal(queue(f.runtime,f.ref,prepared.chart_session).apply_status,'delivered')
    const applications=new ChartApplications(f.runtime,()=>Date.now()+31000)
    await applications.dispatch({ref:f.ref,view,conversation:'A',revision:1,active:true,ambiguous:false,state:sanitizeChartContext(f.state)})
    assert.equal(status(f.runtime,f.ref,prepared.chart_session).apply_status,'outcome_unknown')
  } finally {await f.cleanup()}
})

test('a changed observation rejects a queued candidate, while a changed local state rejects a dispatched one',async()=>{
  for(const changedBeforeDispatch of [true,false]) {
    const f=await fixture()
    try {
      const prepared=prepare(f.runtime,f.ref,1);queue(f.runtime,f.ref,prepared.chart_session)
      const local={...f.state,range_key:'changed'}
      const response=await f.broker.publish(publication(2,changedBeforeDispatch ? local : null))
      if(changedBeforeDispatch) assert.equal(response.application,undefined)
      else {
        const controller=createChartApplyController({conversationId:'A',viewId:view,capture:()=>local,isActive:()=>true,apply:()=>assert.fail('dirty view must not apply')})
        const receipt=controller.consume(response.application,response)
        await f.broker.publish(publication(3,local,receipt))
      }
      assert.equal(status(f.runtime,f.ref,prepared.chart_session).apply_status,'rejected')
    } finally {await f.cleanup()}
  }
})

test('old protocol and multiple active views reject delivery instead of picking another chart',async()=>{
  for(const mode of ['old_protocol','multiple_views']) {
    const f=await fixture()
    try {
      const prepared=prepare(f.runtime,f.ref,1);queue(f.runtime,f.ref,prepared.chart_session)
      if(mode==='multiple_views')await f.broker.publish({...publication(1,f.state),view_id:'w'.repeat(32)})
      const response=await f.broker.publish({...publication(2,null),...(mode==='old_protocol' ? {application_protocol:undefined} : {})})
      assert.equal(response.application,undefined)
      assert.equal(status(f.runtime,f.ref,prepared.chart_session).apply_status,'rejected')
    } finally {await f.cleanup()}
  }
})

test('disposing a publisher cancels an in-flight delivery without touching removed DOM or inventing a receipt',async()=>{
  let unblock:(value:any)=>void=()=>{}, calls=0, applied=0
  const first=new Promise(resolve=>{unblock=resolve}), c=command(), bodies:any[]=[]
  const publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:base,isActive:()=>true,apply:()=>{applied++},
    transport:async body=>{bodies.push(body);calls++;if(calls===1)return await first;return {ok:true}}})
  await new Promise(resolve=>setImmediate(resolve));publisher.dispose()
  unblock({ok:true,context_ref:c.context_ref,revision:1,application:c});await new Promise(resolve=>setImmediate(resolve))
  assert.equal(applied,0);assert.equal(bodies[1].active,false)
  // The canceled request never supplied a usable lease. Do not claim a
  // rejection receipt for an unseen delivery; the server retains uncertainty.
  assert.equal(bodies[1].receipt,undefined)
})

test('forged or mismatching applied receipts cannot confirm a source for the next mutation',async()=>{
  const f=await fixture()
  try {
    const prepared=prepare(f.runtime,f.ref,1);queue(f.runtime,f.ref,prepared.chart_session)
    const delivered=await f.broker.publish(publication(2,null)), c=delivered.application
    await assert.rejects(f.broker.publish(publication(3,f.state,{candidate_chart_session:c.candidate_chart_session,lease_id:'x'.repeat(32),status:'applied'})))
    const ack=await f.broker.publish(publication(4,f.state,{candidate_chart_session:c.candidate_chart_session,lease_id:c.lease_id,status:'applied'}))
    assert.equal(ack.receipt.apply_status,'outcome_unknown')
    assert.equal(status(f.runtime,f.ref,prepared.chart_session).apply_status,'outcome_unknown')
  } finally {await f.cleanup()}
})

test('a completed rollback advances its consumed revision once, allowing a fresh guarded request',async()=>{
  const f=await fixture()
  try {
    const prepared=prepare(f.runtime,f.ref,1);queue(f.runtime,f.ref,prepared.chart_session)
    const delivered=await f.broker.publish(publication(2,null)), c=delivered.application
    const controller=createChartApplyController({conversationId:'A',viewId:view,capture:()=>f.state,isActive:()=>true,
      apply:()=>{throw Object.assign(Error('failed'),{rolledBack:true})}})
    const receipt=controller.consume(c,delivered)
    const first=await f.broker.publish(publication(3,f.state,receipt))
    assert.equal(first.receipt.apply_status,'failed');assert.ok(first.revision>1)
    const duplicate=await f.broker.publish(publication(4,null,receipt))
    assert.equal(duplicate.revision,first.revision)
    const fresh=prepare(f.runtime,f.ref,first.revision,original,'retry-after-rollback')
    assert.equal(queue(f.runtime,f.ref,fresh.chart_session).apply_status,'queued')
  } finally {await f.cleanup()}
})

test('publisher retries an acknowledgment without repeating the local mutation',async()=>{
  let current=base(), applied=0, posts=0, unblock:()=>void=()=>{}
  const pause=new Promise<void>(resolve=>{unblock=resolve}), c=command()
  const publisher=createChartContextPublisher({conversationId:'A',viewId:view,capture:()=>current,isActive:()=>true,
    apply:(payload,token)=>{applied++;current={...current,source_chart_session:token,drawings:drawingInventory(payload)}},
    transport:async body=>{
      posts++
      if(posts===1)return {ok:true,context_ref:c.context_ref,revision:1,application:c}
      if(posts===2){await pause;throw Error('ack reply lost')}
      if(posts>3)return {ok:true}
      assert.equal(body.receipt.status,'applied');return {ok:true,context_ref:c.context_ref,revision:2,
        receipt:{...body.receipt,apply_status:'applied',confirmed_chart_session:c.candidate_chart_session}}
    }})
  try {
    await new Promise(resolve=>setImmediate(resolve));assert.equal(applied,1)
    unblock();await new Promise(resolve=>setImmediate(resolve));publisher.notify();await new Promise(resolve=>setImmediate(resolve))
    assert.equal(applied,1);assert.equal(posts,3)
  } finally {publisher.dispose();await new Promise(resolve=>setImmediate(resolve))}
})
