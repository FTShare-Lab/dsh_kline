import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const html = readFileSync(new URL('../view/kline.html', import.meta.url), 'utf8')
const source = html.slice(html.indexOf('/* Curated workbench:'), html.indexOf('function resetChartViewport('))

function fixture(type: string, selectedId: string | null = null) {
  const fields: Record<string, any> = {
    workbenchType: { value: type }, workbenchName: { value: '测试' }, workbenchColor: { value: 'info' },
    workbenchPeriod: { value: '20' }, workbenchDeviation: { value: '2' }, workbenchPrice: { value: '123' },
    workbenchRatios: { value: '0,0.236,0.382,0.5,0.618,0.786,1' }, workbenchMidline: { value: 'yes' }, workbenchFill: { value: 'yes' },
    workbenchStatus: { textContent: '' },
  }
  const calls: Array<{ name: string; args: any }> = []
  const context: any = {
    document: { getElementById: (id: string) => fields[id] },
    window: { __DSH_KLINE_OBSERVATION__: { ok: true, context_ref: 'a'.repeat(32), revision: 7,
      source_status: { phase: 'aligned' } } },
    lastChartPayload: { _live_chart_session: 'b'.repeat(32) },
    captureChartContext: () => ({ state: 'ready', source_chart_session: 'b'.repeat(32), drawings: [] }),
    currentSymbol: 'TEST.X', currentCandles: [{ time: 1, close: 100 }],
    currentInterval: 'day',
    callTool: async (name: string, args: any) => {
      calls.push({ name, args })
      if (name === 'workbench_run_ta') return { structuredContent: { ok: true, result_ref: 'c'.repeat(64),
        loaded_bars: 120, summary: args.name === 'BBANDS'
          ? { upperband: { latest: { value: 130 }, valid_count: 101 }, middleband: { latest: { value: 120 } }, lowerband: { latest: { value: 110 } } }
          : { real: { latest: { value: 123.456 }, valid_count: 101 } },
        selectable_render_targets: [{ kind: args.name === 'BBANDS' ? 'price_band' : 'series_line' }] } }
      if (name === 'workbench_run_chart_function') return { structuredContent: { ok: true, result_ref: 'd'.repeat(64) } }
      if (name === 'workbench_prepare_edit') return { structuredContent: { ok: true, chart_session: 'e'.repeat(32), object: { id: 'line_1' } } }
      if (name === 'workbench_apply_edit') return { structuredContent: { ok: true, apply_status: 'queued' } }
      if (name === 'workbench_edit_status') return { structuredContent: { ok: true, apply_status: 'applied' } }
      throw Error(name)
    },
    crypto: { randomUUID: () => 'request-1' }, sleep: async () => {},
  }
  const api = runInNewContext(source + ';({ state: workbenchState, proposal: workbenchProposal, apply: workbenchApplyProposal, style: workbenchStyleOrDelete, signature: workbenchParameterSignature, begin: beginWorkbenchPick, replace: beginWorkbenchReplace, point: workbenchPoint })', context)
  api.state.selectedId = selectedId
  return { api, calls, fields, context }
}

test('curated TA proposal is read-only until confirmation and carries only a bound result reference', async () => {
  const { api, calls } = fixture('sma')
  const proposal = await api.proposal('create')
  assert.deepEqual(calls.map(call => call.name), ['workbench_run_ta'])
  assert.equal(calls[0].args.name, 'SMA')
  assert.equal(calls[0].args.parameters.timeperiod, 20)
  assert.equal(proposal.edit.kind, 'series_line')
  assert.equal(proposal.edit.ta_result_ref, 'c'.repeat(64))
  assert.ok(!('values' in proposal.edit))
  assert.equal(proposal.binding.expected_revision, 7)
  assert.match(proposal.preview, /real 123\.46；有效 101\/120 根/)
})

test('first agent chart uses its mounted source before any live replacement exists', async () => {
  const { api, context } = fixture('sma')
  context.lastChartPayload = {}
  context.window.__DSH_KLINE_INITIAL_CHART_SESSION__ = 'b'.repeat(32)
  const proposal = await api.proposal('create')
  assert.equal(proposal.binding.chart_session, 'b'.repeat(32))
})

test('channel proposal sends explicit three anchors to deterministic function, never auto-picks', async () => {
  const { api, calls } = fixture('channel')
  await assert.rejects(() => api.proposal('create'), /还需在图上点选 3 根 K 线/)
  assert.equal(calls.length, 0)
  api.state.anchors = [{ time: 10, price: 100 }, { time: 30, price: 120 }, { time: 20, price: 90 }]
  const proposal = await api.proposal('create')
  assert.equal(calls[0].name, 'workbench_run_chart_function')
  assert.equal(calls[0].args.function, 'parallel_channel')
  assert.equal(calls[0].args.parameters.parallel_time, '20')
  assert.equal(proposal.edit.result_ref, 'd'.repeat(64))
})

