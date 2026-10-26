import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createContext, runInContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const analysis = html.slice(html.indexOf('let keyLevelsRequestVersion ='), html.indexOf('async function submitRangeAnalyze('))
const clear = html.slice(html.indexOf('function clearAnalysisAnnotations('), html.indexOf('function syncAutoLevelsFromPayload('))
function fixture() {
  const state: any = { currentSymbol: 'A', currentName: 'A', currentInterval: 'year', currentRangeKey: 'custom', currentAdjust: 'forward',
    currentCandles: Array.from({ length: 10 }, (_, i) => ({ time: i + 1, close: 10 })),
    analysisLevels: [{ symbol: 'A' }, { symbol: 'B' }], customLevels: [], userDrawings: [], lastMarks: [], lastLines: [], rangePickStart: null, currentSelection: null,
    calls: [], statuses: [], updates: [], saves: 0, drawingClears: 0, customClears: 0,
    nodes: {} as Record<string, any>, aiDrawings: [] as any[], deletedAi: [] as string[],
    document: { getElementById(id: string) { return state.nodes[id] ||= { disabled: false, hidden: true, textContent: '', classList: { add() {}, remove() {} }, setAttribute() {} } } },
    window: { setTimeout() {}, __DSH_KLINE_OBSERVATION__: { ok: true, revision: 1, context_ref: 'a'.repeat(32) }, __DSH_KLINE_REPORT_CONTEXT__() {} }, console, t: (s: string) => s,
    clearRangePick() { state.rangePickStart = null }, clearOverlays() {}, persistAnnotationRemoval() {},
    drawLevelOverlays() {}, renderLevelsPanel() {}, renderKeyLevelPlan() {}, cancelLevelPlace() {},
    saveWorkspacePreferences() { state.saves++ },
    clearCurrentUserDrawings() { state.drawingClears++; state.userDrawings = state.userDrawings.filter((d: any) => d.symbol !== state.currentSymbol) },
    clearCurrentCustomLevels() { state.customClears++; state.customLevels = state.customLevels.filter((d: any) => d.symbol !== state.currentSymbol) },
    captureChartContext() { return { state: 'ready', drawings: state.aiDrawings } },
    lastChartPayload: { _live_chart_session: 'b'.repeat(32) },
    WORKBENCH_KINDS: { channel: 'channel', fibonacci: 'fibonacci_retracement' },
    workbenchState: { selectedId: null, selectedParameters: null, anchors: [] },
    workbenchInvalidate() {}, renderDrawingWorkbench() {},
    workbenchCurrentBinding() { return { context_ref: 'a'.repeat(32), expected_revision: state.window.__DSH_KLINE_OBSERVATION__.revision, chart_session: 'b'.repeat(32), symbol: state.currentSymbol } },
    async workbenchApplyProposal({edit}: any) {
      assert.equal(edit.kind, 'all_drawings'); assert.equal(edit.action, 'delete'); assert.equal(edit.object_id, undefined)
      state.deletedAi.push(...state.aiDrawings.filter((d: any) => d.origin === 'ai' && d.interval === state.currentInterval).map((d: any) => d.id))
      state.aiDrawings = state.aiDrawings.filter((d: any) => d.origin !== 'ai' || d.interval !== state.currentInterval)
      state.window.__DSH_KLINE_OBSERVATION__.revision++
    },
    async sleep() {},
    setChartStatus(s: string) { state.statuses.push(s) }, showActivityNotice() {}, finishActivityNotice() {},
    dismissActivityNotice() {},
    syncAutoLevelsFromPayload(r: any) { state.updates.push(r) },
    async callMarketTool(name: string, args: any) { state.calls.push({ name, args }); return { structuredContent: { status: 'ready' } } },
  }
  const context = createContext(state)
  runInContext(analysis + clear, context)
  return { state, context }
}
test('key levels send displayed rows only and preserve chart settings', async () => {
  const { state, context } = fixture()
  const rows = state.currentCandles
  await runInContext('analyzeKeyLevels()', context)
  assert.equal(state.calls[0].name, 'analyze_key_levels')
  assert.equal(state.calls[0].args.rows, rows)
  assert.equal(state.currentCandles, rows)
  assert.equal(state.currentAdjust, 'forward')
  assert.equal(state.currentInterval, 'year')
  assert.equal(state.updates.length, 1)
})
test('insufficient bars do not call service; no levels is not a failure', async () => {
  const { state, context } = fixture()
  state.currentCandles = []
  await runInContext('analyzeKeyLevels()', context)
  assert.equal(state.calls.length, 0)
  assert.equal(state.statuses.at(-1), 'keyLevelsInsufficient')
  state.currentCandles = Array(5).fill({ close: 1 })
  state.callMarketTool = async () => ({ structuredContent: { status: 'no_levels' } })
  await runInContext('analyzeKeyLevels()', context)
  assert.equal(state.statuses.at(-1), 'keyLevelsEmpty')
})
test('late analysis cannot reappear after clear, symbol change or disposal', async () => {
  for (const action of ['clearAnalysisAnnotations()', 'currentSymbol = "B"', 'window.__DSH_KLINE_DISPOSED__ = true']) {
    const { state, context } = fixture()
    let resolve: any
    state.callMarketTool = () => new Promise(r => { resolve = r })
    const pending = runInContext('analyzeKeyLevels()', context)
    runInContext(action, context)
    resolve({ status: 'ready' })
    await pending
    assert.equal(state.updates.length, 0)
  }
})
test('analysis clear preserves other symbols and persists selection-only clears', () => {
  const { state, context } = fixture()
  runInContext('clearAnalysisAnnotations()', context)
  assert.equal(state.analysisLevels.length, 1)
  assert.equal(state.analysisLevels[0].symbol, 'B')
  assert.equal(state.drawingClears, 0)
  assert.equal(state.customClears, 0)
  assert.equal(state.saves, 1)
})
test('key-level button opens, closes and cancels an in-flight request', async () => {
  const { state, context } = fixture()
  let resolve: any
  state.callMarketTool = () => new Promise(r => { resolve = r })
  runInContext('toggleKeyLevelPlan()', context)
  assert.equal(runInContext('keyLevelPlanExpanded', context), true)
  runInContext('toggleKeyLevelPlan()', context)
  assert.equal(runInContext('keyLevelPlanExpanded', context), false)
  resolve({ status: 'ready' })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(state.updates.length, 0)
})
test('reopening unchanged key levels reuses the result instead of recalculating', async () => {
  const { state, context } = fixture()
  await runInContext('analyzeKeyLevels()', context)
  runInContext('toggleKeyLevelPlan(); toggleKeyLevelPlan()', context)
  assert.equal(state.calls.length, 1)
})
test('real drawing and custom-level clear functions retain other symbols', () => {
  const { state, context } = fixture()
  state.userDrawings = [{ symbol: 'A' }, { symbol: 'B' }]
  state.customLevels = [{ symbol: 'A' }, { symbol: 'B' }]
  state.drawingMode = 'trend'
  state.drawingDraft = { time: 1 }
  state.setDrawingCaptureActive = () => {}
  state.renderUserDrawings = () => {}
  runInContext(html.slice(html.indexOf('function clearCurrentUserDrawings('), html.indexOf('function resetChartViewport(')), context)
  runInContext(html.slice(html.indexOf('function clearCurrentCustomLevels('), html.indexOf('function persistAnnotationRemoval(')), context)
  runInContext('clearCurrentUserDrawings(); clearCurrentCustomLevels()', context)
  assert.equal(state.userDrawings.length, 1)
  assert.equal(state.userDrawings[0].symbol, 'B')
  assert.equal(state.customLevels.length, 1)
  assert.equal(state.customLevels[0].symbol, 'B')
  assert.equal(state.drawingMode, '')
  assert.equal(state.drawingDraft, null)
})
test('cleared raw commands are removed from the saved chart without removing candles', () => {
  const { state, context } = fixture()
  const candles = { type: 'SET_CANDLES', rows: state.currentCandles }
  state.lastChartPayload = { symbol: 'A', chartCommands: [candles, { type: 'TEXT_MARKER' }, { type: 'DRAW_TREND_LINE' }] }
  state.rememberWorkspaceTab = () => {}
  state.window.__DSH_KLINE_SAVE_VIEW__ = (p: any) => { state.savedView = p }
  runInContext(html.slice(html.indexOf('function persistAnnotationRemoval('), html.indexOf('function clearAnalysisAnnotations(')), context)
  runInContext('persistAnnotationRemoval(["TEXT_MARKER", "DRAW_TREND_LINE"])', context)
  assert.equal(state.savedView.chartCommands.length, 1)
  assert.equal(state.savedView.chartCommands[0], candles)
})

