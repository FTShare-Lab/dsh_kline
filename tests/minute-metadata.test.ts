import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {runInNewContext} from 'node:vm'

const html=readFileSync(new URL('../view/kline.html',import.meta.url),'utf8')
const between=(a:string,b:string)=>html.slice(html.indexOf(a),html.indexOf(b,html.indexOf(a)))
const ingest=between('    if (!structured.local_render) {','    const previousSymbol')
const build=between('function buildLocalChartPayload(','async function renderCurrentViewLocally(')
const collect=between('function captureChartContext(','function refreshMirrorAxes(')
const workspaces=between('function rememberWorkspaceTab(','async function closeWorkspaceTab(')
const rows=[1,2].map(time=>({time:time*60,open:31,high:33,low:30,close:32,volume:1}))
function fixture() {
  const c:any={currentSymbol:'TEST.X',currentName:'测试',currentInterval:'minute',currentRangeKey:'custom',currentAdjust:'forward',
    sourceCandles:rows,sourceCandleInterval:'minute',sourceCandleIntervalValue:null,localChartDataMeta:{source:'ftshare'},lastChartPayload:null,
    sourceRowsForCurrentInterval:()=>c.sourceCandles,buildLocalIndicatorCommands:()=>[],activeIndicators:()=>['vol'],
    indicatorStateVersion:1,INDICATOR_HISTORY_BUFFER_DAYS:0,lastLines:[],lastMarks:[],lastHorizontalLines:[],lastAgentTrendLines:[],lastAgentChannels:[],lastAgentRectangles:[],
    activeSecurityTab:'chart',currentCandles:rows,openingSymbol:false,kchart:{getVisibleRange:()=>({from:0,to:2})},
    userDrawings:[],customLevels:[],analysisLevels:[],currentSelection:null,maVisible:false,vwapVisible:false,volVisible:true,macdVisible:false,kdjVisible:false,bollVisible:false,rsiVisible:false,atrVisible:false,chartDataStatus:'delayed',volumeUnit:'wan',exchangeTimezone:'Asia/Shanghai',
    workspaceTabs:[],activeWorkspaceTabId:'',workspaceTabId:(p:any)=>p.symbol,renderWorkspaceTabs(){},saveWorkspacePreferences(){},
    securityWorkspaceData:{},securityWorkspaceLoading:false,securityIntelligenceData:{},securityIntelligenceLoading:false,
    activeCompanyTab:'overview',clearRangePick(){},securityWorkspaceRequestId:0,securityIntelligenceRequestId:0,
    syncTimeControls(){},rememberAnalysisCommands(){},handleToolResult(){}}
  const api=runInNewContext(build+collect+workspaces+';({build:buildLocalChartPayload,capture:()=>captureChartContext("a".repeat(32)),remember:rememberWorkspaceTab,select:selectWorkspaceTab})',c)
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

test('interactive fetch records explicit returned minute size; omitted metadata never inherits last source',()=>{
  const {c}=fixture()
  const code=between('    sourceCandles = fetched.rows.slice();','    currentSymbol = fetched.symbol')
  c.options={};c.fetched={rows,interval:'minute',interval_value:5,adjust:'backward'}
  runInNewContext(code,c);assert.equal(c.sourceCandleIntervalValue,5)
  delete c.fetched.interval_value
  runInNewContext(code,c);assert.equal(c.sourceCandleIntervalValue,null)
})