test('ABC update is one named-point mutation, not a replacement of the group', async () => {
  const { api, calls, context } = fixture('abc', 'poly_1')
  const original = [10, 20, 30].map((time, index) => ({ label: 'ABC'[index], time, price: 100 + index }))
  context.captureChartContext = () => ({ state: 'ready', source_chart_session: 'b'.repeat(32),
    drawings: [{ id: 'poly_1', kind: 'labeled_polyline', origin: 'ai', interval: 'day', points: original }] })
  api.state.anchors = original.map(point => ({ time: point.time, price: point.price }))
  api.state.anchors[2].price = 108
  const proposal = await api.proposal('update')
  assert.equal(calls.length, 0)
  assert.equal(proposal.edit.point_label, 'C')
  assert.equal(proposal.edit.point_price, 108)
  assert.ok(!('points' in proposal.edit))
  assert.ok(!('result_ref' in proposal.edit))
})

test('confirmation uses prepare, apply, then exact candidate status', async () => {
  const { api, calls } = fixture('horizontal')
  const proposal = await api.proposal('create')
  assert.equal(calls.length, 0)
  const outcome = await api.apply(proposal)
  assert.deepEqual(calls.map(call => call.name), ['workbench_prepare_edit', 'workbench_apply_edit', 'workbench_edit_status'])
  assert.equal(calls[0].args.edit.price, 123)
  assert.equal(calls[1].args.candidate_chart_session, 'e'.repeat(32))
  assert.equal(outcome.status.apply_status, 'applied')
})

test('style update refuses to silently ignore a changed TA period', async () => {
  const { api, calls, fields, context } = fixture('sma', 'series_1')
  context.lastChartPayload.chartCommands = [{ id: 'series_1', source: { kind: 'sma', period: 20 }, condition: null }]
  context.captureChartContext = () => ({ state: 'ready', source_chart_session: 'b'.repeat(32),
    drawings: [{ id: 'series_1', kind: 'series_line', origin: 'ai', interval: 'day' }] })
  api.state.selectedParameters = api.signature({ type: 'sma', period: 20 })
  fields.workbenchPeriod.value = '21'
  await api.style('update')
  assert.equal(calls.length, 0)
  assert.match(fields.workbenchStatus.textContent, /请先预览提案/)
})

test('the workbench keeps curated objects and lists old drawings without a second create tool', () => {
  for (const label of ['SMA 均线', 'EMA 均线', 'BOLL 价带', '水平线', '趋势线', '平行通道', '平台框', '斐波那契', 'ABC（手动选点）'])
    assert.ok(html.includes(label), label)
  assert.match(html, /class="workbench-legacy"[\s\S]*id="drawingList"/)
  assert.doesNotMatch(html, /id="drawingPopover"|data-drawing-type=/)
  assert.match(html, /id="drawingWorkbench"/)
  assert.match(html, /id="workbenchPreview"/)
  assert.match(html, /if \(WORKBENCH_ANCHORS\[workbenchType\(\)\] && workbenchType\(\) !== "horizontal"\) beginWorkbenchPick\(\)/)
  assert.match(html, /id="workbenchAdvanced"/)
})

test('workbench waits for a publication of the current chart before using a stale source', async () => {
  const { api, context, calls } = fixture('horizontal')
  let notifications = 0
  context.window.__DSH_KLINE_REPORT_CONTEXT__ = () => { notifications++ }
  context.window.__DSH_KLINE_SOURCE_KEY__ = () => 'new-chart'
  context.window.__DSH_KLINE_OBSERVATION__.observed_source_key = 'old-chart'
  await assert.rejects(() => api.proposal('create'), /当前图已变化，正在重新核对/)
  assert.equal(notifications, 1)
  assert.equal(calls.length, 0)
  context.window.__DSH_KLINE_OBSERVATION__.observed_source_key = 'new-chart'
  assert.equal((await api.proposal('create')).binding.chart_session, 'b'.repeat(32))
  context.window.__DSH_KLINE_OBSERVATION__.source_status = { phase: 'blocked' }
  await assert.rejects(() => api.proposal('create'), /当前图已变化，正在重新核对/)
})

test('channel picking accepts three distinct bars while ordinary range selection remains separate', () => {
  const { api, context, fields } = fixture('channel')
  fields.workbenchConfirm = { disabled: false }
  fields.toolbarHint = { textContent: '' }
  fields.drawingWorkbench = { classList: { contains: () => true } }
  context.currentCandles = [{ time: 10, close: 100 }, { time: 20, close: 90 }, { time: 30, close: 120 }]
  context.setDrawingCaptureActive = () => {}
  context.t = () => '普通区间选择'
  context.renderWorkbenchAnchors = () => context.syncWorkbenchPickUi()
  api.begin()
  assert.equal(fields.workbenchConfirm.disabled, true)
  api.point({ time: 10, close: 100 })
  assert.match(fields.workbenchStatus.textContent, /1\/3/)
  api.point({ time: 30, close: 120 })
  assert.match(fields.workbenchStatus.textContent, /2\/3/)
  api.point({ time: 40, close: 80 })
  assert.match(fields.workbenchStatus.textContent, /起点和终点之间/)
  assert.equal(api.state.anchors.length, 2)
  api.point({ time: 20, close: 90 })
  assert.equal(api.state.anchors.length, 3)
  assert.equal(fields.workbenchConfirm.disabled, false)
  assert.equal(api.state.picking, false)
})

