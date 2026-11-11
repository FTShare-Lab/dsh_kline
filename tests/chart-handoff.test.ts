import assert from 'node:assert/strict'
import test from 'node:test'
import { handoffLiveChart, liveChartFor, observeLiveCharts } from '../src/client/chart-handoff.ts'
import type { Sessions } from '../src/client/conversation.ts'

function host() {
  let current = 'A'
  const sessions: Sessions = {
    list: { getSnapshot: () => ({ current }), subscribe: () => () => {} },
    binding: () => undefined,
  }
  return { sessions, select: (id: string) => { current = id } }
}
const chart = { session: 'a'.repeat(32), order: 1 }

test('a tab mounted after a live result receives exactly its conversation chart', () => {
  const h = host()
  assert.equal(liveChartFor(h.sessions, 'A'), undefined)
  handoffLiveChart(h.sessions, 'A', chart)
  assert.deepEqual(liveChartFor(h.sessions, 'A'), chart)
  h.select('B')
  assert.equal(liveChartFor(h.sessions, 'A'), undefined)
  assert.equal(liveChartFor(h.sessions, 'B'), undefined)
  assert.equal(liveChartFor(h.sessions), undefined)
})
test('inactive results, another host instance and older completions cannot replace a live chart', () => {
  const h = host()
  handoffLiveChart(h.sessions, 'B', chart)
  h.select('B')
  assert.equal(liveChartFor(h.sessions, 'B'), undefined)
  h.select('A')
  handoffLiveChart(h.sessions, 'A', chart)
  handoffLiveChart(h.sessions, 'A', {session: 'b'.repeat(32), order: 0})
  assert.deepEqual(liveChartFor(h.sessions, 'A'), chart)
  assert.equal(liveChartFor(host().sessions, 'A'), undefined)
})

const entries = (token: string, order: number) => [
  {type: 'event', event: {type: 'tool/call', time: order, data: {callId: token, name: 'mcp__dsh_kline__analyze_kline'}}},
  {type: 'event', event: {type: 'tool/result', time: order + 1, data: {message: {role: 'tool', toolCallId: token,
    content: [{type: 'text', text: JSON.stringify({chart_session: token})}]}}}},
]
test('modern hydration and older-page loading never reveal charts; an immediate live append does', () => {
  const first = entries('a'.repeat(32), 1)
  const next = [...first, ...entries('b'.repeat(32), 3)]
  const observe = observeLiveCharts({entries: [], revision: 0, change: {kind: 'replace'}})
  assert.equal(observe({entries: first, revision: 1, change: {kind: 'replace'}}), undefined)
  assert.equal(observe({entries: first, revision: 2, change: {kind: 'prepend'}}), undefined)
  assert.deepEqual(observe({entries: next, revision: 3, change: {kind: 'append'}}), {session: 'b'.repeat(32), order: 3})
  assert.equal(observe({entries: next, revision: 3, change: {kind: 'append'}}), undefined)
  assert.equal(observe({entries: next, revision: 4, change: {kind: 'settle-assistant'}}), undefined)
})
