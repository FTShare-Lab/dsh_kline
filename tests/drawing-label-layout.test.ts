import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
function extractHelpers(source:string) {
  const normalized=source.replace(/\r\n?/g,'\n')
  const start=normalized.indexOf('  let agentLabelCache =')
  const end=normalized.indexOf('  try {\n    window.klinecharts.registerOverlay',start)
  assert.ok(start>=0 && end>start,'label helper boundaries must exist')
  return normalized.slice(start,end)
}
const helpers = extractHelpers(html)
const plain = (value:any) => JSON.parse(JSON.stringify(value))
function fixture() {
  const objects = new Map<string,any>(), payload:any = {chartCommands:[]}
  let offset = 0, gutter = 0, measureCount = 0
  const chart:any = {getOverlayById:(id:string) => objects.get(id),
    convertToPixel:(points:any[], options:any) => {assert.equal(options.absolute,false); return points.map(p=>({x:p.x+offset,y:p.y}))}}
  const fn = runInNewContext(helpers + '; ({wrapAgentLabelText,placeAgentLabels,agentLabelEntry,agentDrawingLabelFigures,getCache:()=>agentLabelCache})', {
    kchart:chart, lastChartPayload:payload,
    document:{getElementById:()=>gutter ? {} : null,createElement:()=>({getContext:()=>({
      measureText:(text:string)=>{measureCount++;return {width:Array.from(text).length*11}},font:''})})},
    rightAxisGutterWidth:()=>gutter,
  })
  const add = (id:string,name='ftvAgentRectangle',label='完整观察平台',points=[{x:40,y:40},{x:120,y:100}]) => {
    const object = {id,name,points,extendData:{label,agent:true,price:30},visible:true}
    objects.set(id,object);payload.chartCommands.push({id,type:'DRAW_AGENT_RECTANGLE'});return object
  }
  const render = (id:string,width=600,height=320) => {
    const overlay=objects.get(id), coordinates=chart.convertToPixel(overlay.points,{absolute:false})
    return fn.agentDrawingLabelFigures(overlay,coordinates,{width,height},
      {type:'text',attrs:{x:0,y:0,text:overlay.extendData.label},styles:{size:11,color:'#ffffff',backgroundColor:'#ff7a00'}})
  }
  return {fn,objects,payload,add,render,setOffset:(x:number)=>{offset=x},setGutter:(x:number)=>{gutter=x},measureCount:()=>measureCount}
}
function textBox(figures:any[]) {
  const text=figures.filter(f=>f.type==='text')
  return {x:text[0].attrs.x,y:text[0].attrs.y,width:Math.max(...text.map(f=>Array.from(f.attrs.text).length*11))+10,
    height:text.length*15+4,text:text.map(f=>f.attrs.text).join('')}
}
const overlaps = (a:any,b:any) => a.x < b.x+b.width && a.x+a.width > b.x && a.y < b.y+b.height && a.y+a.height > b.y

