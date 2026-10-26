import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {runInNewContext} from 'node:vm'

const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
const between=(a:string,b:string)=>html.slice(html.indexOf(a),html.indexOf(b,html.indexOf(a)))
const ingest=between('    if (!structured.local_render) {','    const previousSymbol')
const build=between('function buildLocalChartPayload(','async function renderCurrentViewLocally(')
const sequenceHash=between('function candleSequenceHash(','function drawAgentSeriesLineCommands(')
const collect=between('function captureChartContext(','function refreshMirrorAxes(')
const workspaces=between('function rememberWorkspaceTab(','async function closeWorkspaceTab(')
const rows=[1,2].map(time=>({time:time*60,open:31,high:33,low:30,close:32,volume:1}))
function fixture() {
  const c:any={currentSymbol:'TEST.X',currentName:'测试',currentInterval:'minute',currentRangeKey:'custom',currentAdjust:'forward',
    sourceCandles:rows,sourceCandleInterval:'minute',sourceCandleIntervalValue:null,localChartDataMeta:{source:'ftshare'},lastChartPayload:null,
    legacySequenceRowHashes:new Map(),
    sourceRowsForCurrentInterval:()=>c.sourceCandles,cropRowsForRange:(value:any)=>value,buildLocalIndicatorCommands:()=>[],activeIndicators:()=>['vol'],
    indicatorStateVersion:1,INDICATOR_HISTORY_BUFFER_DAYS:0,lastLines:[],lastMarks:[],lastHorizontalLines:[],lastAgentTrendLines:[],lastAgentChannels:[],lastAgentRectangles:[],lastAgentFibonacci:[],lastAgentPolylines:[],lastAgentAnnotations:[],lastAgentSeriesLines:[],lastAgentPriceBands:[],lastAgentPriceSticks:[],
    activeSecurityTab:'chart',currentCandles:rows,openingSymbol:false,kchart:{getVisibleRange:()=>({from:0,to:2})},
    userDrawings:[],customLevels:[],analysisLevels:[],currentSelection:null,maVisible:false,vwapVisible:false,volVisible:true,macdVisible:false,kdjVisible:false,bollVisible:false,rsiVisible:false,atrVisible:false,chartDataStatus:'delayed',volumeUnit:'wan',exchangeTimezone:'Asia/Shanghai',
    workspaceTabs:[],activeWorkspaceTabId:'',workspaceTabId:(p:any)=>p.symbol,renderWorkspaceTabs(){},saveWorkspacePreferences(){},
    securityWorkspaceData:{},securityWorkspaceLoading:false,securityIntelligenceData:{},securityIntelligenceLoading:false,
    activeCompanyTab:'overview',clearRangePick(){},securityWorkspaceRequestId:0,securityIntelligenceRequestId:0,
    syncTimeControls(){},rememberAnalysisCommands(){},handleToolResult(){}}
  const api=runInNewContext(sequenceHash+build+collect+workspaces+';({build:buildLocalChartPayload,hash:candleSequenceHash,capture:()=>captureChartContext("a".repeat(32)),remember:rememberWorkspaceTab,select:selectWorkspaceTab})',c)
  const receive=(value:any,symbol='TEST.X')=>{
    c.structured={symbol,interval:'minute',interval_value:value,adjust:'forward',data_meta:{source:'ftshare'},chartCommands:[{type:'SET_CANDLES',rows}]}
    runInNewContext(ingest,c);c.currentSymbol=symbol;c.lastChartPayload=c.structured
  }
  return {c,api,receive}
}

test('declared minute size survives actual ingestion, repeated local redraw and observation without changing rows',()=>{
  for(const size of [1,5,15,240]) {
    const {c,api,receive}=fixture();receive(size)
    for(let n=0;n<3;n++) {
      c.lastChartPayload=api.build(rows)
      assert.equal(c.lastChartPayload.interval_value,size)
      assert.equal(api.capture().interval_value,size)
      assert.equal(c.lastChartPayload.chartCommands[0].rows,rows)
      assert.equal(c.currentAdjust,'forward')
    }
  }
})

test('missing/invalid new source size stays unknown and drawing-only metadata cannot overwrite known source',()=>{
  for(const bad of [undefined,null,0,241,1.5,'1',true,NaN]) {
    const {c,api,receive}=fixture();receive(5);receive(bad,'OTHER.X')
    c.lastChartPayload=api.build(rows)
    assert.equal(c.lastChartPayload.interval_value,null)
    assert.equal(api.capture().interval_value,null)
  }
  const {c,api,receive}=fixture();receive(5)
  c.structured={interval:'minute',interval_value:1,chartCommands:[]};runInNewContext(ingest,c)
  c.lastChartPayload=api.build(rows);assert.equal(api.capture().interval_value,5)
})

