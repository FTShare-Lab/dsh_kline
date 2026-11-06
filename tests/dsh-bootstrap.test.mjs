import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PassThrough } from 'node:stream'
import { EventEmitter } from 'node:events'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdtempSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn } from 'node:child_process'
import { serve } from '../scripts/dsh-bootstrap.mjs'

function fixture(options = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'dsh-bootstrap-test-'))
  const input = new PassThrough(), output = new PassThrough(), error = new PassThrough()
  const replies = [], children = []
  output.on('data', chunk => replies.push(...String(chunk).trim().split('\n').map(JSON.parse)))
  const spawnServer = (_command, _args, opts) => {
    assert.equal(opts.env.DSH_KLINE_DEFER_BOOTSTRAP, '0')
    const child = Object.assign(new EventEmitter(), { stdin:new PassThrough(), stdout:new PassThrough(), stderr:new PassThrough(),
      sent:[], exitCode:null, signalCode:null,
      kill() { this.exitCode = 1; this.emit('exit', 1); return true } })
    child.stdin.on('data', chunk => child.sent.push(...String(chunk).trim().split('\n').map(JSON.parse)))
    children.push(child)
    return child
  }
  const server = serve({ input, output, error, args:['fake-server'],
    env:{ DSH_KLINE_CACHE_DIR:directory, DSH_KLINE_HOST_PID:String(process.pid) },
    retryDelayMs:5, maxRetryDelayMs:10, spawnServer, ...options })
  const send = message => input.write(JSON.stringify({jsonrpc:'2.0', ...message})+'\n')
  const initialize = () => send({id:1,method:'initialize',params:{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'test',version:'1'}}})
  const ready = (child = children.at(-1)) => child.stdout.write(JSON.stringify({jsonrpc:'2.0',id:'dsh-kline-bootstrap-initialize',result:{capabilities:{}}})+'\n')
  return {children,replies,send,initialize,ready,directory, close() { server.shutdown(); rmSync(directory,{recursive:true,force:true}) } }
}

test('DSH completes discovery before Python and keeps its complete catalog after readiness', () => {
  const f = fixture()
  try {
    f.initialize()
    assert.equal(f.replies[0].result.serverInfo.name,'dsh_kline')
    f.send({id:2,method:'tools/list'})
    const tools = f.replies.at(-1).result.tools
    for (const name of ['analyze_kline','prepare_chart_edit','apply_chart_edit','list_ta_functions']) assert.ok(tools.some(t=>t.name===name))
    f.send({id:3,method:'tools/call',params:{name:'analyze_kline',arguments:{symbol:'TEST'}}})
    assert.equal(f.children[0].sent.length,1)
    f.ready()
    assert.equal(f.children[0].sent.filter(m=>m.id===3).length,1)
    f.send({id:4,method:'tools/list'})
    assert.deepEqual(f.replies.at(-1).result.tools,tools)
    assert.ok(!f.replies.some(m=>m.method==='notifications/tools/list_changed'))
  } finally { f.close() }
})

test('expired or cancelled preparation calls cannot execute after readiness', async () => {
  const f = fixture({preparationWaitMs:5})
  try {
    f.initialize()
    f.send({id:2,method:'tools/call',params:{name:'apply_chart_edit',arguments:{}}})
    f.send({id:3,method:'tools/call',params:{name:'analyze_kline',arguments:{}}})
    f.send({method:'notifications/cancelled',params:{requestId:3}})
    await delay(20)
    const response=f.replies.find(m=>m.id===2)
    assert.equal(response.result.structuredContent.operation_dispatched,false)
    f.ready()
    assert.ok(!f.children[0].sent.some(m=>m.id===2 || m.id===3))
  } finally { f.close() }
})