test('actual label helper extraction accepts LF and Windows CRLF without capturing unrelated chart code',()=>{
  const lf=html.replace(/\r\n?/g,'\n')
  assert.equal(extractHelpers(lf),extractHelpers(lf.replace(/\n/g,'\r\n')))
  assert.doesNotMatch(extractHelpers(lf),/registerOverlay|applyNewData|fetch\(/)
})

test('coincident same-name labels separate deterministically regardless of callback order; geometry is immutable',()=>{
  const f=fixture(); f.add('B'); f.add('A')
  const before=JSON.stringify([...f.objects.values()])
  const b=textBox(f.render('B')),a=textBox(f.render('A'))
  const cached=f.fn.getCache();f.render('B');assert.equal(f.fn.getCache(),cached)
  assert.equal(overlaps(a,b),false);assert.equal(a.text,'完整观察平台');assert.equal(b.text,a.text)
  assert.deepEqual(plain(f.render('B')),plain(f.render('B')))
  assert.equal(JSON.stringify([...f.objects.values()]),before)
  const second=fixture();second.add('A');second.add('B')
  assert.deepEqual(textBox(second.render('A')),a);assert.deepEqual(textBox(second.render('B')),b)
  assert.ok(f.render('B').some((v:any)=>v.type==='line' && v.ignoreEvent))
})

test('all four AI families share placement while non-AI trend labels are excluded',()=>{
  const f=fixture()
  f.add('rectangle');f.add('trend','ftvTrendLine','趋势线')
  f.add('channel','ftvAgentChannel','平行通道',[{x:40,y:40},{x:120,y:100},{x:40,y:60},{x:120,y:120}])
  f.add('horizontal','ftvHorizontalLine','指定价位',[{x:120,y:50}])
  const boxes=['rectangle','trend','channel','horizontal'].map(id=>textBox(f.render(id)))
  for(let a=0;a<boxes.length;a++)for(let b=a+1;b<boxes.length;b++)assert.equal(overlaps(boxes[a],boxes[b]),false)
  assert.equal(boxes[3].text,'指定价位 30')
  assert.equal(f.fn.agentLabelEntry({id:'manual',name:'ftvTrendLine',extendData:{label:'手动线'}},[{x:40,y:40},{x:120,y:100}],600,320,()=>22),null)
})

test('edge clamping respects the percentage-axis gutter; long Chinese names wrap without shortening',()=>{
  const f=fixture(); f.setGutter(80)
  const name='这是用户要求完整保留的中文平台名称'.repeat(3)
  f.add('long','ftvAgentRectangle',name,[{x:310,y:2},{x:340,y:80}])
  const figures=f.render('long',400,320),box=textBox(figures)
  assert.equal(box.text,name);assert.ok(figures.filter((v:any)=>v.type==='text').length>1)
  assert.ok(box.x>=4 && box.x+box.width<=316);assert.ok(box.y>=4 && box.y+box.height<=316)
  assert.ok(figures.filter((v:any)=>v.type==='text').every((v:any)=>v.styles.color==='#ffffff'))
})

test('pan/zoom projections and pane resize reflow labels without requiring a new snapshot revision',()=>{
  const f=fixture();f.add('A');f.add('B')
  const first=textBox(f.render('A')); f.setOffset(100)
  assert.equal(textBox(f.render('A')).x,first.x+100)
  const narrower=textBox(f.render('A',200,180))
  assert.ok(narrower.x+narrower.width<=196);assert.ok(narrower.y+narrower.height<=176)
})

test('fully offscreen or hidden objects do not reserve space or leave floating labels',()=>{
  const f=fixture();f.add('visible');f.add('off','ftvAgentRectangle','屏幕外',[{x:-220,y:20},{x:-120,y:120}])
  assert.equal(f.render('off').length,0)
  const before=textBox(f.render('visible'));f.objects.get('off').visible=false
  assert.deepEqual(textBox(f.render('visible')),before)
  f.add('line','ftvHorizontalLine','超范围',[{x:40,y:-20}]);assert.equal(f.render('line').length,0)
})

test('updates/deletes/restores use the current SDK objects and do not leave cached label reservations',()=>{
  const f=fixture();f.add('A');f.add('B')
  const shared=textBox(f.render('B'))
  f.objects.delete('A');f.payload.chartCommands=f.payload.chartCommands.filter((c:any)=>c.id!=='A')
  const single=textBox(f.render('B'));assert.notDeepEqual(shared,single)
  f.objects.get('B').extendData.label='新名称';assert.equal(textBox(f.render('B')).text,'新名称')
  f.objects.get('B').extendData.label='完整观察平台';f.add('A')
  assert.deepEqual(textBox(f.render('B')),shared)
})

test('layout helper is bounded and stable for dense inventory; rendering falls back if SDK APIs fail',()=>{
  const f=fixture(),entries=Array.from({length:180},(_,i)=>({id:String(i).padStart(3,'0'),x:10,y:10,width:80,height:19}))
  const first=f.fn.placeAgentLabels(entries,600,320),second=f.fn.placeAgentLabels([...entries].reverse(),600,320)
  assert.equal(first.size,180);assert.deepEqual(plain([...first]),plain([...second]))
  for(const box of first.values())assert.ok(box.x>=4 && box.y>=4 && box.x+box.width<=596 && box.y+box.height<=316)
  f.add('A');f.add('bad');f.objects.get('bad').points=null
  assert.equal(f.render('A')[0].attrs.text,'完整观察平台')
})

test('label layout cannot mutate application, observation, receipt or geometry protocols',()=>{
  assert.doesNotMatch(helpers,/createOverlay|removeOverlay|overrideOverlay|applyNewData|fetch\(|localStorage|render_verified|pixel_verified/)
  assert.match(helpers,/absolute: false/)
  assert.match(helpers,/if \(agentLabelCache.key !== key\)/)
  assert.match(helpers,/let comparisonsLeft = 30000/)
})
