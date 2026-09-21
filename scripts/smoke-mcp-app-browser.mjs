// Headless browser test with a local MCP Apps host fixture, not a Codex Desktop test.
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const python = process.env.DSH_KLINE_TEST_PYTHON || join(root, '.venv/bin/python')
const fixture = JSON.parse(execFileSync(python, ['-c', `
import asyncio,json
import server
from adapters.mcp_apps import mcp_app_html
rows=[dict(time=1700000000+i*86400,open=100+i,high=103+i,low=99+i,close=102+i,volume=1000+i) for i in range(60)]
r=asyncio.run(server.analyze_kline_rows(rows,"BROWSER.FIXTURE",name="Browser fixture",indicators=["ma","vol","macd"]))
print(json.dumps(dict(html=mcp_app_html(),payload=r.structuredContent)))
`], { cwd: root, env: { ...process.env, DSH_KLINE_ADAPTER: 'codex' }, maxBuffer: 10 * 1024 * 1024, encoding: 'utf8' }))
const parentHtml = `<!doctype html><style>html,body{margin:0;background:#eee}iframe{width:960px;height:850px;border:0}</style><iframe src="/app"></iframe><script>
const payload=${JSON.stringify(fixture.payload).replaceAll('<', '\\u003c')};
window.requests=[];
addEventListener('message',e=>{
 const m=e.data;if(!m||m.jsonrpc!=='2.0')return;
 window.requests.push(m.method);
 const send=result=>e.source.postMessage({jsonrpc:'2.0',id:m.id,result},'*');
 if(m.method==='ui/initialize')send({protocolVersion:'2026-01-26',hostCapabilities:{},hostContext:{theme:'dark',locale:'zh-CN',displayMode:'inline',availableDisplayModes:['inline','fullscreen']}});
 else if(m.method==='ui/notifications/initialized')e.source.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:payload}},'*');
 else if(m.method==='ui/request-display-mode')send({mode:m.params.mode});
 else if(m.method==='tools/call'){
   const action=m.params.arguments.action;
   let data={ok:true,items:[],rows:[],results:[]};
   if(action==='watchlist_get')data.watchlist={version:1,revision:0,groups:[{id:'default',name:'Default'}],items:[],activeGroupId:'default',sort:'manual'};
   if(action==='data_source_status')data.providers={ftshare:{available:false,configured:false,capabilities:{}}};
   send({structuredContent:data,content:[],isError:false});
 }
});</script>`
const server = createServer((req, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8')
  res.end(req.url === '/app' ? fixture.html : parentHtml)
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const scratch = await mkdtemp(join(tmpdir(), 'dsh-kline-browser-'))
const chrome = spawn(process.env.CHROME_BIN || '/usr/bin/google-chrome', [
  '--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
  '--remote-debugging-port=0', `--user-data-dir=${join(scratch, 'profile')}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] })
const exited = new Promise(resolve => chrome.once('exit', resolve))
let socket
try {
  const endpoint = await new Promise((resolve, reject) => {
    let log = ''
    const timeout = setTimeout(() => reject(Error('Chrome did not start')), 15000)
    chrome.on('error', error => { clearTimeout(timeout); reject(error) })
    chrome.stderr.on('data', data => {
      log += data.toString()
      const match = log.match(/DevTools listening on (ws:\/\/\S+)/)
      if (match) { clearTimeout(timeout); resolve(match[1]) }
    })
  })
  socket = new WebSocket(endpoint)
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
  let sequence = 0
  const pending = new Map(), errors = []
  socket.onmessage = event => {
    const message = JSON.parse(event.data)
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails)
    if (!pending.has(message.id)) return
    const entry = pending.get(message.id); pending.delete(message.id); clearTimeout(entry.timer)
    if (message.error) entry.reject(Error(JSON.stringify(message.error))); else entry.resolve(message.result)
  }
  const request = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => { pending.delete(id); reject(Error(`${method} timeout`)) }, 15000)
    pending.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ id, method, params, sessionId }))
  })
  const { targetId } = await request('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await request('Target.attachToTarget', { targetId, flatten: true })
  await request('Runtime.enable', {}, sessionId)
  await request('Page.enable', {}, sessionId)
  await request('Emulation.setDeviceMetricsOverride', { width: 1100, height: 900, deviceScaleFactor: 1, mobile: false }, sessionId)
  await request('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` }, sessionId)
  const evaluate = async expression => (await request('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId)).result.value
  const waitFor = async expression => {
    const deadline = Date.now() + 15000
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    throw Error(`Browser condition failed: ${expression}`)
  }
  await waitFor(`document.querySelector('iframe')?.contentWindow?.currentCandles?.length === 60 || (()=>{try{return document.querySelector('iframe').contentWindow.eval('currentCandles.length')===60}catch{return false}})()`)
  const result = await evaluate(`(()=>{const d=document.querySelector('iframe').contentDocument;const b=d.querySelector('#mcpDisplayModeBtn');return {width:b.getBoundingClientRect().width,text:b.textContent,canvas:d.querySelectorAll('canvas').length,disabled:b.disabled}})()`)
  assert.equal(result.width, 30)
  assert.equal(result.text.trim(), '')
  assert.ok(result.canvas > 0)
  assert.equal(result.disabled, false)
  const state = () => evaluate(`(()=>{const w=document.querySelector('iframe').contentWindow;return {theme:w.eval('currentTheme()'),language:w.eval('viewLanguage')}})()`)
  assert.deepEqual(await state(), { theme: 'dark', language: 'zh' })
  const context = async (theme, locale) => {
    await evaluate(`document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:${JSON.stringify({theme, locale})}},'*')`)
  }
  await context('light', 'en-US')
  await waitFor(`(()=>{const w=document.querySelector('iframe').contentWindow;return w.eval('currentTheme()')==='light'&&w.eval('viewLanguage')==='en'})()`)
  await evaluate(`document.querySelector('iframe').contentWindow.eval('setTheme("dark").then(()=>setLanguage("zh"))')`)
  await context('light', 'en-US')
  assert.deepEqual(await state(), { theme: 'dark', language: 'zh' })
  await evaluate(`document.querySelector('iframe').contentWindow.eval('setTheme("host").then(()=>setLanguage("host"))')`)
  assert.deepEqual(await state(), { theme: 'light', language: 'en' })
  await evaluate(`document.querySelector('iframe').contentDocument.querySelector('#mcpDisplayModeBtn').click()`)
  await waitFor(`document.querySelector('iframe').contentDocument.querySelector('#mcpDisplayModeBtn').getAttribute('aria-expanded')==='true'`)
  await evaluate(`document.querySelector('iframe').contentDocument.querySelector('#mcpDisplayModeBtn').click()`)
  await waitFor(`document.querySelector('iframe').contentDocument.querySelector('#mcpDisplayModeBtn').getAttribute('aria-expanded')==='false'`)
  assert.equal(errors.length, 0, JSON.stringify(errors))
  const { data } = await request('Page.captureScreenshot', { format: 'png' }, sessionId)
  const screenshot = join(scratch, 'mcp-app.png')
  await writeFile(screenshot, Buffer.from(data, 'base64'))
  console.log('PASS actual Chrome: 60 candles, chart canvases, host theme/language and manual overrides, 30px icon, inline/fullscreen round trip, no JS exceptions')
  console.log(`Screenshot: ${screenshot}`)
} finally {
  socket?.close()
  chrome.kill('SIGTERM')
  await exited
  server.close()
}