test('one clear action deletes current-period AI objects before local marks while keeping indicators and alerts', async () => {
  const { state, context } = fixture()
  Object.assign(state, { userDrawings: [{symbol:'A'}, {symbol:'B'}], customLevels: [{symbol:'A'}, {symbol:'B'}],
    aiDrawings: [{id:'ai-1',origin:'ai',kind:'channel',interval:'year'}, {id:'ai-2',origin:'ai',kind:'fibonacci_retracement',interval:'year'},
      {id:'other-period',origin:'ai',kind:'series_line',interval:'day'}], maVisible:true, priceAlerts:[{symbol:'A',price:31}] })
  runInContext('showClearConfirmation()', context)
  await runInContext('clearCurrentChartAnnotations()', context)
  assert.deepEqual(state.deletedAi,['ai-1','ai-2'])
  assert.deepEqual(state.aiDrawings.map((d: any) => d.id), ['other-period'])
  assert.deepEqual(state.userDrawings,[{symbol:'B'}]); assert.deepEqual(state.customLevels,[{symbol:'B'}])
  assert.deepEqual(state.analysisLevels,[{symbol:'B'}]); assert.equal(state.maVisible,true)
  assert.deepEqual(state.priceAlerts,[{symbol:'A',price:31}]); assert.equal(state.currentInterval,'year')
  assert.equal(state.statuses.at(-1),'clearAllDone')
})