test('source minute size is workspace-owned, round trips and cannot inherit another tab or repair legacy unknowns',async()=>{
  const {c,api,receive}=fixture();receive(5)
  c.lastChartPayload=api.build(rows);api.remember(c.lastChartPayload)
  assert.equal(c.workspaceTabs[0].sourceIntervalValue,5)
  c.sourceCandleIntervalValue=1;c.activeWorkspaceTabId='OTHER.X'
  await api.select('TEST.X')
  c.lastChartPayload=api.build(rows);assert.equal(api.capture().interval_value,5)
  delete c.workspaceTabs[0].sourceIntervalValue;delete c.workspaceTabs[0].payload.interval_value
  c.sourceCandleIntervalValue=1;c.activeWorkspaceTabId='OTHER.X'
  await api.select('TEST.X')
  c.lastChartPayload=api.build(rows);assert.equal(api.capture().interval_value,null)
})

test('local redraw retains aligned sequence objects but never reuses them on changed candles',()=>{
  const {c,api,receive}=fixture();receive(5)
  const line={type:'DRAW_AGENT_SERIES_LINE',id:'series:a',interval:'minute',bar_count:2}
  const band={type:'DRAW_AGENT_PRICE_BAND',id:'band:a',interval:'minute',bar_count:2}
  const sticks={type:'DRAW_AGENT_PRICE_STICKS',id:'sticks:a',interval:'minute',bar_count:2}
  c.lastAgentSeriesLines=[line];c.lastAgentPriceBands=[band];c.lastAgentPriceSticks=[sticks]
  const same=api.build(rows)
  assert.ok(same.chartCommands.includes(line));assert.ok(same.chartCommands.includes(band));assert.ok(same.chartCommands.includes(sticks))
  const changed=rows.map((row,index)=>index===1?{...row,close:31.5}:row)
  const stale=api.build(changed)
  assert.ok(!stale.chartCommands.includes(line));assert.ok(!stale.chartCommands.includes(band));assert.ok(!stale.chartCommands.includes(sticks))
})

test('hashed sequence drawings survive daily-weekly-daily without crossing into changed candles',()=>{
  const {c,api}=fixture()
  const day=rows.map((row,index)=>({...row,time:(index+1)*86400}))
  const week=[{...day[0],time:day[1].time,open:31,high:33,low:30,close:32,volume:2}]
  c.currentInterval='day';c.lastChartPayload={symbol:'TEST.X',interval:'day',chartCommands:[{type:'SET_CANDLES',rows:day}]}
  const line={type:'DRAW_AGENT_SERIES_LINE',id:'series:day',interval:'day',bar_count:2,row_hash:api.hash(day)}
  const band={type:'DRAW_AGENT_PRICE_BAND',id:'band:day',interval:'day',bar_count:2,row_hash:api.hash(day)}
  const sticks={type:'DRAW_AGENT_PRICE_STICKS',id:'sticks:day',interval:'day',bar_count:2,row_hash:api.hash(day)}
  c.lastAgentSeriesLines=[line];c.lastAgentPriceBands=[band];c.lastAgentPriceSticks=[sticks]
  c.currentInterval='week'
  const weekly=api.build(week)
  assert.ok(weekly.chartCommands.includes(line));assert.ok(weekly.chartCommands.includes(band));assert.ok(weekly.chartCommands.includes(sticks))
  c.lastChartPayload=weekly;c.currentInterval='day'
  const returned=api.build(day)
  assert.ok(returned.chartCommands.includes(line));assert.ok(returned.chartCommands.includes(band));assert.ok(returned.chartCommands.includes(sticks))
  const changed=day.map((row,index)=>index===1?{...row,close:31.5}:row)
  const stale=api.build(changed)
  assert.ok(!stale.chartCommands.includes(line));assert.ok(!stale.chartCommands.includes(band));assert.ok(!stale.chartCommands.includes(sticks))
  c.currentSymbol='OTHER.X';c.currentInterval='week'
  const other=api.build(week)
  assert.ok(!other.chartCommands.includes(line));assert.ok(!other.chartCommands.includes(band));assert.ok(!other.chartCommands.includes(sticks))
})

test('interactive fetch records explicit returned minute size; omitted metadata never inherits last source',()=>{
  const {c}=fixture()
  const code=between('    sourceCandles = fetched.rows.slice();','    currentSymbol = fetched.symbol')
  c.options={};c.fetched={rows,interval:'minute',interval_value:5,adjust:'backward'}
  runInNewContext(code,c);assert.equal(c.sourceCandleIntervalValue,5)
  delete c.fetched.interval_value
  runInNewContext(code,c);assert.equal(c.sourceCandleIntervalValue,null)
})