test('reselecting a single channel anchor preserves its peers and invalidates an old preview', () => {
  const { api, context, fields } = fixture('channel')
  fields.workbenchConfirm = { disabled: false, textContent: '保存到图表' }
  fields.toolbarHint = { textContent: '' }
  fields.drawingWorkbench = { classList: { contains: () => true } }
  context.setDrawingCaptureActive = () => {}
  context.t = () => '普通区间选择'
  context.renderWorkbenchAnchors = () => context.syncWorkbenchPickUi()
  api.state.anchors = [{ time: 10, price: 100 }, { time: 30, price: 120 }, { time: 20, price: 90 }]
  api.state.pending = { preview: 'old' }
  api.state.candidate = { ref: 'd'.repeat(64) }
  api.replace(1)
  assert.equal(api.state.replaceIndex, 1)
  assert.equal(api.state.pending, null)
  assert.equal(api.state.candidate, null)
  api.point({ time: 15, close: 121 })
  assert.equal(api.state.anchors[1].time, 30)
  api.point({ time: 35, close: 121 })
  assert.equal(api.state.anchors[0].time, 10)
  assert.equal(api.state.anchors[1].time, 35)
  assert.equal(api.state.anchors[2].time, 20)
  assert.equal(api.state.picking, false)
  assert.equal(fields.workbenchConfirm.textContent, '预览图形')
})

test('reviewed channel candidate uses only its bound result reference and selection number', async () => {
  const { api, calls, context } = fixture('channel')
  api.state.anchors = [{ time: 10, price: 100 }, { time: 30, price: 120 }, { time: 20, price: 90 }]
  api.state.candidate = { ref: 'f'.repeat(64), number: 2, type: 'channel',
    binding: { context_ref: 'a'.repeat(32), expected_revision: 7, chart_session: 'b'.repeat(32), symbol: 'TEST.X' } }
  const proposal = await api.proposal('create')
  assert.equal(calls.length, 0)
  assert.equal(proposal.edit.candidate_result_ref, 'f'.repeat(64))
  assert.equal(proposal.edit.candidate_number, 2)
  assert.equal(proposal.edit.user_confirmed_candidate, true)
  assert.ok(!('result_ref' in proposal.edit))
  context.window.__DSH_KLINE_OBSERVATION__.revision = 8
  await assert.rejects(() => api.proposal('create'), /候选与当前图不匹配/)
})

test('channel preview draws both edges and optional midline without an endpoint-to-offset diagonal', () => {
  const elements: Array<{ tag: string; attrs: Record<string, string> }> = []
  const svg = { replaceChildren: () => { elements.length = 0 }, setAttribute: () => {},
    append: (element: any) => elements.push(element) }
  const chart = { clientWidth: 300, clientHeight: 200 }
  const context: any = {
    document: {
      getElementById: (id: string) => id === 'workbenchPreview' ? svg : id === 'klineChart' ? chart : null,
      createElementNS: (_: string, tag: string) => ({ tag, attrs: {} as Record<string, string>,
        setAttribute(key: string, value: string) { this.attrs[key] = value } }),
    },
    currentCandles: [{ time: 10 }, { time: 20 }, { time: 30 }],
    kchart: { convertToPixel: ([point]: any[]) => [{ x: point.timestamp / 1000, y: point.value }] },
  }
  const api = runInNewContext(source + ';({ state: workbenchState, preview: drawWorkbenchPreview })', context)
  api.state.anchors = [{ time: 10, price: 100 }, { time: 30, price: 120 }, { time: 20, price: 90 }]
  let midline = 'yes'
  context.document.getElementById = (id: string) => id === 'workbenchPreview' ? svg
    : id === 'klineChart' ? chart : id === 'workbenchType' ? { value: 'channel' }
    : id === 'workbenchMidline' ? { value: midline } : null
  api.preview()
  const lines = elements.filter(element => element.tag === 'line').map(element => element.attrs)
  assert.deepEqual(lines.map(line => [line.x1, line.y1, line.x2, line.y2]), [
    ['10', '100', '30', '120'], ['10', '80', '30', '100'], ['10', '90', '30', '110'],
  ])
  midline = 'no'
  api.preview()
  assert.equal(elements.filter(element => element.tag === 'line').length, 2)
})