test('a guarded deletion failure stops before local marks are cleared', async () => {
  const { state, context } = fixture()
  state.aiDrawings = [{id:'ai-1',origin:'ai',kind:'channel',interval:'year'}]
  state.userDrawings = [{symbol:'A'}]
  state.workbenchApplyProposal = async () => { throw Error('revision conflict') }
  runInContext('showClearConfirmation()', context)
  await runInContext('clearCurrentChartAnnotations()', context)
  assert.equal(state.drawingClears, 0)
  assert.equal(state.userDrawings.length, 1)
  assert.match(state.statuses.at(-1), /revision conflict/)
})
test('an older local service falls back to guarded single-object edits only for supported kinds', async () => {
  const { state, context } = fixture()
  state.aiDrawings = [{id:'ai-1',origin:'ai',kind:'channel',interval:'year'}, {id:'ai-2',origin:'ai',kind:'fibonacci_retracement',interval:'year'}]
  state.userDrawings = [{symbol:'A'}]
  state.workbenchApplyProposal = async ({edit}: any) => {
    if (edit.kind === 'all_drawings') { const error: any = Error('old service'); error.code = 'invalid_workbench_request'; throw error }
    state.deletedAi.push(edit.object_id)
    state.aiDrawings = state.aiDrawings.filter((item: any) => item.id !== edit.object_id)
    state.window.__DSH_KLINE_OBSERVATION__.revision++
  }
  runInContext('showClearConfirmation()', context)
  await runInContext('clearCurrentChartAnnotations()', context)
  assert.deepEqual(state.deletedAi, ['ai-1','ai-2'])
  assert.equal(state.drawingClears, 1)
  assert.equal(state.statuses.at(-1), 'clearAllDone')
})
test('clear confirmation expires when chart objects change before confirmation', async () => {
  const { state, context } = fixture()
  state.aiDrawings = [{id:'ai-1',origin:'ai',kind:'channel',interval:'year'}]
  runInContext('showClearConfirmation()', context)
  state.aiDrawings.push({id:'ai-2',origin:'ai',kind:'rectangle',interval:'year'})
  await runInContext('clearCurrentChartAnnotations()', context)
  assert.equal(state.deletedAi.length, 0)
  assert.equal(state.statuses.at(-1), 'clearChanged')
})
test('global clear refuses a loading chart instead of silently leaving AI drawings', async () => {
  const { state, context } = fixture()
  state.captureChartContext = () => ({ state: 'loading', drawings: [] })
  state.userDrawings = [{symbol:'A'}]
  runInContext('showClearConfirmation()', context)
  assert.equal(state.nodes.confirmClearBtn.disabled, true)
  assert.equal(state.nodes.clearConfirmText.textContent, 'clearNotReady')
  await runInContext('clearCurrentChartAnnotations()', context)
  assert.equal(state.drawingClears, 0)
})

test('Chinese and English clear copy describes one action including AI drawings', () => {
  const copy = html.slice(html.indexOf('Object.assign(UI_COPY.zh,'), html.indexOf('function restoreCanvasHeight('))
  const vm: any = {UI_COPY:{zh:{},en:{}}}
  // Read only the two copy blocks, without running any browser initialization.
  for(const language of ['zh','en']) {
    const start=copy.indexOf(`Object.assign(UI_COPY.${language},`)
    const end=copy.indexOf('\n});',start)+4
    runInContext(copy.slice(start,end),createContext(vm))
    const labels=vm.UI_COPY[language]
    assert.match(labels.clearConfirmMessage,/AI/)
    assert.match(labels.clearAllDone,language==='zh'?/已清空/:/cleared/)
  }
  assert.doesNotMatch(html, /data-clear-kind=/)
  assert.doesNotMatch(html, /id="clearDrawingsBtn"|id="clearLevelsBtn"/)
  assert.match(html, /id="clearBtn"[^>]*>清除图形与标注/)
})