test('backend restart preserves MCP and never replays an operation with an unknown result', async () => {
  const f=fixture()
  try {
    f.initialize(); f.ready()
    f.send({id:2,method:'tools/call',params:{name:'apply_chart_edit',arguments:{}}})
    const original=f.children[0]
    original.kill()
    const response=f.replies.find(m=>m.id===2).result.structuredContent
    assert.equal(response.operation_dispatched,true)
    assert.equal(response.outcome_unknown,true)
    await delay(20)
    assert.equal(f.children.length,2)
    f.ready()
    assert.ok(!f.children[1].sent.some(m=>m.id===2))
    f.send({id:3,method:'tools/call',params:{name:'list_ta_functions',arguments:{limit:1}}})
    assert.equal(f.children[1].sent.at(-1).id,3)
    f.children[1].stdout.write(JSON.stringify({jsonrpc:'2.0',id:3,result:{content:[]}})+'\n')
    assert.deepEqual(f.replies.at(-1),{jsonrpc:'2.0',id:3,result:{content:[]}})
  } finally { f.close() }
})

test('repeated startup exits retain discovery and persist stderr without polluting MCP', async () => {
  const f=fixture()
  try {
    f.initialize()
    f.children[0].stderr.write('simulated registration PermissionError\n')
    f.children[0].stdout.write('not a protocol frame\nnull\n[]\n{}\n')
    f.children[0].kill()
    await delay(20)
    f.send({id:2,method:'tools/list'})
    assert.ok(f.replies.at(-1).result.tools.some(t=>t.name==='analyze_kline'))
    const log=readFileSync(join(f.directory,'logs',`backend-${process.pid}.log`),'utf8')
    assert.match(log,/PermissionError/)
    assert.match(log,/MCP connection retained/)
    f.send({id:3,method:'tools/call',params:{name:'dsh_kline_runtime_status'}})
    assert.equal(f.replies.at(-1).result.structuredContent.phase,'recovering')
  } finally { f.close() }
})

test('host disconnect cancels pending calls and backend recovery', async () => {
  const f=fixture()
  f.initialize(); f.children[0].kill()
  f.close()
  await delay(20)
  assert.equal(f.children.length,1)
})


test('host shutdown terminates an in-progress installer descendant', async () => {
  const directory=mkdtempSync(join(tmpdir(),'dsh-bootstrap-tree-'))
  const started=join(directory,'started'), leaked=join(directory,'installer-finished-after-shutdown')
  const grandchild=`setTimeout(()=>require('node:fs').writeFileSync(${JSON.stringify(leaked)},'leaked'),3000)`
  const script=`require('node:child_process').spawn(process.execPath,['-e',${JSON.stringify(grandchild)}],{stdio:'inherit'});require('node:fs').writeFileSync(${JSON.stringify(started)},'started');setInterval(()=>{},10000)`
  const input=new PassThrough(),output=new PassThrough(),error=new PassThrough()
  const server=serve({input,output,error,command:process.execPath,args:['-e',script],spawnServer:spawn,
    env:{...process.env,DSH_KLINE_CACHE_DIR:directory,DSH_KLINE_HOST_PID:String(process.pid)}})
  try {
    input.write(JSON.stringify({jsonrpc:'2.0',id:1,method:'initialize',params:{protocolVersion:'2024-11-05'}})+'\n')
    const deadline=Date.now()+5000
    while(!existsSync(started) && Date.now()<deadline)await delay(20)
    assert.ok(existsSync(started),'installer descendant did not start')
    server.shutdown()
    await delay(3500)
    assert.equal(existsSync(leaked),false,'an installer survived its MCP owner')
  } finally {server.shutdown();rmSync(directory,{recursive:true,force:true})}
})


test('string request IDs cannot collide with the completed backend handshake', () => {
  const f=fixture()
  try {
    f.initialize();f.ready()
    const id='dsh-kline-bootstrap-initialize'
    f.send({id,method:'tools/call',params:{name:'list_ta_functions',arguments:{limit:1}}})
    const result={content:[{type:'text',text:'ok'}]}
    f.children[0].stdout.write(JSON.stringify({jsonrpc:'2.0',id,result})+'\n')
    assert.deepEqual(f.replies.at(-1),{jsonrpc:'2.0',id,result})
  } finally {f.close()}
})
