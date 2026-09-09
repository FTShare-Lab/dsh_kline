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
    analysisLevels: [{ symbol: 'A' }, { symbol: 'B' }], lastMarks: [], lastLines: [], rangePickStart: null,
    calls: [], statuses: [], updates: [], saves: 0, drawingClears: 0, customClears: 0,
    document: { getElementById: () => ({ disabled: false, hidden: true, classList: { remove() {} }, setAttribute() {} }) },
    window: { setTimeout() {} }, console, t: (s: string) => s,
    clearRangePick() { state.rangePickStart = null }, clearOverlays() {}, persistAnnotationRemoval() {},
    drawLevelOverlays() {}, renderLevelsPanel() {}, cancelLevelPlace() {},
    saveWorkspacePreferences() { state.saves++ },
    clearCurrentUserDrawings() { state.drawingClears++ }, clearCurrentCustomLevels() { state.customClears++ },
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
test('category actions dispatch selectively, all clears all three categories', () => {
  for (const kind of ['analysis', 'drawings', 'custom', 'all']) {
    const { state, context } = fixture()
    runInContext(`clearAnnotationsByKind('${kind}')`, context)
    assert.equal(state.drawingClears, Number(['drawings', 'all'].includes(kind)))
    assert.equal(state.customClears, Number(['custom', 'all'].includes(kind)))
    assert.equal(state.analysisLevels.length, ['analysis', 'all'].includes(kind) ? 1 : 2)
  }
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
