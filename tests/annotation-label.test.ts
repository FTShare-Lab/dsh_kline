import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {runInNewContext} from 'node:vm'

test('latest-candle annotation uses the drawable pane edge, not the wider chart container',()=>{
  const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
  const templates:any[]=[]
  runInNewContext(html.slice(html.indexOf('function registerOverlays('),html.indexOf('function initChart('))+';registerOverlays()',{
    overlaysRegistered:false,window:{klinecharts:{registerOverlay:(overlay:any)=>{
      templates.push(overlay);if(overlay.name==='ftvAgentAnnotation')throw Error('captured')
    }}},console:{warn(){}},colorFor:()=> '#123456',
    document:{getElementById:(id:string)=>id==='percentAxis'?{}:{clientWidth:600}},
    rightAxisGutterWidth:()=>52,
  })
  const template=templates.find(t=>t.name==='ftvAgentAnnotation');assert.ok(template)
  const overlay={points:[{timestamp:1000,value:1331.88}],extendData:{annotationKind:'text_annotation',
    label:'QA-条件命中',text:'QA-已改',colorName:'info'}}
  const right=template.createPointFigures({overlay,coordinates:[{x:285,y:100}],bounding:{width:320,height:220}})[0]
  assert.equal(right.attrs.text,'QA-条件命中 · QA-已改')
  assert.equal(right.attrs.align,'right')
  assert.equal(right.attrs.x,260)
  assert.equal(overlay.points[0].value,1331.88)
  const middle=template.createPointFigures({overlay,coordinates:[{x:125,y:100}],bounding:{width:320,height:220}})[0]
  assert.equal(middle.attrs.x,125)
  assert.equal(middle.attrs.align,'left')
})
